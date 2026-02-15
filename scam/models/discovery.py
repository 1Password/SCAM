"""Dynamic model discovery from provider APIs.

Queries Anthropic, OpenAI, Google (Gemini), and Ollama for available
models so the CLI can offer an interactive picker instead of requiring
exact model names.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from rich.console import Console

# Provider names that trigger interactive discovery
PROVIDER_NAMES = {"anthropic", "openai", "google", "gemini", "ollama"}

# Regex to strip date suffixes like -2024-11-20 from OpenAI model IDs
_DATE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")

# OpenAI model prefixes that are chat-capable (relevant for benchmarking)
_OPENAI_CHAT_PREFIXES = (
    "gpt-5", "gpt-4.1", "gpt-4o", "gpt-4-turbo", "gpt-4-", "gpt-4", "gpt-3.5",
    "o1", "o3", "o4",
    "chatgpt-4o",
)

# Substrings in OpenAI model IDs to exclude
_OPENAI_EXCLUDE = (
    ":ft-", "instruct", "realtime", "audio", "search",
    "embedding", "tts", "whisper", "dall-e", "davinci",
    "babbage", "moderation", "transcribe", "image",
    "vision", "computer-use", "codex", "-chat-latest",
    "sora", "-oss-", "diarize",
)


@dataclass
class DiscoveredModel:
    """A model discovered from a provider API."""

    id: str
    provider: str
    display_name: str = ""
    created_at: str = ""


def is_interactive_model_arg(value: str | None) -> tuple[bool, list[str] | None]:
    """Check if the ``--model`` value should trigger interactive selection.

    Returns ``(is_interactive, provider_filter)``:
    - ``(True, None)`` → interactive mode, enumerate all providers
    - ``(True, ["anthropic"])`` → interactive mode, specific provider(s)
    - ``(False, None)`` → direct mode, treat value as model name(s)
    """
    if value is None:
        return True, None

    parts = [p.strip().lower() for p in value.split(",")]
    if all(p in PROVIDER_NAMES for p in parts):
        return True, parts

    return False, None


# ---------------------------------------------------------------------------
# Provider-specific discovery
# ---------------------------------------------------------------------------


def list_anthropic_models() -> list[DiscoveredModel]:
    """Query the Anthropic API for available models."""
    try:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return []
        client = anthropic.Anthropic(api_key=api_key)
        page = client.models.list(limit=100)

        models: list[DiscoveredModel] = []
        for m in page.data:
            models.append(
                DiscoveredModel(
                    id=m.id,
                    provider="anthropic",
                    display_name=getattr(m, "display_name", m.id),
                    created_at=str(getattr(m, "created_at", "")),
                )
            )

        # Newest first (API default, but be explicit)
        models.sort(key=lambda x: x.created_at, reverse=True)
        return models

    except Exception:
        return []


def list_openai_models() -> list[DiscoveredModel]:
    """Query the OpenAI API for available chat models.

    Filters out non-chat models (embeddings, audio, images, etc.) and
    de-duplicates date-versioned snapshots when a canonical alias exists.
    """
    try:
        import openai

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return []
        client = openai.OpenAI(api_key=api_key)
        response = client.models.list()

        raw: list[DiscoveredModel] = []
        for m in response.data:
            mid = m.id

            # Must start with a known chat prefix
            if not any(mid.startswith(p) for p in _OPENAI_CHAT_PREFIXES):
                continue

            # Exclude non-chat variants
            if any(ex in mid.lower() for ex in _OPENAI_EXCLUDE):
                continue

            raw.append(
                DiscoveredModel(
                    id=mid,
                    provider="openai",
                    display_name=mid,
                    created_at=str(getattr(m, "created", "")),
                )
            )

        # De-duplicate: prefer canonical names (no date suffix) over snapshots.
        # If a canonical alias exists (e.g. gpt-4o), drop gpt-4o-2024-11-20.
        canonical_ids: set[str] = set()
        dated: dict[str, DiscoveredModel] = {}  # base → latest dated model

        for dm in raw:
            base = _DATE_SUFFIX.sub("", dm.id)
            if dm.id == base:
                canonical_ids.add(base)
            else:
                if base not in dated or dm.created_at > dated[base].created_at:
                    dated[base] = dm

        models: list[DiscoveredModel] = []
        for dm in raw:
            base = _DATE_SUFFIX.sub("", dm.id)
            if dm.id == base:
                # Canonical alias — always include
                models.append(dm)
            elif base not in canonical_ids:
                # No canonical alias — include the latest dated snapshot only
                if dated.get(base) is dm:
                    models.append(dm)

        models.sort(key=lambda x: x.created_at, reverse=True)
        return models

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Google (Gemini) chat-capable model prefixes
# ---------------------------------------------------------------------------

_GEMINI_CHAT_PREFIXES = (
    "gemini-3",
    "gemini-2.5",
    "gemini-2.0",
    "gemini-1.5",
)

# Substrings in Gemini model IDs to exclude
_GEMINI_EXCLUDE = (
    "embedding",
    "aqa",
    "vision",
    "imagen",
    "code",
    "tuning",
    "learnlm",
)


def list_google_models() -> list[DiscoveredModel]:
    """Query the Google Gemini API for available chat models.

    Uses the ``google-genai`` SDK to list models and filters for
    chat-capable Gemini models.
    """
    try:
        from google import genai

        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            return []
        client = genai.Client(api_key=api_key)

        models: list[DiscoveredModel] = []
        for m in client.models.list():
            # Model names come as "models/gemini-2.5-flash" — strip prefix
            mid: str = m.name or ""
            if mid.startswith("models/"):
                mid = mid[len("models/"):]

            # Must start with a known chat prefix
            if not any(mid.startswith(p) for p in _GEMINI_CHAT_PREFIXES):
                continue

            # Exclude non-chat variants
            if any(ex in mid.lower() for ex in _GEMINI_EXCLUDE):
                continue

            display = getattr(m, "display_name", mid) or mid
            models.append(
                DiscoveredModel(
                    id=mid,
                    provider="google",
                    display_name=display,
                )
            )

        # Sort by ID descending so newest (higher version) comes first
        models.sort(key=lambda x: x.id, reverse=True)
        return models

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Ollama (local) — OpenAI-compatible API
# ---------------------------------------------------------------------------

def list_ollama_models() -> list[DiscoveredModel]:
    """List models available from a local Ollama instance.

    GETs Ollama's /api/tags (default base http://localhost:11434).
    Returns model IDs in the form "ollama/<name>" for use with create_model.
    """
    try:
        import urllib.request

        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        # Ollama tags endpoint is at /api/tags, not under /v1
        if base.endswith("/v1"):
            base = base[: -3]
        url = f"{base}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
        models_list = data.get("models") or []
        result: list[DiscoveredModel] = []
        for m in models_list:
            name = m.get("name") or ""
            if not name:
                continue
            # Ollama may return "name:tag"; we use the full name for the API
            result.append(
                DiscoveredModel(
                    id=f"ollama/{name}",
                    provider="ollama",
                    display_name=name,
                )
            )
        result.sort(key=lambda x: x.display_name or x.id)
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Unified discovery
# ---------------------------------------------------------------------------


def discover_models(
    providers: list[str] | None = None,
    console: Console | None = None,
) -> dict[str, list[DiscoveredModel]]:
    """Discover available models from specified providers (or all with valid keys).

    Returns a dict keyed by display provider name → list of models.
    """
    targets = [p.lower() for p in providers] if providers else ["anthropic", "openai", "google"]
    # Normalise aliases so `--model gemini` works
    targets = ["google" if t == "gemini" else t for t in targets]
    result: dict[str, list[DiscoveredModel]] = {}

    if "anthropic" in targets:
        if os.environ.get("ANTHROPIC_API_KEY"):
            models = list_anthropic_models()
            if models:
                result["Anthropic"] = models
            elif console:
                console.print("  [dim]Anthropic: no models returned[/dim]")
        elif console:
            console.print("  [dim]Anthropic: ANTHROPIC_API_KEY not set — skipped[/dim]")

    if "openai" in targets:
        if os.environ.get("OPENAI_API_KEY"):
            models = list_openai_models()
            if models:
                result["OpenAI"] = models
            elif console:
                console.print("  [dim]OpenAI: no models returned[/dim]")
        elif console:
            console.print("  [dim]OpenAI: OPENAI_API_KEY not set — skipped[/dim]")

    if "google" in targets:
        if os.environ.get("GOOGLE_API_KEY"):
            models = list_google_models()
            if models:
                result["Google (Gemini)"] = models
            elif console:
                console.print("  [dim]Google: no models returned[/dim]")
        elif console:
            console.print("  [dim]Google: GOOGLE_API_KEY not set — skipped[/dim]")

    return result


# ---------------------------------------------------------------------------
# Interactive selection helper
# ---------------------------------------------------------------------------


def interactive_model_select(
    providers: list[str] | None = None,
    console: Console | None = None,
) -> list[str]:
    """Show curated benchmark models and let the user select interactively.

    Uses the curated :data:`BENCHMARK_MODELS` list rather than querying
    every provider API — faster and cleaner for typical benchmark runs.
    Only shows providers whose API key is set.

    Returns a list of model ID strings ready to pass to the runner.
    Raises ``SystemExit`` if no models are found or the user makes no selection.
    """
    from scam.utils.config import (
        BENCHMARK_MODELS,
        MODEL_PRICING,
        AVG_AGENTIC_INPUT_TOKENS_PER_SCENARIO,
        AVG_AGENTIC_OUTPUT_TOKENS_PER_SCENARIO,
        _PROVIDER_API_KEYS,
    )

    _console = console or Console()

    # Filter providers by API key availability
    provider_filter: set[str] | None = None
    if providers:
        # Map CLI provider names → display names used in BENCHMARK_MODELS
        _alias = {
            "anthropic": "Anthropic",
            "openai": "OpenAI",
            "google": "Google (Gemini)",
            "gemini": "Google (Gemini)",
            "ollama": "Ollama",
        }
        provider_filter = {_alias.get(p.lower(), p) for p in providers}

    available: dict[str, list[tuple[str, str]]] = {}
    for provider_name, models in BENCHMARK_MODELS.items():
        if provider_filter and provider_name not in provider_filter:
            continue
        env_var = _PROVIDER_API_KEYS.get(provider_name)
        if env_var is not None and not os.environ.get(env_var):
            _console.print(f"  [dim]{provider_name}: {env_var} not set — skipped[/dim]")
            continue
        if provider_name == "Ollama":
            ollama_models = list_ollama_models()
            if ollama_models:
                available[provider_name] = [(m.id, "Local") for m in ollama_models]
            # If Ollama not running / no models, skip so we don't show empty section
        else:
            available[provider_name] = models

    if not available:
        _console.print(
            "\n[red]No models available.[/red] Make sure your API keys are set "
            "(ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY)."
        )
        raise SystemExit(1)

    # Build numbered list
    flat: list[tuple[str, str, str]] = []  # (model_id, tier, provider)
    _console.print("\n[bold]Benchmark Models[/bold]\n")
    idx = 1

    for provider_name, models in available.items():
        _console.print(f"  [bold cyan]{provider_name}[/bold cyan]")
        for model_id, tier in models:
            pricing = MODEL_PRICING.get(model_id)

            parts = [f"    [green]{idx:>3}[/green]  {model_id}"]
            parts.append(f"[dim]{tier:>9}[/dim]")
            if pricing:
                per_run = (
                    (AVG_AGENTIC_INPUT_TOKENS_PER_SCENARIO * 19 / 1_000_000) * pricing[0]
                    + (AVG_AGENTIC_OUTPUT_TOKENS_PER_SCENARIO * 19 / 1_000_000) * pricing[1]
                )
                parts.append(f"[yellow]~${per_run:.3f}/run[/yellow]")

            _console.print("  ".join(parts))
            flat.append((model_id, tier, provider_name))
            idx += 1

        _console.print()

    _console.print("[dim]Enter comma-separated numbers, ranges (1-3), or 'all'.[/dim]")
    _console.print("[dim]Tip: use --model <name> to run any model not listed here.[/dim]")
    raw = _console.input("[bold]Select models> [/bold]").strip()

    if not raw:
        _console.print("[red]No selection made.[/red]")
        raise SystemExit(1)

    if raw.lower() == "all":
        selected = [m for m, _, _ in flat]
    else:
        selected_indices: set[int] = set()
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part and not part.startswith("-"):
                try:
                    lo, hi = part.split("-", 1)
                    for i in range(int(lo), int(hi) + 1):
                        selected_indices.add(i)
                except ValueError:
                    _console.print(f"[yellow]Skipping invalid range: {part}[/yellow]")
            else:
                try:
                    selected_indices.add(int(part))
                except ValueError:
                    _console.print(f"[yellow]Skipping invalid input: {part}[/yellow]")

        selected = []
        for i in sorted(selected_indices):
            if 1 <= i <= len(flat):
                selected.append(flat[i - 1][0])

    if not selected:
        _console.print("[red]No valid models selected.[/red]")
        raise SystemExit(1)

    _console.print(f"\n[bold]Selected:[/bold] {', '.join(selected)}")

    # Suggest parallelization when multiple models are selected
    if len(selected) > 1:
        suggested_parallel = min(len(selected), 3)
        _console.print(
            f"[dim]Tip: add --parallel {suggested_parallel} to run "
            f"{suggested_parallel} models concurrently.[/dim]"
        )

    _console.print()
    return selected
