"""Configuration management for SCAM benchmark."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pydantic import BaseModel, Field

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
AGENTIC_SCENARIOS_DIR = SCENARIOS_DIR
SKILLS_DIR = PROJECT_ROOT / "skills"
RESULTS_DIR = PROJECT_ROOT / "results"
AGENTIC_RESULTS_DIR = RESULTS_DIR / "agentic"

# Supported models and their pricing (per 1M tokens: input, output).
# Standard tier pricing from provider pricing pages as of Feb 2026.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # ── Anthropic ────────────────────────────────────────────────
    # Claude 4.5 / 4.6 series
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5-20251101": (5.00, 25.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # Claude 4 series
    "claude-opus-4-1-20250805": (15.00, 75.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    # Claude 3.x legacy
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    # ── OpenAI ───────────────────────────────────────────────────
    # GPT-5 series
    "gpt-5.2": (1.75, 14.00),
    "gpt-5.2-pro": (21.00, 168.00),
    "gpt-5.1": (1.25, 10.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-pro": (15.00, 120.00),
    # GPT-4.1 series
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    # GPT-4o series
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "chatgpt-4o-latest": (5.00, 15.00),
    # o-series reasoning models
    "o4-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
    "o3-pro": (20.00, 80.00),
    "o3-mini": (1.10, 4.40),
    "o1": (15.00, 60.00),
    "o1-pro": (150.00, 600.00),
    "o1-mini": (1.10, 4.40),
    # Legacy
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4-turbo-preview": (10.00, 30.00),
    "gpt-4-0125-preview": (10.00, 30.00),
    "gpt-4-1106-preview": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-4-0613": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "gpt-3.5-turbo-0125": (0.50, 1.50),
    "gpt-3.5-turbo-1106": (1.00, 2.00),
    "gpt-3.5-turbo-16k": (3.00, 4.00),
    # ── Google (Gemini) ──────────────────────────────────────────
    # Gemini 3 series (preview)
    "gemini-3-pro-preview": (2.00, 12.00),
    "gemini-3-flash-preview": (0.50, 3.00),
    # Gemini 2.5 series
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.15, 0.60),
    # Gemini 2.0 series
    "gemini-2.0-flash": (0.10, 0.40),
    # Gemini 1.5 legacy
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
}

# ---------------------------------------------------------------------------
# Curated benchmark model list — the models that belong in a blog post.
# Organized by provider → list of (model_id, tier_label).
# Users can always bypass this with --model <exact-name>.
# ---------------------------------------------------------------------------

BENCHMARK_MODELS: dict[str, list[tuple[str, str]]] = {
    "Anthropic": [
        ("claude-opus-4-6", "Frontier"),
        ("claude-sonnet-4-20250514", "Mid-tier"),
        ("claude-haiku-4-5-20251001", "Fast"),
    ],
    "OpenAI": [
        ("gpt-5.2", "Frontier"),
        ("gpt-4.1", "Mid-tier"),
        ("gpt-4.1-mini", "Fast"),
    ],
    "Google (Gemini)": [
        ("gemini-3-pro-preview", "Frontier"),
        ("gemini-3-flash-preview", "Mid-tier"),
        ("gemini-2.5-flash", "Fast"),
    ],
    # Ollama: list populated dynamically from local Ollama API in discovery
    "Ollama": [],
}

# Flat set for quick lookups
BENCHMARK_MODEL_IDS: set[str] = {
    model_id
    for models in BENCHMARK_MODELS.values()
    for model_id, _ in models
}

# Local LLM prefixes: "ollama/", "vllm-openai/", "vllm-anthropic/"
LOCAL_PROVIDER_PREFIXES: tuple[str, ...] = ("ollama/", "vllm-openai/", "vllm-anthropic/")

# Default base URLs for local endpoints (override via env)
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_VLLM_OPENAI_BASE_URL = "http://localhost:8000/v1"
DEFAULT_VLLM_ANTHROPIC_BASE_URL = "http://localhost:8000"

# Provider → env var mapping for quick key checks (None = no key required, e.g. Ollama)
_PROVIDER_API_KEYS: dict[str, str | None] = {
    "Anthropic": "ANTHROPIC_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
    "Google (Gemini)": "GOOGLE_API_KEY",
    "Ollama": None,
}

# Derive provider model sets from the pricing table so there's a single
# source of truth.
ANTHROPIC_MODELS: set[str] = {
    m for m in MODEL_PRICING if m.startswith("claude-")
}
GOOGLE_MODELS: set[str] = {
    m for m in MODEL_PRICING if m.startswith("gemini-")
}
OPENAI_MODELS: set[str] = {
    m for m in MODEL_PRICING
    if m not in ANTHROPIC_MODELS and m not in GOOGLE_MODELS
}

class RunConfig(BaseModel):
    """Configuration for a benchmark run."""

    models: list[str]
    skill_path: Path | None = None
    categories: list[str] | None = None
    difficulties: list[int] | None = None
    output_path: Path | None = None
    concurrency: int = Field(default=5, ge=1, le=50)
    delay: float = Field(default=0.1, ge=0.0)
    yes: bool = False


def get_api_key(provider: str) -> str:
    """Get API key from environment."""
    env_var = f"{provider.upper()}_API_KEY"
    key = os.environ.get(env_var, "")
    if not key:
        raise ValueError(
            f"Missing API key: set {env_var} environment variable"
        )
    return key


def parse_local_model_id(model_name: str) -> tuple[str, str] | None:
    """If model_name is a local provider id (e.g. ollama/llama3.2), return (provider, model_id).

    Returns None if not a local provider format.
    """
    for prefix in LOCAL_PROVIDER_PREFIXES:
        if model_name.startswith(prefix):
            return prefix.rstrip("/"), model_name[len(prefix) :].strip() or model_name
    return None


def resolve_model_provider(model_name: str) -> str:
    """Determine which provider a model belongs to.

    Checks local prefixes first (ollama/, vllm-openai/, vllm-anthropic/), then
    the hardcoded sets, then prefix-based detection for cloud providers.
    """
    # Local LLM prefixes take precedence
    parsed = parse_local_model_id(model_name)
    if parsed:
        return parsed[0]

    if model_name in ANTHROPIC_MODELS:
        return "anthropic"
    if model_name in GOOGLE_MODELS:
        return "google"
    if model_name in OPENAI_MODELS:
        return "openai"

    # Prefix-based fallback for models not in hardcoded sets
    if model_name.startswith("claude-"):
        return "anthropic"
    if model_name.startswith("gemini-"):
        return "google"
    if any(
        model_name.startswith(p)
        for p in ("gpt-", "o1", "o3", "o4", "chatgpt-")
    ):
        return "openai"

    raise ValueError(f"Unknown model provider for: {model_name}")


def skill_hash(content: str) -> str:
    """Generate a hash for a skill file's content for caching."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def agentic_scenario_hash(yaml_path: Path) -> str:
    """SHA-256 hash (first 16 hex chars) of an agentic scenario YAML file.

    Hashes the raw file bytes so that *any* change — content, whitespace,
    comments — produces a different hash.
    """
    content = yaml_path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:16]


