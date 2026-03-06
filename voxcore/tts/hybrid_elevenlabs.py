"""
HybridElevenLabsTTS — adaptive routing between Flash v2.5 and v3.

Transport: both models use the same HTTP REST endpoint as the existing
ElevenLabsTTS provider (requests.post). No WebSocket or streaming changes.

Output format: requests pcm_22050 for both models.
If v3 rejects pcm_22050 (HTTP 422), automatically retries with pcm_24000.
Both are raw PCM formats wrapped in a WAV container — no pydub/ffmpeg needed.

Routing (TTS_MODE=hybrid):
  Flash v2.5 — for short or utility responses:
    * text length <= SHORT_THRESHOLD characters, OR
    * text starts with a common ACK phrase (case-insensitive)
  v3 — for all other (longer / narrative) responses

Voice settings — Flash and v3 are independent:
  Flash uses ELEVENLABS_STABILITY / ELEVENLABS_SIMILARITY / ELEVENLABS_STYLE,
  the same values as the single-model ElevenLabsTTS provider.
  v3 uses its own TTS_V3_* preset (high stability, low style) so it stays calm
  regardless of how expressive Flash is tuned. v3 settings are logged at startup.

Emotion directives (optional):
  The LLM can prefix its response with [emotion:tag] to nudge v3 delivery.
  Example: "[emotion:cheerful] Great news, your query worked!"
  Supported tags: neutral, cheerful, empathetic, excited, serious, playful, apologetic.
  Tag values are clamped to a subtle range (max 0.15) so v3 never becomes bubbly.
  Tags are stripped before synthesis and ignored when Flash is selected.
  If no tag is present, TTS_EMOTION_DEFAULT is used (default: neutral → style 0.0).

Text normalisation (TTS_V3_TEXT_NORMALIZE, default true):
  v3 over-reacts to punctuation that LLMs routinely produce. The normaliser:
    - Collapses repeated !! / !!! → single period
    - Converts sentence-ending ! → period
    - Folds ALL-CAPS words (3+ chars) to Title Case
    - Strips basic emoji (U+1F300–U+1F9FF, U+2600–U+27BF)
  Applied only to v3 synthesis; Flash receives the original text unchanged.

Fallback:
  If v3 synthesis fails for any reason (API error, timeout, unsupported format),
  the request is automatically retried using Flash. The error is logged as a
  warning but does not propagate to the caller.

Timing:
  Each synthesize() call logs: route, model, emotion (v3 only), char count,
  elapsed time. v3 voice settings are also logged once at startup.

Config (set in .env):
  TTS_PROVIDER=elevenlabs_hybrid
  TTS_FAST_MODEL=eleven_flash_v2_5
  TTS_EMOTE_MODEL=eleven_v3
  TTS_MODE=hybrid | flash_only | v3_only
  TTS_EMOTION_DEFAULT=neutral
  TTS_V3_STABILITY=0.80      (high = calm prosody, no pitch spikes)
  TTS_V3_SIMILARITY=0.75
  TTS_V3_STYLE=0.0           (expressiveness off by default)
  TTS_V3_TEXT_NORMALIZE=true
"""
import io
import re
import time
import wave
import logging
import requests

from voxcore.config import Config
from voxcore.tts.base import TTSProvider

logger = logging.getLogger(__name__)

# --- Routing constants ---
_SHORT_THRESHOLD = 80  # chars; at or below this length → Flash
_ACK_PREFIXES = (
    "got it", "sure", "one sec", "opening", "checking",
    "done", "ok,", "alright", "understood",
)

# --- Emotion directive ---
_EMOTION_TAG_RE = re.compile(r"^\[emotion:(\w+)\]\s*", re.IGNORECASE)

