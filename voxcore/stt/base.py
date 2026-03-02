"""
Abstract interface for speech-to-text providers.

All STT backends must subclass STTProvider and implement transcribe().
The method receives raw 16-bit PCM audio bytes and returns a text string.

To add a new provider:
    1. Create voxcore/stt/your_provider.py
    2. Subclass STTProvider and implement transcribe()
    3. Register it in voxcore/stt/factory.py
    4. Set STT_PROVIDER=your_provider in .env
"""
from abc import ABC, abstractmethod


class STTProvider(ABC):
    """Base class for speech-to-text providers."""

    @abstractmethod
    def transcribe(self, audio_bytes: bytes) -> str:
        """
        Transcribe raw PCM audio to text.

        Args:
            audio_bytes: Raw 16-bit PCM audio at the configured sample rate.

        Returns:
            Transcribed text string. Empty string if no speech detected.
        """
        ...
