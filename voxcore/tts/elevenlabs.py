"""
ElevenLabs TTS provider.

Calls the ElevenLabs API and returns WAV bytes ready for playback.
No temporary files are created - audio stays in memory end-to-end.

Audio format: requests pcm_22050 (raw 16-bit PCM, 22050 Hz, mono) via the
output_format query parameter. The Accept header alone is not honoured
reliably by ElevenLabs - the API defaults to MP3 otherwise. The raw PCM
bytes are wrapped in a WAV container before returning so play_wav() works
without any changes.

Defaults to eleven_flash_v2_5 (lowest latency, lowest cost).
All settings are read from config, not from environment variables.
"""
import io
import wave
import logging
import requests

from voxcore.config import Config
from voxcore.tts.base import TTSProvider

logger = logging.getLogger(__name__)

# ElevenLabs output format: raw signed 16-bit PCM, 22050 Hz, mono.
# Avoids MP3 decoding and is natively playable via PyAudio.
_OUTPUT_FORMAT = "pcm_22050"
_PCM_SAMPLE_RATE = 22050
_PCM_CHANNELS = 1
_PCM_SAMPWIDTH = 2  # 16-bit = 2 bytes


class ElevenLabsTTS(TTSProvider):
    """ElevenLabs cloud TTS. Returns WAV audio bytes."""

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
        self.model_id = config.elevenlabs_model_id
        self.max_chars = config.tts_max_chars
        self.voice_settings = {
            "stability": config.elevenlabs_stability,
            "similarity_boost": config.elevenlabs_similarity,
            "style": config.elevenlabs_style,
            "use_speaker_boost": True,
        }
        logger.info(f"ElevenLabs TTS ready (voice: {self.voice_id}, model: {self.model_id})")

    def synthesize(self, text: str) -> bytes:
        """
        Call ElevenLabs API and return WAV bytes.

        Requests raw PCM via output_format query parameter (reliable),
        then wraps the PCM in a WAV container for play_wav() compatibility.
        """
        safe_text = text[: self.max_chars]
        if len(text) > self.max_chars:
            logger.warning(f"TTS text truncated: {len(text)} -> {self.max_chars} chars")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": safe_text,
            "model_id": self.model_id,
            "voice_settings": self.voice_settings,
        }

        logger.info(f"Synthesizing {len(safe_text)} chars via ElevenLabs")
        response = requests.post(
            url,
            params={"output_format": _OUTPUT_FORMAT},
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()

        return self._pcm_to_wav(response.content)

    def _pcm_to_wav(self, pcm_bytes: bytes) -> bytes:
        """Wrap raw PCM bytes in a WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(_PCM_CHANNELS)
            wf.setsampwidth(_PCM_SAMPWIDTH)
            wf.setframerate(_PCM_SAMPLE_RATE)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()