# Emotion → v3 style offset.
# Values are deliberately low (max 0.15) — v3 is already more expressive than
# Flash at equivalent settings, so we nudge rather than push.
# These are ADDED on top of TTS_V3_STYLE; the final style sent is clamped to [0, 1].
_EMOTION_STYLE_V3: dict[str, float] = {
    "neutral":    0.00,   # no lift; let base style carry it
    "cheerful":   0.10,
    "empathetic": 0.08,
    "excited":    0.15,   # ceiling — keeps "excited" grounded on v3
    "serious":    0.00,
    "playful":    0.12,
    "apologetic": 0.05,
}

# --- PCM format negotiation for v3 ---
# Try these in order; if the first gets a 422, fall back to the next.
# Both are raw signed 16-bit PCM so no decoder is needed — just WAV wrapping.
_V3_PCM_FORMATS = ["pcm_22050", "pcm_24000"]
_PCM_SAMPLE_RATES: dict[str, int] = {"pcm_22050": 22050, "pcm_24000": 24000}

# Flash always uses this format (known to work)
_FLASH_PCM_FORMAT = "pcm_22050"
_FLASH_SAMPLE_RATE = 22050

_PCM_CHANNELS = 1
_PCM_SAMPWIDTH = 2  # 16-bit = 2 bytes

# Emoji ranges for normalizer
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF]")


