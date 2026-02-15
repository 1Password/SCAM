"""Model implementations for SCAM benchmark."""

import os

from scam.models.base import BaseModel
from scam.models.anthropic import AnthropicModel
from scam.models.openai import OpenAIModel
from scam.models.gemini import GeminiModel
from scam.utils.config import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_VLLM_ANTHROPIC_BASE_URL,
    DEFAULT_VLLM_OPENAI_BASE_URL,
    parse_local_model_id,
    resolve_model_provider,
)

__all__ = [
    "BaseModel",
    "AnthropicModel",
    "OpenAIModel",
    "GeminiModel",
    "create_model",
]


def create_model(model_name: str) -> BaseModel:
    """Create a model instance based on the model name.

    Supports local LLMs via prefixes:
    - ollama/<model> — OpenAI-compatible Ollama (OLLAMA_BASE_URL, default localhost:11434)
    - vllm-openai/<model> — vLLM OpenAI-compatible (VLLM_OPENAI_BASE_URL, default localhost:8000)
    - vllm-anthropic/<model> — vLLM Anthropic-compatible (VLLM_ANTHROPIC_BASE_URL)
    """
    parsed = parse_local_model_id(model_name)
    if parsed:
        provider, model_id = parsed
        if provider == "ollama":
            base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
            return OpenAIModel(model_id, base_url=base_url, api_key="ollama")
        if provider == "vllm-openai":
            base_url = os.environ.get("VLLM_OPENAI_BASE_URL", DEFAULT_VLLM_OPENAI_BASE_URL)
            api_key = os.environ.get("OPENAI_API_KEY", "dummy")
            return OpenAIModel(model_id, base_url=base_url, api_key=api_key)
        if provider == "vllm-anthropic":
            base_url = os.environ.get(
                "VLLM_ANTHROPIC_BASE_URL", DEFAULT_VLLM_ANTHROPIC_BASE_URL
            )
            api_key = os.environ.get("ANTHROPIC_API_KEY", "dummy")
            return AnthropicModel(model_id, base_url=base_url, api_key=api_key)
        raise ValueError(f"Unknown local provider: {provider}")

    provider = resolve_model_provider(model_name)
    if provider == "anthropic":
        return AnthropicModel(model_name)
    elif provider == "openai":
        return OpenAIModel(model_name)
    elif provider == "google":
        return GeminiModel(model_name)
    else:
        raise ValueError(f"Unknown model provider for: {model_name}")
