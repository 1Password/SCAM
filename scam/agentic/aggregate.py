"""Aggregate statistics across multiple agentic benchmark runs."""

from __future__ import annotations

import json
import math
from pathlib import Path


# t-values for 95% CI (two-tailed) indexed by degrees of freedom (n-1).
# Covers n=2..30 runs so we avoid a scipy dependency.
_T_TABLE_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045,
}


def _t_value(n: int) -> float:
    """Return the t-value for a 95% CI with *n* observations."""
    df = n - 1
    if df in _T_TABLE_95:
        return _T_TABLE_95[df]
    # For n > 30, approximate with 1.96 (normal distribution)
    return 1.96


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def _stability(std: float) -> str:
    """Classify score stability based on standard deviation."""
    if std == 0.0:
        return "stable"
    if std < 0.1:
        return "low_variance"
    return "unstable"


def aggregate_runs(run_results: list[dict]) -> dict:
    """Compute per-scenario and overall statistics across multiple runs.

    Args:
        run_results: List of result dicts from ``run_agentic_benchmark()``.

    Returns:
        A summary dict with ``metadata``, ``aggregate``, and ``scenarios`` keys.
    """
    if not run_results:
        raise ValueError("No run results to aggregate")

    # Use metadata from the first run as baseline
    first_meta = run_results[0].get("metadata", {})

    # Collect per-scenario scores across runs
    scenario_scores: dict[str, list[float]] = {}
    for run in run_results:
        for score_entry in run.get("scores", []):
            sid = score_entry["scenario_id"]
            scenario_scores.setdefault(sid, []).append(score_entry["safety_score"])

    # Collect per-scenario critical failures across runs
    scenario_crits: dict[str, list[bool]] = {}
    for run in run_results:
        for score_entry in run.get("scores", []):
            sid = score_entry["scenario_id"]
            scenario_crits.setdefault(sid, []).append(
                bool(score_entry.get("critical_failure"))
            )

    # Per-scenario stats
    scenarios: dict[str, dict] = {}
    for sid, scores in scenario_scores.items():
        m = _mean(scores)
        s = _std(scores)
        crits = scenario_crits.get(sid, [])
        crit_count = sum(crits)
        perfect_count = sum(1 for v in scores if v >= 1.0)
        scenarios[sid] = {
            "scores": [round(v, 4) for v in scores],
            "mean": round(m, 4),
            "std": round(s, 4),
            "min": round(min(scores), 4),
            "max": round(max(scores), 4),
            "range": round(max(scores) - min(scores), 4),
            "stability": _stability(s),
            "critical_failure_count": crit_count,
            "perfect_count": perfect_count,
        }

    # Overall aggregate
    overall_scores = [
        _mean([score_entry["safety_score"] for score_entry in run.get("scores", [])])
        for run in run_results
    ]
    overall_mean = _mean(overall_scores)
    overall_std = _std(overall_scores)

    n = len(run_results)
    t = _t_value(n)
    margin = t * overall_std / math.sqrt(n) if n > 1 else 0.0

    # Total cost across all runs
    total_cost = sum(
        run.get("metadata", {}).get("actual_cost", 0) or 0
        for run in run_results
    )
    total_input_tokens = sum(
        run.get("metadata", {}).get("total_input_tokens", 0)
        for run in run_results
    )
    total_output_tokens = sum(
        run.get("metadata", {}).get("total_output_tokens", 0)
        for run in run_results
    )

    # Per-run stats
    pass_counts = []
    crit_counts = []
    for run in run_results:
        passed = sum(
            1 for s in run.get("scores", [])
            if s["safety_score"] >= 1.0
        )
        crits = sum(
            1 for s in run.get("scores", [])
            if s.get("critical_failure")
        )
        pass_counts.append(passed)
        crit_counts.append(crits)

    stable_count = sum(1 for s in scenarios.values() if s["stability"] == "stable")
    unstable_count = sum(1 for s in scenarios.values() if s["stability"] == "unstable")
    low_var_count = sum(1 for s in scenarios.values() if s["stability"] == "low_variance")
    total_scenarios = len(scenarios)

    return {
        "metadata": {
            "model": first_meta.get("model"),
            "skill_hash": first_meta.get("skill_hash"),
            "total_runs": n,
            "completed_runs": n,
            "total_cost": round(total_cost, 6),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "run_files": [f"run-{i + 1:03d}.json" for i in range(n)],
        },
        "aggregate": {
            "mean_safety_score": round(overall_mean, 4),
            "std_safety_score": round(overall_std, 4),
            "ci_95_low": round(overall_mean - margin, 4),
            "ci_95_high": round(overall_mean + margin, 4),
            "per_run_scores": [round(s, 4) for s in overall_scores],
            "pass_count_mean": round(_mean(pass_counts), 2),
            "pass_count_std": round(_std(pass_counts), 2),
            "critical_failure_mean": round(_mean(crit_counts), 2),
            "critical_failure_std": round(_std(crit_counts), 2),
            "total_scenarios": total_scenarios,
            "stable_scenarios": stable_count,
            "low_variance_scenarios": low_var_count,
            "unstable_scenarios": unstable_count,
        },
        "scenarios": scenarios,
    }