class HybridElevenLabsTTS(TTSProvider):
    """
    ElevenLabs TTS that routes between Flash v2.5 (low latency) and
    v3 (expressive) based on response length, ACK pattern, and emotion
    directives. Falls back to Flash automatically if v3 fails.

    Flash and v3 use independent voice_settings so v3's calm-ARVIS
    preset is never contaminated by Flash's tuning (and vice versa).
    """

    def __init__(self, config: Config):
        if not config.elevenlabs_api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY is not set. "
                "Get one at https://elevenlabs.io/app/settings/api-keys"
            )
        if not config.elevenlabs_voice_id:
            raise RuntimeError(
                "ELEVENLABS_VOICE_ID is not set. "
                "Find voice IDs at https://elevenlabs.io/app/voice-library"
            )

        self.api_key = config.elevenlabs_api_key
        self.voice_id = config.elevenlabs_voice_id
        self.max_chars = config.tts_max_chars
        self.fast_model = config.tts_fast_model
        self.emote_model = config.tts_emote_model
        self.mode = config.tts_mode.lower()
        self.emotion_default = config.tts_emotion_default.lower()
        self.v3_text_normalize = config.tts_v3_text_normalize
        self._v3_base_style = config.tts_v3_style
        self._v3_speed = config.tts_v3_speed

        # Flash voice settings — same as the standalone ElevenLabsTTS provider.
        # Driven by the existing ELEVENLABS_* vars so behaviour is unchanged.
        self._flash_voice_settings: dict = {
            "stability":       config.elevenlabs_stability,
            "similarity_boost": config.elevenlabs_similarity,
            "style":           config.elevenlabs_style,
            "use_speaker_boost": True,
        }

        # v3 voice settings — independent "calm ARVIS" preset.
        # High stability kills prosody variability (the main cause of bubbly delivery).
        # style=0.0 by default; emotion tags add a small offset on top.
        self._v3_voice_settings: dict = {
            "stability":       config.tts_v3_stability,
            "similarity_boost": config.tts_v3_similarity,
            "style":           config.tts_v3_style,
            "use_speaker_boost": True,
        }

        logger.info(
            f"HybridElevenLabs TTS ready — "
            f"mode={self.mode}, fast={self.fast_model}, emote={self.emote_model}"
        )
        # Log v3 preset once so it's easy to iterate without adding debug prints
        logger.info(
            f"v3 voice settings — "
            f"stability={config.tts_v3_stability}, "
            f"similarity={config.tts_v3_similarity}, "
            f"style={config.tts_v3_style}, "
            f"speed={config.tts_v3_speed}, "
            f"text_normalize={config.tts_v3_text_normalize}"
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def synthesize(self, text: str) -> bytes:
        """
        Route to Flash or v3, synthesize, and return WAV bytes.

        Routing order:
          1. Extract [emotion:tag] prefix from text (strips tag, keeps clean text)
          2. Determine model from tts_mode and routing rules
          3. For v3: apply text normalizer → try pcm_22050 → pcm_24000 on 422
                     → Flash fallback on any other error
          4. For Flash: single attempt with pcm_22050, original text unchanged
        """
        safe_text = text[: self.max_chars]
        if len(text) > self.max_chars:
            logger.warning(f"TTS text truncated: {len(text)} -> {self.max_chars} chars")

        # Extract optional [emotion:tag] from the start of the text
        emotion, clean_text = self._extract_emotion(safe_text)

        t0 = time.perf_counter()

        if self.mode == "flash_only":
            wav = self._synthesize_flash(clean_text)
            self._log_timing("flash_only", self.fast_model, None, clean_text, t0)
            return wav

        if self.mode == "v3_only":
            return self._synthesize_v3_with_fallback(clean_text, emotion, t0)

        # hybrid: route based on text characteristics
        if self._is_short_or_ack(clean_text):
            wav = self._synthesize_flash(clean_text)
            self._log_timing("hybrid→flash", self.fast_model, None, clean_text, t0)
            return wav
        else:
            return self._synthesize_v3_with_fallback(clean_text, emotion, t0)

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def _extract_emotion(self, text: str) -> tuple[str, str]:
        """
        Strip optional [emotion:tag] prefix and return (emotion, clean_text).
        Falls back to tts_emotion_default if no tag is present.
        Unknown tags are silently remapped to the default.
        """
        m = _EMOTION_TAG_RE.match(text)
        if m:
            tag = m.group(1).lower()
            if tag not in _EMOTION_STYLE_V3:
                logger.debug(
                    f"Unrecognised emotion tag '{tag}', "
                    f"using '{self.emotion_default}'"
                )
                tag = self.emotion_default
            return tag, text[m.end():]
        return self.emotion_default, text

    def _is_short_or_ack(self, text: str) -> bool:
        """Return True if the text should be routed to Flash (short / utility)."""
        if len(text) <= _SHORT_THRESHOLD:
            return True
        lower = text.lower().strip()
        return any(lower.startswith(prefix) for prefix in _ACK_PREFIXES)

    # ------------------------------------------------------------------
    # Synthesis paths
    # ------------------------------------------------------------------

    def _synthesize_flash(self, text: str) -> bytes:
        """
        Synthesize using Flash v2.5.
        Uses Flash-specific voice settings; text is passed through unchanged.
        """
        return self._call_elevenlabs(
            text,
            self.fast_model,
            self._flash_voice_settings,  # Flash's own stability/style settings
            _FLASH_PCM_FORMAT,
            _FLASH_SAMPLE_RATE,
        )

    def _synthesize_v3_with_fallback(
        self, text: str, emotion: str, t0: float
    ) -> bytes:
        """
        Attempt v3 synthesis with the calm-ARVIS preset; fall back to Flash on failure.

        Text normalisation: applied before synthesis if TTS_V3_TEXT_NORMALIZE=true.
        Emotion style: a small offset from _EMOTION_STYLE_V3 is added to the v3
        base style (TTS_V3_STYLE). The sum is clamped to [0.0, 1.0].

        PCM format: tries pcm_22050 first; on HTTP 422 retries with pcm_24000.
        Any other exception triggers the Flash fallback immediately.
        """
        # Optional text normalisation — Flash path is never touched
        synth_text = self._normalize_for_v3(text) if self.v3_text_normalize else text

        # Build v3 voice_settings: base preset + emotion style offset (clamped)
        emotion_offset = _EMOTION_STYLE_V3.get(emotion, 0.0)
        effective_style = min(1.0, max(0.0, self._v3_base_style + emotion_offset))
        v3_settings = {**self._v3_voice_settings, "style": effective_style}

        for pcm_format in _V3_PCM_FORMATS:
            sample_rate = _PCM_SAMPLE_RATES[pcm_format]
            try:
                wav = self._call_elevenlabs(
                    synth_text, self.emote_model, v3_settings, pcm_format, sample_rate,
                    speed=self._v3_speed,
                )
                self._log_timing(
                    f"v3({pcm_format})", self.emote_model, emotion, synth_text, t0
                )
                return wav
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 422:
                    logger.debug(
                        f"v3 rejected {pcm_format} (422), trying next format"
                    )
                    continue  # try the next PCM format
                # Non-422 HTTP error → fall through to Flash fallback
                logger.warning(f"v3 TTS HTTP error ({e}), falling back to Flash")
                break
            except Exception as e:
                logger.warning(
                    f"v3 TTS failed ({type(e).__name__}: {e}), falling back to Flash"
                )
                break

        # Flash fallback — use original text (not normalised) to preserve fidelity
        logger.info("  [TTS fallback] using Flash v2.5")
        wav = self._synthesize_flash(text)
        self._log_timing("fallback→flash", self.fast_model, None, text, t0)
        return wav

    # ------------------------------------------------------------------
    # Text normaliser (v3 only)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_for_v3(text: str) -> str:
        """
        Reduce punctuation / formatting that causes v3 to over-emote.
        Applied only to v3 synthesis; Flash receives original text unchanged.
        Controlled by TTS_V3_TEXT_NORMALIZE (default true).

        Rules applied in order:
          1. Repeated !! / !!! → single period
          2. Single sentence-ending ! → period
          3. ALL-CAPS words (3+ chars) → Title Case   (e.g. CRITICAL → Critical)
          4. Strip basic emoji (U+1F300–U+1F9FF, U+2600–U+27BF)
        """
        # Collapse multiple exclamation marks
        text = re.sub(r"!{2,}", ".", text)
        # Single sentence-ending exclamation → period
        text = re.sub(r"!(\s|$)", r".\1", text)
        # ALL-CAPS words → Title Case
        text = re.sub(r"\b([A-Z]{3,})\b", lambda m: m.group(1).title(), text)
        # Strip emoji
        text = _EMOJI_RE.sub("", text)
        return text.strip()

    # ------------------------------------------------------------------
    # Core API call (shared by both models)
    # ------------------------------------------------------------------

    def _call_elevenlabs(
        self,
        text: str,
        model_id: str,
        voice_settings: dict,
        pcm_format: str,
        sample_rate: int,
        speed: float | None = None,
    ) -> bytes:
        """
        POST to ElevenLabs TTS endpoint and return WAV bytes.

        Accepts a fully-formed voice_settings dict so Flash and v3 each
        provide their own independently-tuned values.

        speed: top-level payload parameter (1.0 = normal, <1.0 = slower).
               Only included when explicitly provided; Flash omits it entirely.
        """
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload: dict = {
            "text": text,
            "model_id": model_id,
            "voice_settings": voice_settings,
        }
        if speed is not None:
            payload["speed"] = speed

        response = requests.post(
            url,
            params={"output_format": pcm_format},
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return self._pcm_to_wav(response.content, sample_rate)

    # ------------------------------------------------------------------
    # PCM → WAV wrapping (same logic as ElevenLabsTTS)
    # ------------------------------------------------------------------

    @staticmethod
    def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
        """Wrap raw signed 16-bit PCM in a WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(_PCM_CHANNELS)
            wf.setsampwidth(_PCM_SAMPWIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    @staticmethod
    def _log_timing(
        route: str, model: str, emotion: str | None, text: str, t0: float
    ) -> None:
        emotion_str = f" emotion={emotion}" if emotion else ""
        logger.info(
            f"TTS [{route}] model={model}{emotion_str} "
            f"chars={len(text)} elapsed={time.perf_counter() - t0:.2f}s"
        )
