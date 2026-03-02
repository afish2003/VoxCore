"""
Abstract interface for text-to-speech providers.

All TTS backends must subclass TTSProvider and implement synthesize().
The method returns WAV audio as bytes so the caller can play it
directly without touching the filesystem.

To add a new provider:
    1. Create voxcore/tts/your_provider.py
    2. Subclass TTSProvider and implement synthesize()
    3. Register it in voxcore/tts/factory.py
    4. Set TTS_PROVIDER=your_provider in .env
"""
from abc import ABC, abstractmethod


class TTSProvider(ABC):
    """Base class for text-to-speech providers."""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """
        Convert text to speech audio.

        Args:
            text: The text to speak.

        Returns:
            WAV audio as bytes. Ready to pass directly to the audio player.
        """
        ...
