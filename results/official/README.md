# Official Results

This directory contains the evaluation JSON files that back the published [SCAM website](https://1password.github.io/SCAM/). Each file is the output of a `scam evaluate` run used to generate the site via `scam publish`.

These files are checked into the repo so that anyone can:
- Regenerate the website from source data
- Independently verify the published leaderboard and replays
- Inspect the raw model responses behind every score

## Rules

- **Only official evaluations go here.** Do not commit dev runs, scratch tests, or partial results.
- **One file per published version.** When the website is updated, the new evaluation JSON is added here alongside the previous ones.
- **Do not delete old files.** They serve as the historical record for prior benchmark versions.

## Regenerating the site

```bash
scam publish results/official/scam-evaluate-TIMESTAMP.json
```
