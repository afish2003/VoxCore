"""
Audio recorder with Voice Activity Detection (VAD) and WAV playback.

record_utterance() opens the microphone, captures audio until the user
stops speaking, then closes the device and returns raw PCM bytes.

play_wav() opens the default output device, plays WAV bytes to completion,
then closes the device.

Both methods open and close their own PyAudio instances so they never
conflict with the Porcupine wake word stream. The wake engine releases
the mic before calling the pipeline; the recorder grabs it only then.
"""
import io
import wave
import struct
import logging

import pyaudio

from voxcore.config import Config

logger = logging.getLogger(__name__)


class Recorder:
    """
    Captures a single utterance and plays back audio responses.

    Uses energy-based VAD: recording stops after a configurable period
    of silence, or after record_max_duration seconds, whichever comes first.
    """

    def __init__(self, config: Config):
        self.sample_rate = config.sample_rate
        self.channels = config.channels
        self.chunk_size = config.chunk_size
        self.vad_threshold = config.vad_energy_threshold
        self.silence_duration = config.vad_silence_duration
        self.max_duration = config.record_max_duration

    def record_utterance(self) -> bytes:
        """
        Open the microphone, record until silence, return raw PCM bytes.

        The PyAudio instance is created and terminated within this call
        so the device is available to other users (e.g. Porcupine) after.
        """
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )

        frames = []
        silence_chunks = 0
        max_silence = int(self.silence_duration * self.sample_rate / self.chunk_size)
        max_chunks = int(self.max_duration * self.sample_rate / self.chunk_size)

        try:
            for _ in range(max_chunks):
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                frames.append(data)

                if self._is_speech(data):
                    silence_chunks = 0
                else:
                    silence_chunks += 1
                    # Stop after sustained silence, but only once we have some audio
                    if silence_chunks > max_silence and len(frames) > 10:
                        break
        finally:
            stream.close()
            pa.terminate()

        return b"".join(frames)

    def play_wav(self, wav_bytes: bytes) -> None:
        """
        Play WAV audio bytes through the default output device.
        Blocks until playback is complete.
        """
        pa = pyaudio.PyAudio()
        try:
            with wave.open(io.BytesIO(wav_bytes)) as wf:
                stream = pa.open(
                    format=pa.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                )
                data = wf.readframes(self.chunk_size)
                while data:
                    stream.write(data)
                    data = wf.readframes(self.chunk_size)
                stream.close()
        finally:
            pa.terminate()

    def _is_speech(self, audio_chunk: bytes) -> bool:
        """Return True if the chunk's energy exceeds the VAD threshold."""
        shorts = struct.unpack(f"{len(audio_chunk) // 2}h", audio_chunk)
        energy = sum(abs(s) for s in shorts) / len(shorts)
        return energy > self.vad_threshold
