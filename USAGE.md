# SCAM Usage Guide

Full CLI reference and operational documentation for SCAM. For an overview of what SCAM is and why it exists, see the [README](README.md).

## Commands

### `scam run` — Run the Benchmark

```bash
scam run --model gpt-4o                    # Single model
scam run --model gpt-4o,claude-sonnet-4    # Multiple models
scam run --model gpt-4o --skill skills/security_expert.md  # With a skill
scam run --model gpt-4o --verbose          # See full transcripts
scam run --model gpt-4o --judge-model gpt-4o-mini  # LLM judge fallback
scam run --model gpt-4o --runs 5           # Multi-run for statistical confidence
scam run --model gpt-4o --parallel 3       # Run multiple models in parallel
```

### `scam evaluate` — Baseline vs Skill Comparison

Runs the benchmark twice (no skill, then with the security expert skill) and prints a side-by-side safety comparison.

```bash
scam evaluate --model gpt-4o
scam evaluate --model gpt-4o --report results/report.md
scam evaluate --model gpt-4o --categories agentic_phishing --difficulty 4,5
```

### `scam replay` — Interactive Terminal Replay

Watch a recorded scenario conversation play back in the terminal with typing effects, tool calls, and a final checkpoint scorecard.

```bash
scam replay results/agentic/model-no-skill.json
scam replay results/agentic/model-no-skill.json --scenario phish-shared-doc
scam replay results/agentic/model-no-skill.json --speed fast
```

### `scam export` — HTML and Video Export

Export scenario replays as self-contained HTML pages or MP4 videos for sharing.

```bash
# HTML export (interactive replay pages)
scam export results/agentic/model-no-skill.json
scam export results/agentic/model-no-skill.json --scenario phish-shared-doc

# Video export (MP4 recordings with title cards and scorecards)
scam export results/agentic/model-no-skill.json --video
scam export results/agentic/model-no-skill.json --video --scenario phish-shared-doc --fps 30
```

Video export requires `ffmpeg` to be installed (`brew install ffmpeg` on macOS).

### `scam publish` — Generate GitHub Pages Site

Generate the SCAM website with leaderboard, featured replays, and the security skill from benchmark results.

```bash
scam publish results/agentic/scam-evaluate-1770653270.json           # Generate site in docs/
scam publish results/agentic/scam-evaluate-1770653270.json -o site/  # Custom output dir
```

Then commit the `docs/` directory and enable GitHub Pages in repo settings (Source: main branch, `/docs` folder).

### `scam scenarios` — Inspect Scenarios

```bash
scam scenarios                  # Summary (count, categories, difficulty)
scam scenarios --list           # Full table of all scenarios
scam scenarios --validate       # Validate YAML schema
scam scenarios --categories     # List categories
```

### `scam compare` / `scam report` — Analyze Results

```bash
scam compare results/agentic/model-no-skill.json results/agentic/model-security_expert.json
scam report results/agentic/model-no-skill.json --output report.md
```

## Simulated Tools

Each scenario gives the agent access to a sandboxed set of MCP-style tool servers. Nothing is real — no emails are sent, no credentials are exposed, no live systems are touched.

| Tool | Description |
|------|-------------|
| `list_emails` | List emails in the simulated inbox |
| `read_email` | Read a specific email by ID |
| `reply_to_email` | Reply to an email |
| `forward_email` | Forward an email to a recipient |
| `send_email` | Compose and send a new email |
| `open_url` | Visit a URL and see its content |
| `fill_form` | Submit a form on a visited page |
| `search_credentials` | Search the credential vault for matching entries |
| `get_credential` | Retrieve full credential details from the vault |
| `post_content` | Post content to a public URL (forum, social media, etc.) |

## Multi-Run Statistics

LLM outputs are non-deterministic. Use `--runs` to run the benchmark multiple times and get statistical confidence:

```bash
scam run --model gpt-4o --runs 5
```

This produces per-run results, a `summary.json` with mean, standard deviation, 95% confidence intervals, and a stability rating for each scenario and the overall score.

## Skills

Skills are markdown files that get prepended to the agent's system prompt. They change the agent's behavior without changing the model or the scenario.

| Skill | Description |
|-------|-------------|
| `baseline.md` | Minimal prompt (used as the control in `evaluate`) |
| `security_expert.md` | Security awareness guidance: domain verification, credential handling, content analysis before action |

## Supported Providers

| Provider | API Key |
|----------|---------|
| **Anthropic** (Claude) | `ANTHROPIC_API_KEY` |
| **OpenAI** (GPT, o-series) | `OPENAI_API_KEY` |
| **Google** (Gemini) | `GOOGLE_API_KEY` |

