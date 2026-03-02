"""
STT provider factory.

Selects the STT implementation based on config.stt_provider.
To add a new provider: subclass STTProvider, then add a case here
and set STT_PROVIDER=your_provider in .env.
"""
from voxcore.config import Config
from voxcore.stt.base import STTProvider
from voxcore.stt.whisper import WhisperSTT


def get_stt(config: Config) -> STTProvider:
    """
    Return the configured STT provider.

    Supported providers (set STT_PROVIDER in .env):
        whisper  - faster-whisper, runs locally (default)
    """
    provider = config.stt_provider.lower()

    if provider == "whisper":
        return WhisperSTT(config)

    raise ValueError(
        f"Unknown STT_PROVIDER: '{provider}'. "
        f"Supported options: 'whisper'"
    )
