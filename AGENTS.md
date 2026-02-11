# AGENTS.md — AI Coding Guidelines for SCAM

## Project Overview

SCAM (Security Comprehension Awareness Measure) is a CLI benchmark that evaluates the safety of AI agents with tool access. It runs multi-turn conversations where an AI agent uses tools (inbox, browser, forms, credential vault) and must proactively protect the user from threats without being told to look for them.

## Architecture

```
CLI (typer) → Agentic Runner → Model.chat() (tool-calling loop) → ToolRouter (simulated env)
                ↓                                                        ↓
         Checkpoint evaluator                                  Environment (emails, URLs, vault)
                ↓
         Reporting (rich + markdown)
                ↓
         Export (HTML, video, terminal replay)

```

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `scam/cli.py` | CLI commands: `run`, `evaluate`, `replay`, `export`, `compare`, `report`, `scenarios` |
| `scam/models/base.py` | `BaseModel` (abstract: `chat()` required), `ChatResponse`, `ToolCall` |
| `scam/models/__init__.py` | `create_model()` factory function, re-exports |
| `scam/models/anthropic.py` | Anthropic Claude adapter (Messages API + tool calling) |
| `scam/models/openai.py` | OpenAI adapter (Chat Completions API + tool calling) |
| `scam/models/gemini.py` | Google Gemini adapter (google-genai SDK + function calling) |
| `scam/models/discovery.py` | Dynamic model listing from provider APIs, interactive picker |
| `scam/agentic/scenario.py` | YAML parser, `AgenticScenario` dataclass, `STANDARD_TOOLS` |
| `scam/agentic/environment.py` | `ToolRouter` — simulates inbox, URLs, forms, vault; tracks dangerous calls |
| `scam/agentic/evaluator.py` | Checkpoint-based scoring for agentic scenarios (regex + optional LLM judge) |
| `scam/agentic/judge.py` | LLM-as-judge evaluator — semantic fallback when regex pattern matching misses |
| `scam/agentic/runner.py` | Multi-turn conversation orchestrator for agentic evaluation |
| `scam/agentic/reporting.py` | Terminal reports, comparison, markdown reports (agentic) |
| `scam/agentic/aggregate.py` | Multi-run statistical aggregation (mean, std, CI, stability) |
| `scam/agentic/replay.py` | Interactive terminal replay viewer with typing effects and scorecard |
| `scam/agentic/export_html.py` | Self-contained HTML export with animated replay, per-scenario and combined index pages |
| `scam/agentic/export_video.py` | MP4 video export using Pillow for frame rendering and FFmpeg for encoding. Includes title cards, animated message bubbles with markdown rendering, tool call visualization, and scorecard overlays |
| `scam/utils/config.py` | Paths, model pricing, API keys, `skill_hash()`, `agentic_scenario_hash()`, `estimate_agentic_cost()`, `calculate_cost()` |

## Directory Layout

```
scenarios/                      # Agentic scenario YAML files (main contribution surface)
├── inbox_phishing.yaml
├── social_engineering.yaml
├── credential_exposure.yaml
├── credential_autofill.yaml
├── ecommerce_scams.yaml
├── data_leakage.yaml
├── confused_deputy.yaml
├── multi_stage.yaml
├── prompt_injection.yaml
└── _template.yaml              # Starter template for contributors

skills/                         # System prompt skill files
├── baseline.md                 # Minimal prompt (control condition)
└── security_expert.md          # Security awareness guidance

results/
├── official/                   # Tracked official evaluation results
└── agentic/                    # Scratch evaluations (gitignored)

exports/                        # HTML and video exports (gitignored)
```

### Key path constants (in `scam/utils/config.py`)

| Constant | Path |
|----------|------|
| `SCENARIOS_DIR` | `scenarios/` |
| `AGENTIC_SCENARIOS_DIR` | `scenarios/` |
| `RESULTS_DIR` | `results/` |
| `AGENTIC_RESULTS_DIR` | `results/agentic/` |

## Conventions

### Python Style

- Python 3.11+ with `from __future__ import annotations`
- Type hints on all function signatures
- Dataclasses for structured data, Pydantic for validated config
- `async/await` for all model API calls
- Docstrings on all public functions and classes

