"""
Porcupine wake word engine (Picovoice).

Uses Picovoice's built-in keywords (jarvis, computer, alexa, hey google,
hey siri, grasshopper, bumblebee, terminator, picovoice, porcupine).
A free access key is available at https://console.picovoice.ai/

Key design decision: the PyAudio input stream is opened and closed
around each detection cycle. This frees the audio device so the
Recorder can open a fresh stream to capture the user's utterance,
then the engine reopens its stream to resume idle listening.
This avoids device-conflict issues on Windows where simultaneous
input streams on the same device may fail.
"""
import struct
import logging
import pyaudio
import pvporcupine
from typing import Callable

from voxcore.config import Config
from voxcore.wake.base import WakeWordEngine

logger = logging.getLogger(__name__)


class PorcupineEngine(WakeWordEngine):
    """Wake word engine backed by Picovoice Porcupine."""

    def __init__(self, config: Config, on_wake: Callable[[], None]):
        super().__init__(on_wake)
        self.keyword = config.wake_keyword
        self.sensitivity = config.wake_sensitivity
        self.access_key = config.picovoice_access_key
        self.is_running = False

    def start(self) -> None:
        """
        Listen in a loop.

        Each iteration:
            1. Open Porcupine + audio stream
            2. Listen until wake word detected or stop() called
            3. Close stream (frees audio device)
            4. Call on_wake() if detected (pipeline runs here)
            5. Repeat
        """
        logger.info(f"Listening for wake word: '{self.keyword.upper()}'")
        self.is_running = True

        while self.is_running:
            detected = self._listen_until_wake()
            if detected and self.is_running:
                logger.info(f"Wake word detected: '{self.keyword.upper()}'")
                self.on_wake()  # blocks while pipeline runs; audio device is free

    def stop(self) -> None:
        """Signal the listening loop to exit."""
        self.is_running = False

    def _listen_until_wake(self) -> bool:
        """
        Open stream, read frames until wake word or stop signal.
        Always closes all resources before returning.

        Returns:
            True if wake word was detected.
            False if stop() was called.
        """
        porcupine = pvporcupine.create(
            access_key=self.access_key,
            keywords=[self.keyword],
            sensitivities=[self.sensitivity],
        )
        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length,
        )

        detected = False
        try:
            while self.is_running:
                raw = stream.read(porcupine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * porcupine.frame_length, raw)
                if porcupine.process(pcm) >= 0:
                    detected = True
                    break
        finally:
            stream.close()
            pa.terminate()
            porcupine.delete()

        return detected
