"""Model implementations for SCAM benchmark."""

from scam.models.base import BaseModel
from scam.models.anthropic import AnthropicModel
from scam.models.openai import OpenAIModel
from scam.models.gemini import GeminiModel
from scam.utils.config import resolve_model_provider

__all__ = [
    "BaseModel",
    "AnthropicModel",
    "OpenAIModel",
    "GeminiModel",
    "create_model",
]


def create_model(model_name: str) -> BaseModel:
    """Create a model instance based on the model name."""
    provider = resolve_model_provider(model_name)
    if provider == "anthropic":
        return AnthropicModel(model_name)
    elif provider == "openai":
        return OpenAIModel(model_name)
    elif provider == "google":
        return GeminiModel(model_name)
    else:
        raise ValueError(f"Unknown model provider for: {model_name}")
