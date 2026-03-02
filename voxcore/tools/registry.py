"""
ToolRegistry - holds all registered tools and handles execution.

The orchestrator calls:
    registry.specs()              -> list of OpenAI tool specs for the LLM
    registry.execute(name, args)  -> run a tool and return its string result

Tools are registered in main.py. The registry, orchestrator, and LLM
clients never need to know about specific tool implementations.
"""
import logging
from typing import List

from voxcore.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Container for all active tools.

    Supports a fluent registration API:
        registry = ToolRegistry()
            .register(GetCurrentDatetime())
            .register(WebSearch())
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> "ToolRegistry":
        """Register a tool. Returns self for chaining."""
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: '{tool.name}'")
        return self

    def specs(self) -> List[dict]:
        """Return OpenAI-format tool definitions for all registered tools."""
        return [t.to_openai_spec() for t in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> str:
        """
        Execute a tool by name with the given arguments.

        Returns a plain-text result string in all cases, including errors,
        so the LLM always gets a coherent tool message to work with.
        """
        tool = self._tools.get(name)
        if not tool:
            logger.warning(f"Tool call for unknown tool: '{name}'")
            return f"Error: tool '{name}' is not available."
        try:
            return tool.execute(**arguments)
        except TypeError as e:
            logger.error(f"Tool '{name}' called with bad arguments {arguments}: {e}")
            return f"Error: bad arguments for '{name}': {e}"
        except Exception as e:
            logger.error(f"Tool '{name}' raised an exception: {e}", exc_info=True)
            return f"Error running '{name}': {e}"

    def __len__(self) -> int:
        return len(self._tools)

    def __bool__(self) -> bool:
        return bool(self._tools)