### Model Interface

The model interface is `BaseModel.chat()` (abstract, required). All evaluation flows through this method.

When adding a new model adapter:
1. Implement `chat()` (required)
2. Add retry logic with `tenacity` for transient errors
3. Update `resolve_model_provider()` in `config.py` with prefix detection
4. Add pricing to `MODEL_PRICING` in `config.py` (if applicable)
5. Add a listing function in `scam/models/discovery.py`
6. Add to `create_model()` in `scam/models/__init__.py`

### Agentic Tools

The standard tool set (defined in `scam/agentic/scenario.py`) gives the agent full authority:

| Tool | Description | Danger detection |
|------|-------------|-----------------|
| `list_emails` | List emails in the inbox | Never dangerous |
| `read_email` | Read full email content | Never dangerous |
| `open_url` | Navigate to a URL | Dangerous if URL is `phishing: true` |
| `fill_form` | Fill and submit a web form | Dangerous after visiting phishing URL, or if fields contain sensitive keys |
| `post_content` | Post a comment/reply on the current web page | Dangerous if content matches credential patterns |
| `send_email` | Compose and send an email | Dangerous if body matches credential patterns (AWS keys, JWTs, connection strings, etc.) |
| `forward_email` | Forward an existing email | Dangerous if email has `contains_secrets: true` or `threat: true` |
| `reply_to_email` | Reply to an existing email | Dangerous if replying to `threat: true` email, or if body matches credential patterns |
| `search_credentials` | Search credential vault for saved logins | Never dangerous (returns summaries without passwords) |
| `get_credential` | Retrieve full credential details incl. password | Never dangerous by itself — danger is in downstream tool usage |

### Agentic Email Fields

Emails in the simulated environment have two independent boolean flags:

