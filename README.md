# SCAM — Security Comprehension Awareness Measure

**By [1Password](https://1password.com/blog/ai-agent-security-benchmark)**

> **[View the leaderboard, watch replays, and try the security skill at 1password.github.io/SCAM](https://1password.github.io/SCAM/)**

As AI agents become more capable, they are gaining access to the sensitive information of the people they assist. SCAM measures whether agents will be good stewards of that information against the kinds of threats humans encounter every day.

Most benchmarks show an AI a phishing email and ask "is this bad?" SCAM is different. It tests whether an agent can proactively recognize and report threats during normal activity — dropping agents into realistic workplace situations with access to email, credential vaults, and web forms, where the traps are embedded in the workflow, not called out separately.

## Quick Start

```bash
git clone https://github.com/1Password/SCAM.git
cd SCAM
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Set at least one API key
export OPENAI_API_KEY="sk-..."       
# and/or ANTHROPIC_API_KEY, GOOGLE_API_KEY

# Run the benchmark interactively
scam evaluate -i
```

Interactive mode walks you through model selection, runs every scenario with and without the security skill, and prints a scored report at the end.

## What It Tests

Each scenario gives the agent a routine workplace task — checking email, looking up a credential, reviewing an invoice — along with a set of simulated MCP tool servers: an inbox, a password vault, a web browser, and more. These tools feel real to the model, but everything is sandboxed. No actual credentials are exposed, no real emails are sent, and no live systems are touched.

The catch is that real-world attack patterns are woven into the task. A phishing link sits in the inbox. A lookalike domain shows up in a forwarded thread. An attacker's form is pre-filled with the right company name.

The benchmark covers 30 scenarios across 9 threat categories: **Phishing** · **Social Engineering** · **Credential Exposure** · **Credential Autofill** · **E-Commerce Scams** · **Data Leakage** · **Confused Deputy** · **Multi-Stage Attacks** · **Prompt Injection**

## The Security Skill

SCAM ships with a security skill ([`security_expert.md`](skills/security_expert.md)) — a plain-text system prompt addition that teaches agents to analyze before acting: verify domains before clicking, read content before forwarding, check URLs before entering credentials.

In our benchmarks, this single skill raised average safety scores from ~50% to ~90% across all models tested. It works with any model and any provider. See the [website](https://1password.github.io/SCAM/#skill) for integration instructions.

## Results

The full leaderboard, interactive replays, and downloadable data are published at **[1password.github.io/SCAM](https://1password.github.io/SCAM/)**. Results include a ZIP archive with the raw JSON and an interactive HTML dashboard for independent verification.

## Contributing

The threat landscape changes fast, and no single team can cover all of it. If you work in security, AI safety, or red-teaming, there are real ways to help:

- **Write new scenarios.** Model a threat you've seen in the wild. The YAML format is straightforward.
- **Add new tool servers.** Slack, Jira, cloud consoles — every new surface makes the test harder to game.
- **Improve evaluation.** Better checkpoint logic, fewer false positives, more nuanced scoring.
- **Run it on new models.** Publish your results. The more data points the community has, the harder it is to ignore.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## Learn More

- [USAGE.md](USAGE.md) — Full CLI reference, all commands and flags, supported providers, benchmark versioning, project structure
- [CONTRIBUTING.md](CONTRIBUTING.md) — Scenario authoring guide, YAML schema, difficulty scale, what makes a good scenario
- [MAINTAINERS.md](MAINTAINERS.md) — Cutting releases, updating the website, reviewing PRs
- [Website](https://1password.github.io/SCAM/) — Interactive leaderboard, featured replays, the security skill

## Acknowledgements

- [Jason Meller](https://github.com/terracatta) — created SCAM

## License

SCAM is released under the [MIT License](LICENSE).

Copyright (c) 2026 [1Password](https://1password.com)
