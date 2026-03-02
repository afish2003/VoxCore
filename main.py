"""
VoxCore - Wake-Word-Driven Voice Assistant Core

Main loop:

    IDLE -> (wake word) -> LISTEN -> STT -> LLM -> TTS -> SPEAK -> IDLE

To run:
    python main.py

To swap any provider, edit .env only. No code changes needed.
"""
import logging

from voxcore.config import load_config
from voxcore.wake.factory import get_wake_engine
from voxcore.stt.factory import get_stt
from voxcore.llm.factory import get_llm
from voxcore.tts.factory import get_tts
from voxcore.audio.recorder import Recorder
from voxcore.orchestrator import Orchestrator


def main():
    config = load_config()

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("voxcore")

    logger.info("=" * 60)
    logger.info("VoxCore Starting")
    logger.info(f"  Wake engine : {config.wake_engine} ({config.wake_keyword.upper()})")
    logger.info(f"  STT         : {config.stt_provider} ({config.whisper_model})")
    logger.info(f"  LLM         : {config.llm_backend}")
    logger.info(f"  TTS         : {config.tts_provider}")
    logger.info("=" * 60)

    # Initialize providers
    stt      = get_stt(config)
    llm      = get_llm(config)
    tts      = get_tts(config)
    recorder = Recorder(config)

    # Wire providers into the pipeline orchestrator
    orchestrator = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        recorder=recorder,
        config=config,
    )

    # Wire the wake engine to the pipeline
    # on_wake is called once per detection; it blocks while the pipeline runs
    wake_engine = get_wake_engine(config, on_wake=orchestrator.run_pipeline)

    logger.info(f"Say '{config.wake_keyword.upper()}' to activate.  Ctrl+C to exit.")
    logger.info("[IDLE]")

    try:
        wake_engine.start()     # blocks; loops: idle -> detect -> pipeline -> idle
    except KeyboardInterrupt:
        logger.info("Interrupt received - shutting down...")
    finally:
        wake_engine.stop()
        logger.info("VoxCore stopped.")


if __name__ == "__main__":
    main()
