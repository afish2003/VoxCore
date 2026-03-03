"""
vLLM LLM client.

Uses the OpenAI-compatible /v1/chat/completions endpoint exposed by vLLM.
Supports tool calling via the standard OpenAI tools/tool_choice fields.
Best for GPU inference on Lambda Labs or a dedicated inference server.
"""
import json
import logging
from typing import List, Optional

import requests

from voxcore.config import Config
from voxcore.llm.base import LLMClient, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class VLLMClient(LLMClient):
    """LLM client for a running vLLM inference server."""

    def __init__(self, config: Config):
        self.url = config.vllm_url
        self.model = config.vllm_model
        self.timeout = config.vllm_timeout
        self.temperature = config.llm_temperature
        self.top_p = config.llm_top_p
        self.max_tokens = config.llm_max_tokens
        logger.info(f"vLLM client ready: {self.model} @ {self.url}")

    def chat(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response = requests.post(self.url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]

        raw_tool_calls = message.get("tool_calls") or []
        if raw_tool_calls:
            tool_calls = []
            for i, tc in enumerate(raw_tool_calls):
                fn = tc["function"]
                # vLLM returns arguments as a JSON string; parse it.
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    args = json.loads(args)
                tool_calls.append(ToolCall(
                    id=tc.get("id") or f"call_{i}",
                    name=fn["name"],
                    arguments=args,
                ))
            return LLMResponse(tool_calls=tool_calls)

        return LLMResponse(text=(message.get("content") or "").strip())