# ── Cost helpers ──────────────────────────────────────────────────────

# Multi-turn agentic scenarios may involve 5-20+ API round trips.
AVG_AGENTIC_INPUT_TOKENS_PER_SCENARIO = 4000
AVG_AGENTIC_OUTPUT_TOKENS_PER_SCENARIO = 2000


def estimate_agentic_cost(
    model_name: str,
    num_scenarios: int,
    num_runs: int = 1,
) -> float | None:
    """Estimate the cost of running agentic scenarios against a model.

    Uses higher per-scenario token averages (multi-turn conversations).
    Returns None for local models (no cost).
    """
    pricing = MODEL_PRICING.get(model_name)
    if pricing is None:
        return None
    input_price, output_price = pricing
    total_scenarios = num_scenarios * num_runs
    input_cost = (AVG_AGENTIC_INPUT_TOKENS_PER_SCENARIO * total_scenarios / 1_000_000) * input_price
    output_cost = (AVG_AGENTIC_OUTPUT_TOKENS_PER_SCENARIO * total_scenarios / 1_000_000) * output_price
    return input_cost + output_cost


def calculate_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Calculate actual cost from token counts.

    Returns None for models not in the pricing table.
    """
    pricing = MODEL_PRICING.get(model_name)
    if pricing is None:
        return None
    input_price, output_price = pricing
    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
