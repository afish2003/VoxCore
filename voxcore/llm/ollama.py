"""
Ollama LLM client.

Talks to a locally running Ollama server (http://localhost:11434).
Good for development and CPU-only machines.
Configure the model in .env (OLLAMA_MODEL).
"""
import logging
import requests

from voxcore.config import Config
from voxcore.llm.base import LLMClient

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

    def generate(self, user_text: str, system_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "num_predict": self.max_tokens,
            },
        }
        response = requests.post(self.url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
