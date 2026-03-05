"""
TTS provider factory.

Selects the TTS implementation based on config.tts_provider.
To add a new provider: subclass TTSProvider, then add a case here
and set TTS_PROVIDER=your_provider in .env.
"""
from voxcore.config import Config
from voxcore.tts.base import TTSProvider
from voxcore.tts.elevenlabs import ElevenLabsTTS
from voxcore.tts.hybrid_elevenlabs import HybridElevenLabsTTS


def get_tts(config: Config) -> TTSProvider:
    """
    Return the configured TTS provider.

    Supported providers (set TTS_PROVIDER in .env):
        elevenlabs         - ElevenLabs Flash v2.5 only (default, lowest latency)
        elevenlabs_hybrid  - Adaptive: Flash for short/utility, v3 for expressive
    """
    provider = config.tts_provider.lower()

    if provider == "elevenlabs":
        return ElevenLabsTTS(config)

    if provider == "elevenlabs_hybrid":
        return HybridElevenLabsTTS(config)

    raise ValueError(
        f"Unknown TTS_PROVIDER: '{provider}'. "
        f"Supported options: 'elevenlabs', 'elevenlabs_hybrid'"
    )
