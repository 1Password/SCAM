# Maintainers Guide

This document covers operational tasks that only project maintainers should perform: cutting benchmark releases, updating the website, running official evaluations, and managing the repository.

## Cutting a Benchmark Release

The benchmark version (e.g. `v0.1`) is the contract that makes results comparable. Bump it whenever scenarios, checkpoints, scoring logic, or the tool environment change in a way that affects results.

### Steps

```bash
# 1. Edit the version string
#    File: scam/agentic/benchmark_version.py
#    Change: BENCHMARK_VERSION = "0.2"

# 2. Commit the version bump (include any scenario/scoring changes in the same commit or earlier)
git add scam/agentic/benchmark_version.py
git commit -m "Bump benchmark version to 0.2"

# 3. Tag the release
git tag benchmark/v0.2
git push origin main
git push origin benchmark/v0.2
```

Any run from that exact commit with a clean working tree produces a `v0.2` label. Results from dirty or untagged trees are visibly flagged in both the CLI output and the HTML dashboard.

### Important

- Do not accept PRs that bump `BENCHMARK_VERSION`. Contributors should not change the version — that is a maintainer responsibility after merge.
- The tag name format must be `benchmark/vX.Y` (e.g. `benchmark/v0.1`). The git provenance resolver looks for this prefix.

## Updating the Website

The website is a static GitHub Pages site generated from benchmark results and served from the `docs/` folder on the `main` branch.

### Running an official evaluation

Before updating the site, run a fresh evaluation across all target models:

```bash
scam evaluate -i
```

This produces a timestamped result file in `results/agentic/` (e.g. `scam-evaluate-1770653270.json`).

Review the results. If they look correct, copy the file to the official results directory and regenerate the site.

### Promoting results and regenerating the site

```bash
# 1. Copy the evaluation to the tracked official results directory
cp results/agentic/scam-evaluate-TIMESTAMP.json results/official/

# 2. Regenerate the website from the official copy
scam publish results/official/scam-evaluate-TIMESTAMP.json
```

This overwrites everything in `docs/` with:
- `index.html` — the main site with leaderboard, replays, skill viewer, and terminal demo
- `replays/*.html` — standalone replay pages for featured scenarios
- `data/scam-results.zip` — downloadable ZIP with the raw JSON and an interactive HTML dashboard for independent verification

### Publishing

```bash
# Commit both the official result and the regenerated site together
git add results/official/ docs/
git commit -m "Publish v0.X evaluation results and update website"
git push origin main
```

GitHub Pages deploys automatically from the `docs/` folder. Verify at [1password.github.io/SCAM](https://1password.github.io/SCAM/).

### GitHub Pages configuration

If setting up for the first time:
1. Go to repo Settings > Pages
2. Source: "Deploy from a branch"
3. Branch: `main`, folder: `/docs`

## Managing Results

Dev and scratch results in `results/agentic/` are gitignored — use that directory for experimentation.

Official evaluation results live in `results/official/` and **are** tracked in git. This directory contains the source JSON for every published version of the website. Do not delete old files — they serve as the historical record for prior benchmark versions.

The ZIP file included on the website (`docs/data/scam-results.zip`) also contains the raw JSON and the full HTML dashboard, so the published data is independently verifiable even without cloning the repo.

## Reviewing Scenario PRs

When reviewing a contributed scenario:

1. **Validate the YAML**: `scam scenarios --validate`
2. **Run it against at least one model**: `scam run --model gpt-4o --scenarios new-scenario-id`
3. **Check checkpoint quality**: Does the scenario fail when the agent does the wrong thing? Does it pass when the agent handles it correctly?
4. **Check difficulty rating**: Is the difficulty realistic? D1-2 should be obvious threats, D4-5 should require inference.
5. **Check for real data**: Scenarios must use realistic but fake credentials, domains, and PII. No real secrets, no real malicious URLs.

After merging scenario changes, plan a version bump (see above).

## Reviewing Code PRs

For changes to scoring, evaluation, or the tool environment:
- These affect benchmark comparability and require a version bump after merge.
- Run the full test suite: `pytest tests/ -v`
- Run at least one evaluation to verify results haven't regressed unexpectedly.

For changes to CLI, export, site generator, or model adapters:
- These do not affect benchmark versioning.
- Test the specific feature that changed.

## Current Maintainers

- [Jason Meller](https://github.com/terracatta) (1Password)
