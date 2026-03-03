"""
Ollama LLM client.

Talks to a locally running Ollama server (http://localhost:11434).
Supports tool calling via Ollama's OpenAI-compatible tools field.
Good for development and CPU-only machines.

Note: Ollama returns tool call arguments as a dict (not a JSON string)
and does not always include a tool call ID; both are handled here.
"""
import json
import logging
from typing import List, Optional

import requests

from voxcore.config import Config
from voxcore.llm.base import LLMClient, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class OllamaClient(LLMClient):
    """LLM client for a locally running Ollama server."""

    def __init__(self, config: Config):
        self.url = config.ollama_url
        self.model = config.ollama_model
        self.timeout = config.ollama_timeout
        self.temperature = config.llm_temperature
        self.top_p = config.llm_top_p
        self.max_tokens = config.llm_max_tokens
        logger.info(f"Ollama client ready: {self.model} @ {self.url}")

    def chat(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "num_predict": self.max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        response = requests.post(self.url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        message = response.json()["message"]

        raw_tool_calls = message.get("tool_calls") or []
        if raw_tool_calls:
            tool_calls = []
            for i, tc in enumerate(raw_tool_calls):
                fn = tc["function"]
                # Ollama returns arguments as a dict; normalise in case it's a string.
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)
                tool_calls.append(ToolCall(
                    id=tc.get("id") or f"call_{i}",
                    name=fn["name"],
                    arguments=args,
                ))
            return LLMResponse(tool_calls=tool_calls)

        return LLMResponse(text=(message.get("content") or "").strip())
