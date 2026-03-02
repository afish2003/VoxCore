"""
VoxCore Pipeline Orchestrator

Runs one full interaction cycle per wake-word detection:

    LISTEN -> STT -> LLM -> TTS -> SPEAK

This class is provider-agnostic. It receives concrete implementations
of STT, LLM, and TTS at construction time via dependency injection.
Swapping any provider does not require touching this file.
"""
import logging

from voxcore.config import Config
from voxcore.stt.base import STTProvider
from voxcore.llm.base import LLMClient
from voxcore.tts.base import TTSProvider
from voxcore.audio.recorder import Recorder

logger = logging.getLogger(__name__)

# Skip transcriptions shorter than this (noise, mic pops, empty audio)
_MIN_TRANSCRIPT_LEN = 3


class Orchestrator:
    """
    Stateless pipeline runner.

    Each call to run_pipeline() executes one complete listen-and-respond
    cycle. The method is called directly by the wake word engine callback
    and blocks while the cycle runs.
    """

    def __init__(
        self,
        stt: STTProvider,
        llm: LLMClient,
        tts: TTSProvider,
        recorder: Recorder,
        config: Config,
    ):
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.recorder = recorder
        self.system_prompt = config.llm_system_prompt

    def run_pipeline(self) -> None:
        """
        Execute one full listen -> process -> speak cycle.

        Called once per wake word detection. Errors are caught and
        logged so the wake engine can resume idle listening cleanly.
        """
        try:
            self._run()
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)

    def _run(self) -> None:
        # 1. Listen
        logger.info("[LISTENING]")
        audio_bytes = self.recorder.record_utterance()

        # 2. Transcribe
        logger.info("[STT]")
        user_text = self.stt.transcribe(audio_bytes)
        logger.info(f"  heard: {user_text!r}")

        if not user_text or len(user_text.strip()) < _MIN_TRANSCRIPT_LEN:
            logger.info("  (nothing detected - returning to idle)")
            return

        # 3. Generate
        logger.info("[LLM]")
        response_text = self.llm.generate(user_text, self.system_prompt)
        logger.info(f"  response: {response_text!r}")

        # 4. Synthesize
        logger.info("[TTS]")
        audio_out = self.tts.synthesize(response_text)

        # 5. Speak
        logger.info("[SPEAKING]")
        self.recorder.play_wav(audio_out)

        logger.info("[IDLE]")