Models are discovered dynamically from each provider's API. Use `scam run --model anthropic -i` for interactive selection.

## Benchmark Versioning

SCAM uses a versioning system that ties results to an exact, reproducible state of the test suite. Every result file records the benchmark version and git provenance so you can always answer: "what exactly was tested, and can I trust this result?"

### How it works

The **benchmark version** (e.g. `v0.1`) covers the contract: which scenarios exist, how they're evaluated, and how scoring works. It does _not_ cover the CLI, HTML export, or model adapters — those are tooling and evolve independently.

At runtime, the benchmark resolves its version from git:

| Git state | Label | Meaning |
|-----------|-------|---------|
| Clean tree, on `benchmark/v0.1` tag | `v0.1` | Official release — results are fully reproducible |
| On the tag, uncommitted changes | `v0.1+dirty` | Modified scenarios or scoring — results may differ |
| Ahead of the tag | `v0.1+dev.g3a2b1c` | Development build past the release |
| No benchmark tag | `v0.1-untagged+g3a2b1c` | Tag hasn't been cut yet |

Every result JSON records:
- `benchmark_version` — the base version for filtering and comparison
- `benchmark_ref` — the full label including git state
- `benchmark_commit` — the exact commit hash
- `benchmark_dirty` / `benchmark_tagged` — boolean flags

Scenario YAML files are also individually hashed (SHA-256) and stored in `metadata.scenario_hashes`, so you can verify that a specific scenario hasn't changed since the result was produced.

### Cutting a release

```bash
# 1. Bump BENCHMARK_VERSION in scam/agentic/benchmark_version.py
#    e.g. BENCHMARK_VERSION = "0.2"

# 2. Commit the version bump along with any scenario/scoring changes
git add scam/agentic/benchmark_version.py
git commit -m "Bump benchmark version to 0.2"

# 3. Tag the release
git tag benchmark/v0.2
git push origin benchmark/v0.2
```

Any run from that exact commit with a clean working tree produces a green `v0.2` label. Results from dirty or untagged trees are visibly flagged in both the CLI output and the HTML dashboard.

## Testing

```bash
pytest tests/ -v
```

## Project Structure

```
SCAM/
├── scam/
│   ├── cli.py                 # CLI entry point
│   ├── models/                # Model adapters
│   │   ├── base.py            # Abstract interface (chat)
│   │   ├── anthropic.py       # Anthropic Claude
│   │   ├── openai.py          # OpenAI GPT / o-series
│   │   ├── gemini.py          # Google Gemini
│   │   └── discovery.py       # Dynamic model listing from provider APIs
│   ├── agentic/               # Core: agentic evaluation engine
│   │   ├── benchmark_version.py # Benchmark version + git provenance
│   │   ├── scenario.py        # YAML parser + data models
│   │   ├── environment.py     # Simulated tool environment + routing
│   │   ├── evaluator.py       # Checkpoint-based scoring
│   │   ├── judge.py           # LLM-as-judge for ambiguous checkpoints
│   │   ├── runner.py          # Multi-turn conversation orchestrator
│   │   ├── reporting.py       # Report generation + comparison
│   │   ├── aggregate.py       # Multi-run statistical aggregation
│   │   ├── replay.py          # Terminal replay viewer
│   │   ├── export_html.py     # Self-contained HTML export
│   │   ├── export_video.py    # MP4 video export (Pillow + FFmpeg)
│   │   └── site_generator.py  # GitHub Pages site generator
│   └── utils/
│       └── config.py          # Paths, pricing, API keys
├── scenarios/                 # Agentic scenario YAML files
│   ├── inbox_phishing.yaml
│   ├── social_engineering.yaml
│   ├── credential_exposure.yaml
│   ├── credential_autofill.yaml
│   ├── ecommerce_scams.yaml
│   ├── data_leakage.yaml
│   ├── confused_deputy.yaml
│   ├── multi_stage.yaml
│   ├── prompt_injection.yaml
│   └── _template.yaml         # Starter template for contributors
├── skills/                    # System prompt skill files
│   ├── baseline.md
│   └── security_expert.md
├── results/
│   ├── official/              # Tracked official evaluation results
│   └── agentic/               # Scratch evaluations (gitignored)
├── exports/                   # HTML + video exports (gitignored)
├── tests/
│   ├── test_agentic.py
│   ├── test_export_html.py
│   └── test_replay.py
├── CONTRIBUTING.md
├── LICENSE
└── AGENTS.md
```

## License

SCAM is released under the [MIT License](LICENSE).

Copyright (c) 2026 [1Password](https://1password.com)
