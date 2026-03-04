"""
VoxCore - Wake-Word-Driven Voice Assistant Core

Main loop:

    IDLE -> (wake word) -> LISTEN -> STT -> LLM (+tools) -> TTS -> SPEAK -> IDLE

The LLM can call tools. All tool decisions are made by the LLM at runtime.
There is no keyword routing or hardcoded command logic.

To run:
    python main.py

To swap any provider, edit .env only. No code changes needed.
To add a tool, create voxcore/tools/your_tool.py and register it below.
"""
import logging

from voxcore.config import load_config
from voxcore.wake.factory import get_wake_engine
from voxcore.stt.factory import get_stt
from voxcore.llm.factory import get_llm
from voxcore.tts.factory import get_tts
from voxcore.audio.recorder import Recorder
from voxcore.orchestrator import Orchestrator
from voxcore.tools.registry import ToolRegistry
from voxcore.tools.datetime_tool import GetCurrentDatetime
from voxcore.tools.open_app import OpenApplication
from voxcore.tools.web_search import WebSearch


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

    # --- Initialize providers ---
    stt      = get_stt(config)
    llm      = get_llm(config)
    tts      = get_tts(config)
    recorder = Recorder(config)

    # --- Register tools ---
    # The LLM decides which tools to call at runtime based on user intent.
    # To add a tool: import it, instantiate it, call .register().
    # No other files need to change.
    tool_registry = (
        ToolRegistry()
        .register(GetCurrentDatetime())
        .register(OpenApplication())
        .register(WebSearch(instances=config.searx_instances))
    )
    logger.info(f"  Tools       : {len(tool_registry)} registered")

    # --- Wire everything into the orchestrator ---
    orchestrator = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        recorder=recorder,
        config=config,
        tool_registry=tool_registry,
    )

    # --- Wire the wake engine to the pipeline ---
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