def save_multi_run(
    run_results: list[dict],
    out_dir: Path,
) -> Path:
    """Save individual run JSONs and a summary to *out_dir*.

    Args:
        run_results: List of result dicts from ``run_agentic_benchmark()``.
        out_dir: Directory to write files into (created if needed).

    Returns:
        Path to the ``summary.json`` file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write individual runs
    for i, run in enumerate(run_results, start=1):
        run_path = out_dir / f"run-{i:03d}.json"
        with open(run_path, "w") as f:
            json.dump(run, f, indent=2, default=str)

    # Write summary
    summary = aggregate_runs(run_results)
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    return summary_path


def load_multi_run(out_dir: Path) -> dict:
    """Load a multi-run summary from *out_dir*.

    Returns:
        The summary dict. If ``summary.json`` exists it is returned
        directly; otherwise individual ``run-*.json`` files are loaded
        and aggregated on the fly.
    """
    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            return json.load(f)

    # Fall back: load individual runs and aggregate
    run_files = sorted(out_dir.glob("run-*.json"))
    if not run_files:
        raise FileNotFoundError(f"No run files found in {out_dir}")

    run_results = []
    for rf in run_files:
        with open(rf) as f:
            run_results.append(json.load(f))

    return aggregate_runs(run_results)


def averaged_result(run_results: list[dict]) -> dict:
    """Convert multiple run results into a single result dict with mean scores.

    Produces a result with the *same schema* as a single run (``"scores"``
    and ``"metadata"`` keys) so it can be consumed by cross-model comparison
    functions.  Adds a ``"multi_run"`` key with per-scenario std, overall
    statistics, and stability info so that callers can optionally display
    variance.

    If *run_results* has a single element, returns it unchanged.
    """
    if len(run_results) == 1:
        return run_results[0]

    summary = aggregate_runs(run_results)
    agg = summary["aggregate"]
    scenarios = summary["scenarios"]
    meta = summary["metadata"]

    # Use first run as template for scenario order and metadata
    first = run_results[0]
    first_scores = first.get("scores", [])

    averaged_scores: list[dict] = []
    for entry in first_scores:
        sid = entry["scenario_id"]
        sc = scenarios.get(sid, {})
        averaged_scores.append({
            **entry,
            "safety_score": sc.get("mean", entry["safety_score"]),
        })

    # Build multi-run metadata
    multi_run_info = {
        "runs": meta.get("total_runs", len(run_results)),
        "overall_std": agg.get("std_safety_score", 0),
        "ci_95_low": agg.get("ci_95_low", 0),
        "ci_95_high": agg.get("ci_95_high", 0),
        "per_run_scores": agg.get("per_run_scores", []),
        "stable_scenarios": agg.get("stable_scenarios", 0),
        "unstable_scenarios": agg.get("unstable_scenarios", 0),
        "scenarios": {
            sid: {
                "std": sc.get("std", 0),
                "min": sc.get("min", 0),
                "max": sc.get("max", 0),
                "stability": sc.get("stability", "stable"),
            }
            for sid, sc in scenarios.items()
        },
    }

    return {
        "scores": averaged_scores,
        "metadata": {
            **first.get("metadata", {}),
            "actual_cost": meta.get("total_cost", 0),
            "total_input_tokens": meta.get("total_input_tokens", 0),
            "total_output_tokens": meta.get("total_output_tokens", 0),
        },
        "multi_run": multi_run_info,
    }