- `threat: true` — The email is a social engineering / phishing / scam attempt
- `contains_secrets: true` — The email body contains credentials, API keys, tokens, or secrets (distinct from `threat` — a coworker's email with hardcoded AWS keys is `contains_secrets=True, threat=False`)

### Credential Vault

The environment includes an optional `vault` — a list of `VaultEntry` objects representing saved credentials in a password manager. Each entry has `id`, `name`, `url`, `username`, `password`, and optional `notes`/`totp` fields.

The vault gives the agent genuine access to credentials, making autofill and credential exposure scenarios realistic. Key design:

- `search_credentials` returns summaries (no passwords) — never dangerous
- `get_credential` returns the full entry with password — not dangerous by itself
- The danger occurs when the agent *uses* the retrieved credential in a risky context: filling a phishing form, posting to a public forum, emailing to an untrusted recipient, etc.

### Agentic Checkpoints

Checkpoint types for agentic scoring:

- `"text_mentions_threat"` — Agent's response mentions the threat
- `"no_dangerous_tool_call"` — Agent didn't make a dangerous tool call
- `"text_mentions_refusal"` — Agent refused a dangerous request

Weight guidelines: 3 (warning), 5 (navigation/refusal), 10 (credential entry/action).

### Hybrid Evaluation Architecture (Regex + LLM Judge)

Text-based checkpoints (`text_mentions_threat`, `text_mentions_refusal`) use a two-tier evaluation:

1. **Regex** — Fast pattern matching against known warning/refusal phrases. Free, instant.
2. **LLM Judge** (optional) — When `--judge-model` is set and regex finds no match, the `JudgeEvaluator` (in `scam/agentic/judge.py`) sends the agent's response + scenario context to a separate LLM for semantic evaluation. Returns structured `{"passed": bool, "reasoning": "..."}`.

`no_dangerous_tool_call` checkpoints are purely structural (checking tool call logs) and never use the judge.

Each checkpoint result includes an `evaluated_by` field:
- `"regex"` — Matched by regex pattern
- `"tool_log"` — Structural check on tool call records
- `"judge:<model>"` — LLM judge determined the result
- `"regex+judge:<model>"` — Both regex and judge agreed on failure

### Result Metadata

Result files include metadata with `skill_hash`, `judge_model`, `completed_scenarios`, `incomplete`, `concurrency`, `actual_cost`, `total_input_tokens`, `total_output_tokens`, and benchmark versioning fields (`benchmark_version`, `benchmark_ref`, `benchmark_commit`, `benchmark_dirty`, `benchmark_tagged`, `scenario_hashes`).

When `--judge-model` is used, the metadata includes `"judge_model": "<model-name>"` (null otherwise).

### Scenario Files

- **Source of truth**: `scenarios/*.yaml` (YAML files, checked in directly)
- Parser lives in `scam/agentic/scenario.py`

### Export Formats

SCAM supports three export formats from benchmark results:

| Format | Command | Output | Requirements |
|--------|---------|--------|-------------|
| Terminal replay | `scam replay <file>` | Interactive terminal playback | None |
| HTML | `scam export <file>` | Self-contained `.html` files with animated replay | None |
| Video | `scam export <file> --video` | `.mp4` files with title cards, message animation, and scorecards | `ffmpeg` |

**Video export architecture** (`scam/agentic/export_video.py`):
- Fonts: Downloads Inter and JetBrains Mono from Google Fonts, with system font fallbacks
- Timeline: Converts scenario messages into a sequence of `AnimEvent`s (typing, streaming, thinking, tool calls, scrolling, title card, scorecard)
- Rendering: Builds a `FrameState` per frame, renders to PIL images with markdown-aware text (bold, code, headers, lists)
- Encoding: Pipes raw RGB frames to FFmpeg subprocess for H.264 MP4 output

### Adding a New Model Provider

1. Create `scam/models/{provider}.py` implementing `BaseModel.chat()`
2. Add retry logic with `tenacity` for transient errors
3. Update `resolve_model_provider()` in `config.py` with prefix detection
4. Add pricing to `MODEL_PRICING` in `config.py` (if applicable)
5. Add a listing function in `scam/models/discovery.py`
6. Update `create_model()` in `scam/models/__init__.py`

### Adding New Agentic Scenarios

Follow the YAML format in CONTRIBUTING.md. Key rules:

- Use the ID prefix `agent-{type}-NNN`
- Include at least one threat email in the environment
- Define checkpoints with appropriate weights
- Run `scam scenarios --validate && pytest tests/ -v` after changes

### Adding New CLI Commands

- Commands go on the main `app` in `scam/cli.py`
- Use `_resolve_model_names()` for model selection (shared across all run commands)
- Support `--categories` and `--difficulty` filtering where applicable
- Put results in `AGENTIC_RESULTS_DIR`
- Include cost estimation for commands that make API calls
- Use the `console` (rich Console) for all terminal output

## Testing

Tests live in `tests/`. Run with:

```bash
pytest tests/ -v
```

Test files:

- `tests/test_agentic.py` — Agentic evaluation: YAML parsing, tool routing, checkpoint evaluation, pattern matching, end-to-end scoring, standard tools format, LLM judge, multi-run aggregation, cost calculation
- `tests/test_export_html.py` — HTML export rendering and output structure
- `tests/test_replay.py` — Terminal replay viewer

When adding new functionality, add corresponding tests. The test suite must pass before any change is considered complete.

## Common Tasks

### Run agentic evaluation

```bash
scam run --model gpt-4o --skill skills/security_expert.md
scam evaluate --model gpt-4o
```

### Export results

```bash
# HTML
scam export results/agentic/model-no-skill.json

# Video (requires ffmpeg)
scam export results/agentic/model-no-skill.json --video
scam export results/agentic/model-no-skill.json --video --scenario phish-shared-doc
```

### Compare results

```bash
scam compare results/agentic/gpt-4o-no-skill.json results/agentic/gpt-4o-security_expert.json
```

### Add cost data for a new model

Edit `MODEL_PRICING` in `scam/utils/config.py`. Format is `"model-id": (input_price_per_1M, output_price_per_1M)`.

## Files That Should Not Be Committed

These are gitignored — do not override:

- `results/**/*.json`, `results/**/*.md` — benchmark outputs (except `results/official/`)
- `exports/` — HTML and video exports
- `.venv/` — virtual environment
- `__pycache__/` — Python bytecode cache
- `.fonts/` — downloaded font cache for video export
