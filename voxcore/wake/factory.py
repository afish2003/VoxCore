"""
Wake word engine factory.

Selects the engine implementation based on config.wake_engine.
To add a new engine: subclass WakeWordEngine, then add a case here
and set WAKE_ENGINE=your_engine in .env.
"""
from typing import Callable

from voxcore.config import Config
from voxcore.wake.base import WakeWordEngine
from voxcore.wake.porcupine import PorcupineEngine


def get_wake_engine(config: Config, on_wake: Callable[[], None]) -> WakeWordEngine:
    """
    Return the configured wake word engine.

    Supported engines (set WAKE_ENGINE in .env):
        porcupine  - Picovoice Porcupine (default)
    """
    engine = config.wake_engine.lower()

    if engine == "porcupine":
        return PorcupineEngine(config, on_wake)

    raise ValueError(
        f"Unknown WAKE_ENGINE: '{engine}'. "
        f"Supported options: 'porcupine'"
    )
