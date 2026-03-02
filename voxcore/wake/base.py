"""
Abstract interface for wake word engines.

All wake word backends must subclass WakeWordEngine and implement
start() and stop(). The engine calls on_wake() each time the wake
word is detected, then resumes idle listening after on_wake() returns.
"""
from abc import ABC, abstractmethod
from typing import Callable


class WakeWordEngine(ABC):
    """
    Base class for wake word engines.

    Contract:
        - start() blocks; it loops forever listening for the wake word.
        - When the wake word is detected, start() calls self.on_wake().
        - on_wake() blocks while the pipeline runs.
        - After on_wake() returns, start() resumes listening.
        - stop() signals start() to exit after the current iteration.

    To add a new engine:
        1. Create voxcore/wake/your_engine.py
        2. Subclass WakeWordEngine and implement start() / stop()
        3. Register it in voxcore/wake/factory.py
        4. Set WAKE_ENGINE=your_engine in .env
    """

    def __init__(self, on_wake: Callable[[], None]):
        self.on_wake = on_wake

    @abstractmethod
    def start(self) -> None:
        """Start listening. Blocks until stop() is called."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Signal the engine to exit after the current loop iteration."""
        ...
