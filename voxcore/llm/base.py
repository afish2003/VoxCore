"""
Abstract interface for LLM backends.

All LLM clients must subclass LLMClient and implement generate().
The system prompt is passed on every call so the orchestrator
can change persona without touching provider code.

To add a new backend:
    1. Create voxcore/llm/your_backend.py
    2. Subclass LLMClient and implement generate()
    3. Register it in voxcore/llm/factory.py
    4. Set LLM_BACKEND=your_backend in .env
"""
from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Base class for LLM backends."""

    @abstractmethod
    def generate(self, user_text: str, system_prompt: str) -> str:
        """
        Generate a response.

        Args:
            user_text:     Transcribed user speech.
            system_prompt: Assistant persona / instructions.

        Returns:
            Response text string.
        """
        ...
