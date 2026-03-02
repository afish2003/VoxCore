"""
BaseTool interface.

Every tool the LLM can call must subclass BaseTool and declare three
class attributes:

    name         - identifier the LLM uses to request the tool
    description  - natural language description sent to the LLM
    parameters   - JSON Schema object describing the tool's arguments

The LLM receives these as an OpenAI-format tool spec via to_openai_spec().
The orchestrator calls execute(**arguments) when the LLM requests the tool.

To add a new tool:
    1. Create voxcore/tools/your_tool.py
    2. Subclass BaseTool and fill in name, description, parameters, execute()
    3. Register an instance in main.py with tool_registry.register(YourTool())
    No other files need to change.
"""
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """Base class for all VoxCore tools."""

    name: str           # tool identifier used by the LLM
    description: str    # shown to the LLM to decide when to use the tool
    parameters: dict    # JSON Schema for the tool's input arguments

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """
        Run the tool and return a plain-text result.

        The result is fed back to the LLM as a tool message so it can
        formulate a natural language response for the user.

        Args:
            **kwargs: Arguments matching the parameters schema.

        Returns:
            A plain-text string describing the result or an error.
        """
        ...

    def to_openai_spec(self) -> dict:
        """Return the OpenAI-format tool definition sent to the LLM."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
