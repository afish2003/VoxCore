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

Emotion directives (optional):
  The LLM can prefix its response with [emotion:tag] to request a specific
  delivery from v3. Example: "[emotion:cheerful] Great news, your query worked!"
  Supported tags: neutral, cheerful, empathetic, excited, serious, playful, apologetic.
  The tag is stripped before synthesis. Tags are ignored when Flash is selected.
  If no tag is present, TTS_EMOTION_DEFAULT is used.

Fallback:
  If v3 synthesis fails for any reason (API error, timeout, unsupported format),
  the request is automatically retried using Flash. The error is logged as a
  warning but does not propagate to the caller.

Timing:
  Each synthesize() call logs: model, emotion (if v3), character count, elapsed time.
  This gives enough signal to tune routing thresholds and compare TTFB.

Config (set in .env):
  TTS_PROVIDER=elevenlabs_hybrid
  TTS_FAST_MODEL=eleven_flash_v2_5
  TTS_EMOTE_MODEL=eleven_v3
  TTS_MODE=hybrid | flash_only | v3_only
  TTS_EMOTION_DEFAULT=neutral
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

# Emotion → v3 voice_settings.style value (Flash ignores this entirely)
_EMOTION_STYLE: dict[str, float] = {
    "neutral":    0.30,
    "cheerful":   0.70,
    "empathetic": 0.50,
    "excited":    0.85,
    "serious":    0.15,
    "playful":    0.75,
    "apologetic": 0.40,
}
_DEFAULT_STYLE = 0.30  # fallback when emotion tag is unrecognised

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


class HybridElevenLabsTTS(TTSProvider):
    """
    ElevenLabs TTS that routes between Flash v2.5 (low latency) and
    v3 (expressive) based on response length, ACK pattern, and emotion
    directives. Falls back to Flash automatically if v3 fails.
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

        # Base voice settings shared by both models; style is overridden per call
        self._base_voice_settings = {
            "stability": config.elevenlabs_stability,
            "similarity_boost": config.elevenlabs_similarity,
            "use_speaker_boost": True,
        }

        logger.info(
            f"HybridElevenLabs TTS ready — "
            f"mode={self.mode}, fast={self.fast_model}, emote={self.emote_model}"
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
          3. For v3: try pcm_22050 → pcm_24000 on 422 → Flash fallback on any error
          4. For Flash: single attempt with pcm_22050
        """
        safe_text = text[: self.max_chars]
        if len(text) > self.max_chars:
            logger.warning(f"TTS text truncated: {len(text)} -> {self.max_chars} chars")

        # Extract optional [emotion:tag] from the start of the text
        emotion, clean_text = self._extract_emotion(safe_text)

        t0 = time.perf_counter()

        if self.mode == "flash_only":
            wav = self._synthesize_flash(clean_text)
            self._log_timing("flash_only", self.fast_model, emotion, clean_text, t0)
            return wav

        if self.mode == "v3_only":
            wav = self._synthesize_v3_with_fallback(clean_text, emotion, t0)
            return wav

        # hybrid: route based on text characteristics
        if self._is_short_or_ack(clean_text):
            wav = self._synthesize_flash(clean_text)
            self._log_timing("hybrid→flash", self.fast_model, None, clean_text, t0)
            return wav
        else:
            wav = self._synthesize_v3_with_fallback(clean_text, emotion, t0)
            return wav

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def _extract_emotion(self, text: str) -> tuple[str, str]:
        """
        Strip optional [emotion:tag] prefix and return (emotion, clean_text).
        Falls back to tts_emotion_default if no tag is present.
        """
        m = _EMOTION_TAG_RE.match(text)
        if m:
            tag = m.group(1).lower()
            if tag not in _EMOTION_STYLE:
                logger.debug(f"Unrecognised emotion tag '{tag}', using '{self.emotion_default}'")
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
        """Synthesize using Flash v2.5 (pcm_22050, single attempt)."""
        style = _EMOTION_STYLE.get(self.emotion_default, _DEFAULT_STYLE)
        return self._call_elevenlabs(
            text, self.fast_model, style, _FLASH_PCM_FORMAT, _FLASH_SAMPLE_RATE
        )

    def _synthesize_v3_with_fallback(
        self, text: str, emotion: str, t0: float
    ) -> bytes:
        """
        Attempt v3 synthesis; fall back to Flash on any failure.

        PCM format negotiation: tries pcm_22050 first; if the API returns
        HTTP 422 (unsupported format for this model), retries with pcm_24000.
        Any other exception triggers the Flash fallback immediately.
        """
        style = _EMOTION_STYLE.get(emotion, _DEFAULT_STYLE)

        for pcm_format in _V3_PCM_FORMATS:
            sample_rate = _PCM_SAMPLE_RATES[pcm_format]
            try:
                wav = self._call_elevenlabs(
                    text, self.emote_model, style, pcm_format, sample_rate
                )
                self._log_timing(
                    f"v3({pcm_format})", self.emote_model, emotion, text, t0
                )
                return wav
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 422:
                    logger.debug(
                        f"v3 rejected {pcm_format} (422), trying next format"
                    )
                    continue  # try the next PCM format
                # Non-422 HTTP error → fall through to Flash fallback
                logger.warning(
                    f"v3 TTS HTTP error ({e}), falling back to Flash"
                )
                break
            except Exception as e:
                logger.warning(
                    f"v3 TTS failed ({type(e).__name__}: {e}), falling back to Flash"
                )
                break

        # Flash fallback
        logger.info("  [TTS fallback] using Flash v2.5")
        wav = self._synthesize_flash(text)
        self._log_timing("fallback→flash", self.fast_model, None, text, t0)
        return wav

    # ------------------------------------------------------------------
    # Core API call (shared by both models)
    # ------------------------------------------------------------------

    def _call_elevenlabs(
        self,
        text: str,
        model_id: str,
        style: float,
        pcm_format: str,
        sample_rate: int,
    ) -> bytes:
        """
        POST to ElevenLabs TTS endpoint, return WAV bytes.

        Same transport as ElevenLabsTTS (HTTP REST, requests.post).
        The style parameter drives expressiveness — higher = more emotive.
        """
        voice_settings = {**self._base_voice_settings, "style": style}
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": voice_settings,
        }

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
