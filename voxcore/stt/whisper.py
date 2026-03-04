"""
Whisper STT provider (faster-whisper).

Converts raw PCM bytes to text locally, with no network calls.
The model is loaded once at construction and reused for every transcription.
No global state - the model is owned by this class instance.
"""
import io
import re
import wave
import logging

from faster_whisper import WhisperModel

from voxcore.config import Config
from voxcore.stt.base import STTProvider

logger = logging.getLogger(__name__)

# Whisper hallucination artifacts to strip from transcripts
_HALLUCINATION_RE = re.compile(
    r"\[.*?\]|\(.*?\)|♪|\.{3,}", re.IGNORECASE
)


class WhisperSTT(STTProvider):
    """
    Local speech-to-text using faster-whisper.

    Supports all Whisper model sizes (tiny / base / small / medium / large-v3)
    and both CPU (int8) and CUDA (float16) compute types, set via config.
    """

    def __init__(self, config: Config):
        device = config.whisper_device
        compute_type = "float16" if device == "cuda" else "int8"

        logger.info(
            f"Loading Whisper model '{config.whisper_model}' on {device} ({compute_type})"
        )
        self.model = WhisperModel(
            config.whisper_model,
            device=device,
            compute_type=compute_type,
        )
        self.lang = config.whisper_lang if config.whisper_lang != "auto" else None
        self.sample_rate = config.sample_rate
        self.channels = config.channels
        self.beam_size = config.whisper_beam_size
        self.vad_filter = config.whisper_vad_filter
        self.initial_prompt = config.whisper_initial_prompt or None

        logger.info("Whisper model ready")
        logger.info(
            f"  beam_size={self.beam_size}, vad_filter={self.vad_filter}, "
            f"initial_prompt={self.initial_prompt!r}"
        )

    def transcribe(self, audio_bytes: bytes) -> str:
        """
        Transcribe raw PCM bytes to text.

        Wraps the PCM in a WAV container (in memory) so faster-whisper
        can parse it without writing to disk.
        """
        wav_bytes = self._pcm_to_wav(audio_bytes)
        wav_file = io.BytesIO(wav_bytes)
        segments, _ = self.model.transcribe(
            wav_file,
            language=self.lang,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            initial_prompt=self.initial_prompt,
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text for seg in segments).strip()
        return self._clean_transcript(text)

    def _pcm_to_wav(self, pcm_bytes: bytes) -> bytes:
        """Wrap raw 16-bit PCM bytes in a WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)          # 16-bit = 2 bytes per sample
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    def _clean_transcript(self, text: str) -> str:
        """Remove common Whisper hallucination artifacts."""
        cleaned = _HALLUCINATION_RE.sub("", text).strip()
        return " ".join(cleaned.split()) if cleaned else ""
