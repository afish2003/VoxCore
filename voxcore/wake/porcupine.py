"""
Porcupine wake word engine (Picovoice).

Supports two detection modes:
  1. Built-in keyword (jarvis, computer, alexa, hey google, hey siri, etc.)
     Set WAKE_KEYWORD in .env; leave WAKE_KEYWORD_PATH empty.
  2. Custom trained .ppn model (e.g. "harvest" for ARVIS recall)
     Set WAKE_KEYWORD_PATH to the .ppn file; built-in keyword is ignored.

A free access key is available at https://console.picovoice.ai/

Key design decision: the PyAudio input stream is opened and closed
around each detection cycle. This frees the audio device so the
Recorder can open a fresh stream to capture the user's utterance,
then the engine reopens its stream to resume idle listening.
This avoids device-conflict issues on Windows where simultaneous
input streams on the same device may fail.

Optional confirmation gate (WAKE_CONFIRM_GATE=true):
After Porcupine triggers, captures ~WAKE_CONFIRM_DURATION seconds of
audio and computes RMS energy. If energy < WAKE_CONFIRM_RMS_THRESHOLD,
the wake is rejected and listening resumes. Gate is default OFF.
"""
import math
import struct
import pathlib
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
        self.confirm_gate = config.wake_confirm_gate
        self.confirm_duration = config.wake_confirm_duration
        self.confirm_rms_threshold = config.wake_confirm_rms_threshold
        self.is_running = False

        # Resolve optional custom .ppn path (relative paths are resolved from
        # the repo root — 3 levels up from this file's location).
        self.keyword_path: str = ""
        if config.wake_keyword_path:
            p = pathlib.Path(config.wake_keyword_path)
            if not p.is_absolute():
                p = pathlib.Path(__file__).resolve().parent.parent.parent / p
            if not p.exists():
                raise FileNotFoundError(
                    f"Wake word model not found: {p}\n"
                    f"  Place the .ppn at that path, or set WAKE_KEYWORD_PATH\n"
                    f"  to the correct location, or leave it empty to use the\n"
                    f"  built-in keyword '{self.keyword}'."
                )
            self.keyword_path = str(p)
            logger.info(f"Custom wake model: {self.keyword_path}")

    # ------------------------------------------------------------------
    # Label used in log messages
    # ------------------------------------------------------------------

    @property
    def _label(self) -> str:
        return "harvest" if self.keyword_path else self.keyword

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

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
        logger.info(
            f"Listening for wake word: '{self._label.upper()}' "
            f"(sensitivity={self.sensitivity})"
        )
        self.is_running = True

        while self.is_running:
            detected = self._listen_until_wake()
            if detected and self.is_running:
                logger.info(
                    f"Wake triggered — keyword={self._label!r}, "
                    f"sensitivity={self.sensitivity}"
                )
                self.on_wake()  # blocks while pipeline runs; audio device is free

    def stop(self) -> None:
        """Signal the listening loop to exit."""
        self.is_running = False

    # ------------------------------------------------------------------
    # Internal detection loop
    # ------------------------------------------------------------------

    def _listen_until_wake(self) -> bool:
        """
        Open stream, read frames until wake word or stop signal.
        Always closes all resources before returning.

        Returns:
            True if wake word was detected (and confirmed if gate is on).
            False if stop() was called.
        """
        # Use custom .ppn if provided, otherwise fall back to built-in keyword.
        if self.keyword_path:
            porcupine = pvporcupine.create(
                access_key=self.access_key,
                keyword_paths=[self.keyword_path],
                sensitivities=[self.sensitivity],
            )
        else:
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
                    # Porcupine fired — run optional confirmation gate before committing.
                    if self.confirm_gate:
                        confirmed = self._confirm_wake(
                            stream, porcupine.frame_length, porcupine.sample_rate
                        )
                        if not confirmed:
                            logger.info(
                                "  Confirmation gate: rejected (RMS below threshold "
                                f"{self.confirm_rms_threshold})"
                            )
                            continue  # drop this wake, keep listening
                        logger.info(
                            f"  Confirmation gate: confirmed (threshold={self.confirm_rms_threshold})"
                        )
                    detected = True
                    break
        finally:
            stream.close()
            pa.terminate()
            porcupine.delete()

        return detected

    # ------------------------------------------------------------------
    # Confirmation gate — RMS energy check
    # ------------------------------------------------------------------

    def _confirm_wake(
        self, stream: pyaudio.Stream, frame_length: int, sample_rate: int
    ) -> bool:
        """
        Capture ~confirm_duration seconds of audio and compute RMS energy.

        Returns True if the RMS exceeds confirm_rms_threshold (indicating
        real speech), False if the audio is predominantly silence/noise.

        This is intentionally simple (no STT) to avoid adding latency or
        dependencies. The threshold is configurable via WAKE_CONFIRM_RMS_THRESHOLD
        since optimal values vary by microphone and environment.
        """
        frames_needed = int(self.confirm_duration * sample_rate / frame_length)
        samples: list[int] = []

        for _ in range(frames_needed):
            try:
                raw = stream.read(frame_length, exception_on_overflow=False)
                samples.extend(struct.unpack_from("h" * frame_length, raw))
            except OSError:
                break

        if not samples:
            return False

        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        logger.debug(f"  Gate RMS={rms:.1f} threshold={self.confirm_rms_threshold}")
        return rms >= self.confirm_rms_threshold
