"""
TTS provider factory.

Selects the TTS implementation based on config.tts_provider.
To add a new provider: subclass TTSProvider, then add a case here
and set TTS_PROVIDER=your_provider in .env.
"""
from voxcore.config import Config
from voxcore.tts.base import TTSProvider
from voxcore.tts.elevenlabs import ElevenLabsTTS


def get_tts(config: Config) -> TTSProvider:
    """
    Return the configured TTS provider.

    Supported providers (set TTS_PROVIDER in .env):
        elevenlabs  - ElevenLabs cloud TTS (default)
    """
    provider = config.tts_provider.lower()

    if provider == "elevenlabs":
        return ElevenLabsTTS(config)

    raise ValueError(
        f"Unknown TTS_PROVIDER: '{provider}'. "
        f"Supported options: 'elevenlabs'"
    )
