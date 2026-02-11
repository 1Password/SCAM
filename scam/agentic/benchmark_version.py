"""SCAM Benchmark version — frozen test corpus + scoring contract.

This version covers the scenario YAML files, checkpoint definitions,
scoring logic, tool set, and environment simulation.  It does NOT
cover CLI UX, HTML export, model adapters, or skill files (which are
independently hashed).

Bump this when scenarios, checkpoints, scoring, or evaluation logic
change in a way that makes results non-comparable.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

BENCHMARK_VERSION = "0.1"


@dataclass(frozen=True)
class BenchmarkRef:
    """Resolved benchmark version with git provenance metadata."""

    version: str       # Base version, e.g. "0.1"
    ref: str           # Full label, e.g. "0.1", "0.1+dev.g3a2b1c.dirty"
    commit: str | None  # Short commit hash, or None if not in a git repo
    dirty: bool        # True if working tree has uncommitted changes
    tagged: bool       # True if HEAD is an exact benchmark/vX.Y tag


def resolve_benchmark_ref() -> BenchmarkRef:
    """Determine the benchmark version label from git state.

    Version labels follow this scheme:

    - ``0.1``                   — clean working tree on the exact ``benchmark/v0.1`` tag
    - ``0.1+dirty``             — on the tag but with uncommitted changes
    - ``0.1+dev.g3a2b1c``      — ahead of the tag, clean tree
    - ``0.1+dev.g3a2b1c.dirty`` — ahead of the tag, dirty tree
    - ``0.1-untagged+g3a2b1c``       — no benchmark tag reachable, clean
    - ``0.1-untagged+g3a2b1c.dirty`` — no benchmark tag reachable, dirty
    - ``0.1-nogit``             — not a git repository at all

    Falls back gracefully when git is unavailable.
    """
    version = BENCHMARK_VERSION

    # ── Get commit hash ───────────────────────────────────────────
    commit = _git("rev-parse", "--short", "HEAD")
    if commit is None:
        return BenchmarkRef(
            version=version,
            ref=f"{version}-nogit",
            commit=None,
            dirty=False,
            tagged=False,
        )

    # ── Check if working tree is dirty ────────────────────────────
    dirty_output = _git("status", "--porcelain")
    dirty = bool(dirty_output and dirty_output.strip())

    # ── Check for exact benchmark tag on HEAD ─────────────────────
    exact_tag = _git(
        "describe", "--tags", "--exact-match",
        "--match", "benchmark/v*", "HEAD",
    )
    if exact_tag:
        # We're on a tagged release commit
        dirty_suffix = "+dirty" if dirty else ""
        return BenchmarkRef(
            version=version,
            ref=f"{version}{dirty_suffix}",
            commit=commit,
            dirty=dirty,
            tagged=True,
        )

    # ── Check for nearest ancestor benchmark tag ──────────────────
    desc = _git(
        "describe", "--tags", "--long",
        "--match", "benchmark/v*", "HEAD",
    )
    if desc:
        # Format: "benchmark/v0.1-3-g3a2b1c" (tag-distance-hash)
        dirty_suffix = ".dirty" if dirty else ""
        return BenchmarkRef(
            version=version,
            ref=f"{version}+dev.g{commit}{dirty_suffix}",
            commit=commit,
            dirty=dirty,
            tagged=False,
        )

    # ── No benchmark tag reachable at all ─────────────────────────
    dirty_suffix = ".dirty" if dirty else ""
    return BenchmarkRef(
        version=version,
        ref=f"{version}-untagged+g{commit}{dirty_suffix}",
        commit=commit,
        dirty=dirty,
        tagged=False,
    )


def _git(*args: str) -> str | None:
    """Run a git command and return stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
