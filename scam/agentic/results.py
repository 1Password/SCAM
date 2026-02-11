"""Unified result format (v2) for SCAM agentic benchmarks.

Every CLI invocation of ``scam run`` or ``scam evaluate`` produces exactly
one JSON file with all models, phases, runs, and summaries.

File naming: ``results/agentic/scam-{command}-{epoch}.json``
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path


# ── Statistics helpers (shared with aggregate.py) ────────────────────

_T_TABLE_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045,
}


def _t_value(n: int) -> float:
    df = n - 1
    if df in _T_TABLE_95:
        return _T_TABLE_95[df]
    return 1.96


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def _stability(std: float) -> str:
    if std == 0.0:
        return "stable"
    if std < 0.1:
        return "low_variance"
    return "unstable"


# ── Phase summary computation ────────────────────────────────────────


def compute_phase_summary(run_results: list[dict]) -> dict:
    """Compute summary statistics for a list of runs in a single phase.

    Each *run_result* is a raw result dict from ``run_agentic_benchmark()``
    with ``"scores"`` and ``"metadata"`` keys.

    Returns a summary dict with mean, std, CI, and per-scenario stats.
    """
    n = len(run_results)
    if n == 0:
        return {"mean_safety_score": 0.0}

    # Per-run overall safety scores
    per_run_scores = []
    for run in run_results:
        scores = run.get("scores", [])
        avg = _mean([s["safety_score"] for s in scores]) if scores else 0.0
        per_run_scores.append(avg)

    overall_mean = _mean(per_run_scores)
    overall_std = _std(per_run_scores) if n > 1 else 0.0

    # Per-scenario stats
    scenario_scores: dict[str, list[float]] = {}
    scenario_crits: dict[str, list[bool]] = {}
    for run in run_results:
        for entry in run.get("scores", []):
            sid = entry["scenario_id"]
            scenario_scores.setdefault(sid, []).append(entry["safety_score"])
            scenario_crits.setdefault(sid, []).append(
                bool(entry.get("critical_failure"))
            )

    per_scenario: dict[str, dict] = {}
    for sid, scores in scenario_scores.items():
        m = _mean(scores)
        s = _std(scores)
        crits = scenario_crits.get(sid, [])
        crit_rate = sum(crits) / len(crits) if crits else 0.0
        per_scenario[sid] = {
            "mean": round(m, 4),
            "std": round(s, 4),
            "min": round(min(scores), 4),
            "max": round(max(scores), 4),
            "stability": _stability(s),
            "critical_failure_rate": round(crit_rate, 4),
        }

    # Total critical failures (mean across runs)
    crit_counts = []
    for run in run_results:
        c = sum(1 for s in run.get("scores", []) if s.get("critical_failure"))
        crit_counts.append(c)

    summary: dict = {
        "mean_safety_score": round(overall_mean, 4),
        "critical_failure_count": round(_mean(crit_counts), 2),
        "per_scenario": per_scenario,
    }

    if n > 1:
        t = _t_value(n)
        margin = t * overall_std / math.sqrt(n)
        summary["std_safety_score"] = round(overall_std, 4)
        summary["ci_95"] = [
            round(overall_mean - margin, 4),
            round(overall_mean + margin, 4),
        ]
        summary["per_run_scores"] = [round(s, 4) for s in per_run_scores]

    return summary


# ── Run entry builder ────────────────────────────────────────────────


def _build_run_entry(run_result: dict, run_index: int) -> dict:
    """Convert a raw runner result dict into a v2 run entry."""
    meta = run_result.get("metadata", {})
    scores = run_result.get("scores", [])

    avg = _mean([s["safety_score"] for s in scores]) if scores else 0.0

    return {
        "run_index": run_index,
        "timestamp": meta.get("timestamp", ""),
        "safety_score": round(avg, 4),
        "cost": meta.get("actual_cost"),
        "input_tokens": meta.get("total_input_tokens", 0),
        "output_tokens": meta.get("total_output_tokens", 0),
        "completed_scenarios": meta.get("completed_scenarios", len(scores)),
        "errored_scenarios": meta.get("errored_scenarios", 0),
        "scenarios": scores,
    }


# ── Cross-model summary ─────────────────────────────────────────────


def compute_cross_model_summary(
    models_data: dict[str, dict[str, dict]],
    *,
    is_evaluate: bool = False,
) -> dict:
    """Build the top-level summary with leaderboard and per-scenario data.

    Args:
        models_data: Dict of ``{model_name: {phase_name: phase_dict}}``.
            Each phase_dict has ``"summary"`` and ``"runs"`` keys.
        is_evaluate: If True, expects ``"no-skill"`` and a skill phase
            per model. If False, each model has a single phase.
    """
    leaderboard: list[dict] = []
    per_scenario: dict[str, dict[str, dict]] = {}

    for model_name, phases in models_data.items():
        if is_evaluate:
            # Find baseline and skill phases
            baseline_phase = phases.get("no-skill", {})
            skill_phase_name = next(
                (k for k in phases if k != "no-skill"), None
            )
            skill_phase = phases.get(skill_phase_name, {}) if skill_phase_name else {}

            bl_summary = baseline_phase.get("summary", {})
            sk_summary = skill_phase.get("summary", {})
            bl_score = bl_summary.get("mean_safety_score", 0)
            sk_score = sk_summary.get("mean_safety_score", 0)

            entry = {
                "model": model_name,
                "baseline": round(bl_score, 4),
                "skill": round(sk_score, 4),
                "delta": round(sk_score - bl_score, 4),
                "baseline_critical_failures": bl_summary.get("critical_failure_count", 0),
                "skill_critical_failures": sk_summary.get("critical_failure_count", 0),
            }
            leaderboard.append(entry)

            # Per-scenario cross-model data
            bl_per = bl_summary.get("per_scenario", {})
            sk_per = sk_summary.get("per_scenario", {})
            all_sids = set(bl_per.keys()) | set(sk_per.keys())
            for sid in all_sids:
                if sid not in per_scenario:
                    per_scenario[sid] = {}
                per_scenario[sid][model_name] = {
                    "baseline": bl_per.get(sid, {}).get("mean", 0),
                    "skill": sk_per.get(sid, {}).get("mean", 0),
                }
        else:
            # Single phase (run command)
            phase_name = next(iter(phases), "no-skill")
            phase = phases.get(phase_name, {})
            phase_summary = phase.get("summary", {})
            score = phase_summary.get("mean_safety_score", 0)

            entry = {
                "model": model_name,
                "score": round(score, 4),
                "critical_failures": phase_summary.get("critical_failure_count", 0),
            }
            leaderboard.append(entry)

            # Per-scenario cross-model data
            phase_per = phase_summary.get("per_scenario", {})
            for sid, stats in phase_per.items():
                if sid not in per_scenario:
                    per_scenario[sid] = {}
                per_scenario[sid][model_name] = {
                    "score": stats.get("mean", 0),
                }

    # Sort leaderboard by best score descending
    if is_evaluate:
        leaderboard.sort(key=lambda e: e.get("skill", 0), reverse=True)
    else:
        leaderboard.sort(key=lambda e: e.get("score", 0), reverse=True)

    return {
        "leaderboard": leaderboard,
        "per_scenario": per_scenario,
    }


# ── Unified result builder ───────────────────────────────────────────


def build_unified_result(
    *,
    command: str,
    collected_data: dict[str, dict[str, list[dict]]],
    skill_file: str | None = None,
    skill_hash: str | None = None,
    skill_text: str | None = None,
    judge_model: str | None = None,
    scenario_count: int = 0,
    categories_filter: str | None = None,
    difficulty_filter: str | None = None,
    scenario_hashes: dict[str, str] | None = None,
) -> dict:
    """Assemble a complete v2 result dict.

    Args:
        command: ``"run"`` or ``"evaluate"``.
        collected_data: Nested dict of
            ``{model_name: {phase_name: [run_result, ...]}}``.
            Each run_result is a raw dict from ``run_agentic_benchmark()``.
        skill_file: Name of the skill file used (e.g. ``"security_expert.md"``).
        skill_hash: Hash of the skill file content.
        skill_text: Full text content of the skill file.
        judge_model: Model used for LLM-as-judge.
        scenario_count: Number of scenarios evaluated.
        categories_filter: Category filter applied, if any.
        difficulty_filter: Difficulty filter applied, if any.
        scenario_hashes: Mapping of ``{scenario_id: sha256_prefix}`` for
            each scenario YAML file used in this run.
    """
    now = datetime.now(timezone.utc)
    epoch = int(time.time())

    # Compute total cost and tokens
    total_cost = 0.0
    total_input = 0
    total_output = 0
    all_model_names: list[str] = []
    runs_per_phase = 0

    models_section: dict[str, dict] = {}
    all_errors: list[dict] = []

    for model_name, phases in collected_data.items():
        all_model_names.append(model_name)
        model_entry: dict[str, dict] = {}

        for phase_name, run_results in phases.items():
            if not run_results:
                continue

            runs_per_phase = max(runs_per_phase, len(run_results))

            # Build run entries
            run_entries = []
            for idx, run_result in enumerate(run_results, 1):
                run_entry = _build_run_entry(run_result, idx)
                run_entries.append(run_entry)

                # Accumulate totals
                cost = run_entry.get("cost")
                if cost is not None:
                    total_cost += cost
                total_input += run_entry.get("input_tokens", 0)
                total_output += run_entry.get("output_tokens", 0)

                # Collect errors
                errored = run_entry.get("errored_scenarios", 0)
                if errored > 0:
                    for sc in run_entry.get("scenarios", []):
                        if sc.get("error"):
                            all_errors.append({
                                "model": model_name,
                                "phase": phase_name,
                                "run_index": idx,
                                "scenario_id": sc["scenario_id"],
                                "error": sc["error"],
                            })

            # Compute phase summary
            summary = compute_phase_summary(run_results)

            model_entry[phase_name] = {
                "runs": run_entries,
                "summary": summary,
            }

        models_section[model_name] = model_entry

    # Cross-model summary
    is_evaluate = command == "evaluate"
    cross_model = compute_cross_model_summary(models_section, is_evaluate=is_evaluate)

    # Metadata
    from scam.agentic.benchmark_version import resolve_benchmark_ref

    bench = resolve_benchmark_ref()

    metadata: dict = {
        "command": command,
        "benchmark_version": bench.version,
        "benchmark_ref": bench.ref,
        "benchmark_commit": bench.commit,
        "benchmark_dirty": bench.dirty,
        "benchmark_tagged": bench.tagged,
        "timestamp": now.isoformat(),
        "epoch": epoch,
        "models": all_model_names,
        "skill_file": skill_file,
        "skill_hash": skill_hash,
        "skill_text": skill_text,
        "judge_model": judge_model,
        "runs_per_phase": runs_per_phase,
        "scenario_count": scenario_count,
        "scenario_hashes": scenario_hashes or {},
        "total_cost": round(total_cost, 6),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
    }
    if categories_filter:
        metadata["categories_filter"] = categories_filter
    if difficulty_filter:
        metadata["difficulty_filter"] = difficulty_filter

    return {
        "version": 2,
        "metadata": metadata,
        "models": models_section,
        "summary": cross_model,
        "errors": all_errors,
    }


# ── Save / Load ──────────────────────────────────────────────────────


def save_result(result: dict, output_dir: Path | None = None) -> Path:
    """Write a v2 result dict to disk.

    Returns the path to the written file.
    """
    from scam.utils.config import AGENTIC_RESULTS_DIR

    out_dir = output_dir or AGENTIC_RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = result.get("metadata", {})
    command = meta.get("command", "run")
    epoch = meta.get("epoch", int(time.time()))
    filename = f"scam-{command}-{epoch}.json"

    path = out_dir / filename
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    return path


def load_result(path: Path) -> dict:
    """Load a v2 result file.

    Raises ``ValueError`` if the file is not a v2 result.
    """
    with open(path) as f:
        data = json.load(f)

    if data.get("version") != 2:
        raise ValueError(
            f"Expected v2 result format (version: 2), "
            f"got version: {data.get('version', 'missing')}. "
            f"This file was likely created with an older version of SCAM."
        )

    return data


# ── Helpers for extracting scenarios from v2 results ─────────────────


def iter_scenarios(
    result: dict,
    *,
    model: str | None = None,
    phase: str | None = None,
    run_index: int | None = None,
) -> list[tuple[str, str, int, dict]]:
    """Iterate over scenarios in a v2 result, with optional filters.

    Yields ``(model_name, phase_name, run_index, scenario_dict)`` tuples.
    If *run_index* is not specified, uses the first run for each phase.
    """
    results: list[tuple[str, str, int, dict]] = []
    models = result.get("models", {})

    for model_name, phases in models.items():
        if model and model_name != model:
            continue
        for phase_name, phase_data in phases.items():
            if phase and phase_name != phase:
                continue
            runs = phase_data.get("runs", [])
            if not runs:
                continue
            if run_index is not None:
                target_runs = [r for r in runs if r["run_index"] == run_index]
            else:
                target_runs = [runs[0]]

            for run in target_runs:
                for scenario in run.get("scenarios", []):
                    results.append((
                        model_name, phase_name, run["run_index"], scenario
                    ))

    return results


def get_run_metadata_for_scenario(
    result: dict,
    model_name: str,
    phase_name: str,
) -> dict:
    """Build a metadata dict compatible with export functions.

    Returns a dict resembling old v1 metadata for use with
    ``prepare_scenario_data()`` and similar functions.
    """
    meta = result.get("metadata", {})
    phase_data = result.get("models", {}).get(model_name, {}).get(phase_name, {})
    phase_summary = phase_data.get("summary", {})

    skill_hash = meta.get("skill_hash") if phase_name != "no-skill" else "none"

    return {
        "model": model_name,
        "mode": "agentic",
        "skill_hash": skill_hash or "none",
        "judge_model": meta.get("judge_model"),
        "timestamp": meta.get("timestamp", ""),
        "total_scenarios": meta.get("scenario_count", 0),
        "mean_safety_score": phase_summary.get("mean_safety_score", 0),
    }
