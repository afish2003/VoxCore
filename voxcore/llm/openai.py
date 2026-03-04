"""
OpenAI LLM client.

Uses the official OpenAI Python SDK to talk to the OpenAI Chat Completions API.
Fully supports the tool-calling loop expected by the orchestrator.

This provider is a drop-in replacement for OllamaClient and VLLMClient.
From the orchestrator's perspective it behaves identically: given a message
list and optional tool specs it returns an LLMResponse with either text or
tool calls.

Use this backend to bypass local-model tool-calling compatibility issues
during development:
    LLM_BACKEND=openai

Configuration (.env):
    OPENAI_API_KEY   - required, your OpenAI API key
    OPENAI_MODEL     - optional, defaults to gpt-4o-mini
    OPENAI_TIMEOUT   - optional, seconds, defaults to 30

The OpenAI API natively speaks the same OpenAI message format the orchestrator
already uses, so no message translation is needed here beyond normalising the
tool call objects into VoxCore's ToolCall dataclass.
"""
import json
import logging
from typing import List, Optional

from openai import OpenAI

from voxcore.config import Config
from voxcore.llm.base import LLMClient, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class OpenAIClient(LLMClient):
    """LLM client for the OpenAI Chat Completions API."""

    def __init__(self, config: Config):
        self.client = OpenAI(
            api_key=config.openai_api_key,
            timeout=config.openai_timeout,
        )
        self.model = config.openai_model
        self.temperature = config.llm_temperature
        self.top_p = config.llm_top_p
        self.max_tokens = config.llm_max_tokens
        logger.info(f"OpenAI client ready: {self.model}")

    def chat(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message

        raw_tool_calls = message.tool_calls or []
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                # OpenAI always provides an id and returns arguments as a JSON string.
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json.loads(args)
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))
            return LLMResponse(tool_calls=tool_calls)

        return LLMResponse(text=(message.content or "").strip())
