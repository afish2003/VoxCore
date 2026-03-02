"""
LLM backend factory.

Selects the LLM client based on config.llm_backend.
To add a new backend: subclass LLMClient, then add a case here
and set LLM_BACKEND=your_backend in .env.
"""
import logging

from voxcore.config import Config
from voxcore.llm.base import LLMClient
from voxcore.llm.vllm import VLLMClient
from voxcore.llm.ollama import OllamaClient

logger = logging.getLogger(__name__)


def get_llm(config: Config) -> LLMClient:
    """
    Return the configured LLM client.

    Supported backends (set LLM_BACKEND in .env):
        ollama  - Local Ollama server, CPU-friendly (default)
        vllm    - GPU inference via vLLM OpenAI-compatible API
    """
    backend = config.llm_backend.lower()

    if backend == "ollama":
        return OllamaClient(config)
    if backend == "vllm":
        return VLLMClient(config)

    raise ValueError(
        f"Unknown LLM_BACKEND: '{backend}'. "
        f"Supported options: 'ollama', 'vllm'"
    )
