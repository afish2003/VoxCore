"""
Abstract interface for LLM backends.

All LLM clients must subclass LLMClient and implement chat().

chat() receives the full conversation as a list of OpenAI-format messages
and an optional list of tool definitions. It returns an LLMResponse which
is either a final text answer or one or more tool calls to execute.

The orchestrator drives the multi-turn tool loop; the LLM client only
handles one request/response round at a time.

To add a new backend:
    1. Create voxcore/llm/your_backend.py
    2. Subclass LLMClient and implement chat()
    3. Register it in voxcore/llm/factory.py
    4. Set LLM_BACKEND=your_backend in .env
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ToolCall:
    """A single tool invocation requested by the LLM."""
    id: str            # unique call ID used to correlate the tool result message
    name: str          # tool name matching BaseTool.name
    arguments: dict    # parsed arguments matching the tool's parameters schema


@dataclass
class LLMResponse:
    """
    One response turn from the LLM.

    Exactly one of text or tool_calls will be populated:
        text       - final natural language answer (no tool calls)
        tool_calls - one or more tools the LLM wants executed
    """
    text: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(ABC):
    """Base class for LLM backends."""

    @abstractmethod
    def chat(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """
        Send a conversation turn to the LLM.

        Args:
            messages: Full conversation history in OpenAI message format.
                      The system prompt is included as the first message
                      (role "system"). Subsequent messages alternate between
                      "user", "assistant", and "tool" roles as the tool
                      loop progresses.
            tools:    Optional list of OpenAI-format tool specs from
                      ToolRegistry.specs(). Pass None to disable tool calling.

        Returns:
            LLMResponse with either text (final answer) or tool_calls.
        """
        ...
