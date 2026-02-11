"""Reporting for agentic evaluation results."""

from __future__ import annotations

import json

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def print_agentic_report(
    scores: list[dict],
    metadata: dict,
    console: Console,
) -> None:
    """Print a rich terminal report for a single agentic evaluation run."""
    console.print()
    judge = metadata.get("judge_model")
    judge_info = f"  |  Judge: [magenta]{judge}[/magenta]" if judge else ""
    console.print(Panel(
        f"[bold]SCAM Agentic Safety Report[/bold]\n"
        f"Model: [cyan]{metadata.get('model', '?')}[/cyan]  |  "
        f"Scenarios: {metadata.get('total_scenarios', len(scores))}  |  "
        f"Errors: {metadata.get('errored_scenarios', 0)}{judge_info}",
        border_style="blue",
    ))

    if not scores:
        console.print("[dim]No scores to report.[/dim]")
        return

    avg_safety = sum(s["safety_score"] for s in scores) / len(scores)
    critical_failures = sum(1 for s in scores if s.get("critical_failure"))
    total_dangerous = sum(s.get("dangerous_call_count", 0) for s in scores)

    # Overall metrics
    summary = Table(title="Overall Metrics", show_header=True, header_style="bold")
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")
    summary.add_row("Avg Safety Score", f"{avg_safety:.0%}")
    summary.add_row(
        "Critical Failures",
        f"[{'red' if critical_failures else 'green'}]{critical_failures}/{len(scores)}[/]",
    )
    summary.add_row(
        "Dangerous Tool Calls",
        f"[{'red' if total_dangerous else 'green'}]{total_dangerous}[/]",
    )
    console.print(summary)

    # Per-scenario detail
    detail = Table(title="Per-Scenario Results", show_header=True, header_style="bold")
    detail.add_column("Scenario", style="cyan")
    detail.add_column("D", justify="center")
    detail.add_column("Safety", justify="right")
    detail.add_column("Critical", justify="center")
    detail.add_column("Checkpoints", justify="left")

    for s in scores:
        cps = s.get("checkpoints", [])
        cp_parts = []
        for cp in cps:
            icon = "[green]PASS[/green]" if cp["passed"] else "[red]FAIL[/red]"
            cp_parts.append(f"{icon} {cp['id']}")
        cp_summary = " | ".join(cp_parts) if cp_parts else "[dim]no checkpoints[/dim]"

        crit = "[red]YES[/red]" if s.get("critical_failure") else "[green]no[/green]"
        safety_color = (
            "green" if s["safety_score"] >= 0.8
            else "yellow" if s["safety_score"] >= 0.5
            else "red"
        )

        detail.add_row(
            s["scenario_id"],
            str(s.get("difficulty", "")),
            f"[{safety_color}]{s['safety_score']:.0%}[/]",
            crit,
            cp_summary,
        )

    console.print(detail)

    # Failure details
    failures = [s for s in scores if s["safety_score"] < 1.0]
    if failures:
        console.print(f"\n[bold]Failure Details ({len(failures)}):[/bold]")
        for s in failures:
            console.print(
                f"\n  [cyan]{s['scenario_id']}[/cyan] "
                f"(D{s.get('difficulty', '?')}) — safety={s['safety_score']:.0%}"
            )
            for cp in s.get("checkpoints", []):
                if not cp["passed"]:
                    eval_by = cp.get("evaluated_by", "regex")
                    eval_tag = f" [magenta]\\[{eval_by}][/magenta]" if eval_by != "regex" else ""
                    console.print(f"    [red]FAIL[/red] {cp['description']}{eval_tag}")
                    if cp.get("details"):
                        console.print(f"         [dim]{cp['details']}[/dim]")


def print_agentic_comparison(
    scores_a: list[dict],
    scores_b: list[dict],
    meta_a: dict,
    meta_b: dict,
    console: Console,
) -> None:
    """Print a side-by-side comparison of two agentic evaluation runs."""
    label_a = f"{meta_a.get('model', '?')} (skill:{meta_a.get('skill_hash', 'none')[:8]})"
    label_b = f"{meta_b.get('model', '?')} (skill:{meta_b.get('skill_hash', 'none')[:8]})"

    console.print()
    console.print(Panel(
        f"[bold]SCAM Agentic Safety Comparison[/bold]\n"
        f"A: {label_a}  vs  B: {label_b}",
        border_style="blue",
    ))

    def _avg_safety(scores: list[dict]) -> float:
        return sum(s["safety_score"] for s in scores) / len(scores) if scores else 0.0

    def _critical(scores: list[dict]) -> int:
        return sum(1 for s in scores if s.get("critical_failure"))

    def _dangerous(scores: list[dict]) -> int:
        return sum(s.get("dangerous_call_count", 0) for s in scores)

    avg_a, avg_b = _avg_safety(scores_a), _avg_safety(scores_b)
    crit_a, crit_b = _critical(scores_a), _critical(scores_b)
    dang_a, dang_b = _dangerous(scores_a), _dangerous(scores_b)

    table = Table(title="Overall Comparison", show_header=True, header_style="bold")
    table.add_column("Metric", style="bold")
    table.add_column("A", justify="right")
    table.add_column("B", justify="right")
    table.add_column("Delta", justify="right")

    delta_safety = avg_b - avg_a
    delta_color = "green" if delta_safety > 0 else "red" if delta_safety < 0 else "dim"
    table.add_row(
        "Avg Safety Score",
        f"{avg_a:.0%}",
        f"{avg_b:.0%}",
        f"[{delta_color}]{delta_safety:+.0%}[/]",
    )
    delta_crit = crit_b - crit_a
    table.add_row(
        "Critical Failures",
        str(crit_a),
        str(crit_b),
        f"[{'green' if delta_crit < 0 else 'red' if delta_crit > 0 else 'dim'}]{delta_crit:+d}[/]",
    )
    delta_dang = dang_b - dang_a
    table.add_row(
        "Dangerous Calls",
        str(dang_a),
        str(dang_b),
        f"[{'green' if delta_dang < 0 else 'red' if delta_dang > 0 else 'dim'}]{delta_dang:+d}[/]",
    )
    console.print(table)

    # Per-scenario comparison
    b_by_id = {s["scenario_id"]: s for s in scores_b}
    detail = Table(title="Per-Scenario Comparison", show_header=True, header_style="bold")
    detail.add_column("Scenario", style="cyan")
    detail.add_column("D", justify="center")
    detail.add_column("Safety A", justify="right")
    detail.add_column("Safety B", justify="right")
    detail.add_column("Delta", justify="right")

    for sa in scores_a:
        sb = b_by_id.get(sa["scenario_id"], {})
        safety_a = sa["safety_score"]
        safety_b = sb.get("safety_score", 0.0)
        delta = safety_b - safety_a
        delta_color = "green" if delta > 0 else "red" if delta < 0 else "dim"
        detail.add_row(
            sa["scenario_id"],
            str(sa.get("difficulty", "")),
            f"{safety_a:.0%}",
            f"{safety_b:.0%}",
            f"[{delta_color}]{delta:+.0%}[/]",
        )
    console.print(detail)


def print_verbose_scenarios(
    scores: list[dict],
    console: Console,
) -> None:
    """Print full conversation transcripts and scoring details for each scenario.

    Used by the ``--verbose`` flag on ``scam run``.
    """
    for s in scores:
        # ── Header ──
        safety_color = (
            "green" if s["safety_score"] >= 0.8
            else "yellow" if s["safety_score"] >= 0.5
            else "red"
        )
        console.print()
        console.rule(f"[bold cyan]{s['scenario_id']}[/bold cyan]  D{s.get('difficulty', '?')}  [{safety_color}]{s['safety_score']:.0%}[/{safety_color}]")
        console.print(f"  [dim]{s.get('description', '')}[/dim]")

        # ── Conversation transcript ──
        messages = s.get("messages", [])
        if messages:
            console.print()
            for msg in messages:
                role = msg.get("role", "?")

                if role == "system":
                    # Show a truncated system prompt
                    content = msg.get("content", "")
                    preview = content[:200].replace("\n", " ")
                    if len(content) > 200:
                        preview += "..."
                    console.print(f"  [bold magenta]SYSTEM[/bold magenta]  [dim]{escape(preview)}[/dim]")

                elif role == "user":
                    console.print(f"\n  [bold blue]USER[/bold blue]  {escape(msg.get('content', ''))}")

                elif role == "assistant":
                    content = msg.get("content")
                    tool_calls = msg.get("tool_calls")

                    if tool_calls:
                        for tc in tool_calls:
                            fn = tc.get("function", {})
                            name = fn.get("name", "?")
                            args_raw = fn.get("arguments", "{}")
                            # Parse and pretty-format args
                            try:
                                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                                args_str = json.dumps(args, indent=None)
                            except (json.JSONDecodeError, TypeError):
                                args_str = str(args_raw)
                            console.print(f"  [bold yellow]TOOL CALL[/bold yellow]  {name}({escape(args_str)})")
                    elif content:
                        # Indent multi-line responses
                        lines = content.strip().split("\n")
                        console.print(f"\n  [bold green]AGENT[/bold green]")
                        for line in lines:
                            console.print(f"    {escape(line)}")

                elif role == "tool":
                    result = msg.get("content", "")
                    # Truncate long tool results
                    if len(result) > 300:
                        result = result[:300] + "..."
                    console.print(f"  [dim]  -> {escape(result)}[/dim]")

        # ── Tool call summary ──
        tool_log = s.get("tool_log", [])
        if tool_log:
            console.print()
            dangerous = [t for t in tool_log if t.get("is_dangerous")]
            console.print(f"  [bold]Tool calls:[/bold] {len(tool_log)} total, [{'red' if dangerous else 'green'}]{len(dangerous)} dangerous[/]")
            for t in dangerous:
                args_str = json.dumps(t.get("arguments", {}), indent=None)
                console.print(f"    [red]DANGEROUS[/red] {t['tool']}({escape(args_str)})")

        # ── Checkpoint details ──
        checkpoints = s.get("checkpoints", [])
        if checkpoints:
            console.print()
            console.print("  [bold]Checkpoints:[/bold]")
            for cp in checkpoints:
                icon = "[green]PASS[/green]" if cp["passed"] else "[red]FAIL[/red]"
                weight_str = f"(w={cp['weight']})"
                # Show evaluator type with distinct markers
                eval_by = cp.get("evaluated_by", "regex")
                if eval_by.startswith("judge:"):
                    eval_tag = f" [bold magenta]\\[LLM][/bold magenta]"
                elif eval_by == "tool_log":
                    eval_tag = ""
                elif eval_by.startswith("regex+judge:"):
                    eval_tag = f" [dim magenta]\\[LLM+regex][/dim magenta]"
                else:
                    eval_tag = ""
                console.print(f"    {icon} {cp['description']} [dim]{weight_str}[/dim]{eval_tag}")
                if cp.get("details") and not cp["passed"]:
                    console.print(f"         [dim]{escape(cp['details'])}[/dim]")

        # ── Error ──
        if s.get("error"):
            console.print(f"\n  [red]Error: {escape(s['error'])}[/red]")

    console.print()


def print_multi_run_report(
    out_dir,
    console: Console,
) -> None:
    """Print aggregate statistics from a multi-run directory.

    Reads ``summary.json`` from *out_dir* and renders a rich report
    with per-run scores, stability breakdown, and per-scenario details
    sorted by reliability (unstable scenarios first).
    """
    from pathlib import Path

    from scam.agentic.aggregate import load_multi_run

    summary = load_multi_run(Path(out_dir))
    meta = summary.get("metadata", {})
    agg = summary.get("aggregate", {})
    scenarios = summary.get("scenarios", {})

    n_runs = meta.get("total_runs", "?")
    skill_hash = meta.get("skill_hash", "none")
    skill_label = "[dim]none[/dim]" if skill_hash == "none" else f"[cyan]{skill_hash[:8]}[/cyan]"

    # ── Header panel ──
    per_run = agg.get("per_run_scores", [])
    run_scores_str = " → ".join(f"{s:.0%}" for s in per_run) if per_run else "n/a"

    # Compute stability from scenarios (handles old summaries without aggregate counts)
    total_n = len(scenarios)
    stable_n = agg.get("stable_scenarios") or sum(
        1 for s in scenarios.values() if s.get("stability") == "stable"
    )
    unstable_n = agg.get("unstable_scenarios") or sum(
        1 for s in scenarios.values() if s.get("stability") == "unstable"
    )
    low_var_n = agg.get("low_variance_scenarios") or sum(
        1 for s in scenarios.values() if s.get("stability") == "low_variance"
    )

    console.print()
    console.print(Panel(
        f"[bold]Multi-Run Summary[/bold]  ({n_runs} runs)\n"
        f"Model: [cyan]{meta.get('model', '?')}[/cyan]  |  "
        f"Skill: {skill_label}\n\n"
        f"  [dim]Per-run safety:[/dim]  {run_scores_str}\n"
        f"  [dim]Mean ± std:[/dim]      "
        f"{agg.get('mean_safety_score', 0):.1%} ± {agg.get('std_safety_score', 0):.3f}   "
        f"[dim]95% CI[/dim] [{max(0.0, agg.get('ci_95_low', 0)):.1%}, {min(1.0, agg.get('ci_95_high', 0)):.1%}]\n"
        f"  [dim]Perfect scores:[/dim]  "
        f"{agg.get('pass_count_mean', 0):.1f}/{total_n} scenarios  "
        f"[dim]Crit failures:[/dim] {agg.get('critical_failure_mean', 0):.1f}/{total_n}\n"
        f"  [dim]Stability:[/dim]       "
        f"[green]{stable_n} stable[/green]"
        + (f"  [yellow]{low_var_n} low-var[/yellow]" if low_var_n else "")
        + (f"  [red]{unstable_n} unstable[/red]" if unstable_n else ""),
        border_style="blue",
    ))

    # ── Per-scenario table — sorted: unstable first, then by mean ascending ──
    stability_order = {"unstable": 0, "low_variance": 1, "stable": 2}
    sorted_sids = sorted(
        scenarios.keys(),
        key=lambda sid: (
            stability_order.get(scenarios[sid].get("stability", "stable"), 2),
            scenarios[sid].get("mean", 0),
        ),
    )

    detail = Table(
        title="Per-Scenario Results (unstable first)",
        show_header=True,
        header_style="bold",
    )
    detail.add_column("Scenario", style="cyan")
    detail.add_column("Mean", justify="right")
    detail.add_column("Runs", justify="center")
    detail.add_column("Range", justify="right")
    detail.add_column("Crits", justify="center")
    detail.add_column("Status", justify="center")

    for sid in sorted_sids:
        s = scenarios[sid]
        stability = s.get("stability", "?")
        stab_color = {
            "stable": "green",
            "low_variance": "yellow",
            "unstable": "red",
        }.get(stability, "dim")

        # Color the mean
        mean_val = s.get("mean", 0)
        mean_color = "green" if mean_val >= 0.8 else "yellow" if mean_val >= 0.5 else "red"

        # Compact per-run scores with color
        run_parts = []
        for score in s.get("scores", []):
            c = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"
            run_parts.append(f"[{c}]{score:.0%}[/{c}]")
        runs_str = " ".join(run_parts)

        # Range (max - min)
        range_val = s.get("range", s.get("max", 0) - s.get("min", 0))
        range_str = f"{range_val:.0%}" if range_val > 0 else "[dim]—[/dim]"

        # Critical failure count
        crit_count = s.get("critical_failure_count", 0)
        crit_str = f"[red]{crit_count}/{n_runs}[/red]" if crit_count else f"[dim]0[/dim]"

        # Stability with icon
        if stability == "stable" and mean_val >= 1.0:
            status_str = f"[green]● perfect[/green]"
        elif stability == "stable":
            status_str = f"[green]● stable[/green]"
        elif stability == "low_variance":
            status_str = f"[yellow]◐ low-var[/yellow]"
        else:
            status_str = f"[red]○ unstable[/red]"

        detail.add_row(
            sid,
            f"[{mean_color}]{mean_val:.0%}[/{mean_color}]",
            runs_str,
            range_str,
            crit_str,
            status_str,
        )

    console.print(detail)

    # Cost summary
    total_cost = meta.get("total_cost", 0)
    total_in = meta.get("total_input_tokens", 0)
    total_out = meta.get("total_output_tokens", 0)
    if total_cost or total_in or total_out:
        console.print(
            f"\n[bold]Total cost ({n_runs} runs):[/bold] "
            f"[yellow]${total_cost:.4f}[/yellow]"
            f"  ({total_in:,} input + {total_out:,} output tokens)"
        )


def print_cross_model_comparison(
    all_results: dict[str, dict],
    console: Console,
) -> None:
    """Print a cross-model comparison table for multi-model benchmark runs.

    Args:
        all_results: Dict of ``{model_name: result_dict}`` where each
            result_dict has ``"scores"`` and ``"metadata"`` keys.
            May optionally contain a ``"multi_run"`` key with variance data.
        console: Rich console instance.
    """
    if len(all_results) < 2:
        return

    model_names = list(all_results.keys())

    # Short display names — drop common long suffixes for readability
    def _short(name: str) -> str:
        # e.g. "claude-sonnet-4-20250514" → "claude-sonnet-4"
        import re
        return re.sub(r"-\d{8}$", "", name)

    short_names = [_short(m) for m in model_names]

    # Detect multi-run mode
    any_multi = any("multi_run" in all_results[mn] for mn in model_names)
    n_runs_map = {
        mn: all_results[mn].get("multi_run", {}).get("runs", 1)
        for mn in model_names
    }

    header_extra = ""
    if any_multi:
        runs_str = ", ".join(
            f"{_short(mn)} ×{n_runs_map[mn]}" for mn in model_names
        )
        header_extra = f"\n[dim]Multi-run: {runs_str}  (scores are means)[/dim]"

    console.print()
    console.print(Panel(
        "[bold]Cross-Model Comparison[/bold]\n"
        + "  vs  ".join(f"[cyan]{s}[/cyan]" for s in short_names)
        + header_extra,
        border_style="blue",
    ))

    # ── Overall metrics table ─────────────────────────────────────
    overall = Table(title="Overall Metrics", show_header=True, header_style="bold")
    overall.add_column("Metric", style="bold")
    for sn in short_names:
        overall.add_column(sn, justify="right")

    # Compute per-model aggregates
    avgs: list[float] = []
    stds: list[float] = []
    crits: list[int] = []
    dangs: list[int] = []
    costs: list[float | None] = []

    for mn in model_names:
        scores = all_results[mn]["scores"]
        meta = all_results[mn]["metadata"]
        mr = all_results[mn].get("multi_run", {})
        avg = sum(s["safety_score"] for s in scores) / len(scores) if scores else 0.0
        crit = sum(1 for s in scores if s.get("critical_failure"))
        dang = sum(s.get("dangerous_call_count", 0) for s in scores)
        cost = meta.get("actual_cost")
        avgs.append(avg)
        stds.append(mr.get("overall_std", 0.0))
        crits.append(crit)
        dangs.append(dang)
        costs.append(cost)

    # Highlight best value per row
    best_avg = max(avgs)
    best_crit = min(crits)
    best_dang = min(dangs)

    # Safety score row — show ± std for multi-run
    avg_cells: list[str] = []
    for i, (a, s) in enumerate(zip(avgs, stds)):
        val = f"{a:.0%}"
        if s > 0:
            val += f" [dim]±{s:.2f}[/dim]"
        if a == best_avg:
            avg_cells.append(f"[bold green]{val}[/bold green]")
        else:
            avg_cells.append(val)
    overall.add_row("Avg Safety Score", *avg_cells)

    # CI row for multi-run
    if any_multi:
        ci_cells: list[str] = []
        for mn in model_names:
            mr = all_results[mn].get("multi_run", {})
            lo = mr.get("ci_95_low")
            hi = mr.get("ci_95_high")
            if lo is not None and hi is not None:
                lo_c = max(0.0, lo)
                hi_c = min(1.0, hi)
                ci_cells.append(f"[dim][{lo_c:.0%}, {hi_c:.0%}][/dim]")
            else:
                ci_cells.append("[dim]—[/dim]")
        overall.add_row("95% CI", *ci_cells)

    n_scenarios = len(next(iter(all_results.values()))["scores"])
    overall.add_row(
        "Critical Failures",
        *[
            f"[bold green]{c}/{n_scenarios}[/bold green]" if c == best_crit
            else f"[red]{c}/{n_scenarios}[/red]" if c > 0
            else f"{c}/{n_scenarios}"
            for c in crits
        ],
    )
    overall.add_row(
        "Dangerous Calls",
        *[
            f"[bold green]{d}[/bold green]" if d == best_dang
            else f"[red]{d}[/red]" if d > 0
            else str(d)
            for d in dangs
        ],
    )
    overall.add_row(
        "Actual Cost",
        *[
            f"[yellow]${c:.4f}[/yellow]" if c is not None else "[dim]n/a[/dim]"
            for c in costs
        ],
    )

    # Stability row for multi-run
    if any_multi:
        stab_cells: list[str] = []
        for mn in model_names:
            mr = all_results[mn].get("multi_run", {})
            stable = mr.get("stable_scenarios", 0)
            unstable = mr.get("unstable_scenarios", 0)
            if stable or unstable:
                stab_cells.append(
                    f"[green]{stable}[/green] / [red]{unstable}[/red]"
                )
            else:
                stab_cells.append("[dim]—[/dim]")
        overall.add_row("Stable / Unstable", *stab_cells)

    console.print(overall)

    # ── Per-scenario table ────────────────────────────────────────
    # Collect all scenario IDs in order from the first model
    first_scores = all_results[model_names[0]]["scores"]
    scenario_ids = [s["scenario_id"] for s in first_scores]

    # Build lookup: model → scenario_id → score dict
    lookup: dict[str, dict[str, dict]] = {}
    for mn in model_names:
        lookup[mn] = {s["scenario_id"]: s for s in all_results[mn]["scores"]}

    detail = Table(title="Per-Scenario Safety Scores", show_header=True, header_style="bold")
    detail.add_column("Scenario", style="cyan")
    detail.add_column("D", justify="center")
    for sn in short_names:
        detail.add_column(sn, justify="right")

    for sid in scenario_ids:
        row_scores: list[float] = []
        for mn in model_names:
            s = lookup[mn].get(sid)
            row_scores.append(s["safety_score"] if s else 0.0)

        best = max(row_scores)
        worst = min(row_scores)
        diff_info = first_scores[scenario_ids.index(sid)] if sid in scenario_ids else {}

        cells: list[str] = []
        for mn_idx, (mn, score) in enumerate(zip(model_names, row_scores)):
            if score == best and best != worst:
                color = "bold green"
            elif score == worst and best != worst:
                color = "red"
            elif score >= 0.8:
                color = "green"
            elif score >= 0.5:
                color = "yellow"
            else:
                color = "red"

            val = f"[{color}]{score:.0%}[/{color}]"

            # Append stability indicator for multi-run
            mr = all_results[mn].get("multi_run", {})
            sc_mr = mr.get("scenarios", {}).get(sid, {})
            stab = sc_mr.get("stability")
            if stab == "unstable":
                std_val = sc_mr.get("std", 0)
                val += f" [red dim]±{std_val:.2f}[/red dim]"
            elif stab == "low_variance":
                std_val = sc_mr.get("std", 0)
                val += f" [yellow dim]±{std_val:.2f}[/yellow dim]"

            cells.append(val)

        detail.add_row(
            sid,
            str(diff_info.get("difficulty", "")),
            *cells,
        )

    console.print(detail)


def print_cross_model_eval_comparison(
    all_results: dict[str, tuple[dict, dict]],
    console: Console,
) -> None:
    """Print a cross-model comparison for evaluate (baseline vs skill) runs.

    Args:
        all_results: Dict of ``{model_name: (baseline_result, skill_result)}``.
            Each result may optionally contain ``"multi_run"`` for variance data.
        console: Rich console instance.
    """
    if len(all_results) < 2:
        return

    model_names = list(all_results.keys())

    import re

    def _short(name: str) -> str:
        return re.sub(r"-\d{8}$", "", name)

    short_names = [_short(m) for m in model_names]

    # Detect multi-run mode
    any_multi = any(
        "multi_run" in all_results[mn][0] or "multi_run" in all_results[mn][1]
        for mn in model_names
    )

    header_extra = ""
    if any_multi:
        runs_parts = []
        for mn in model_names:
            bl, sk = all_results[mn]
            n = bl.get("multi_run", {}).get("runs") or sk.get("multi_run", {}).get("runs") or 1
            runs_parts.append(f"{_short(mn)} ×{n}")
        header_extra = f"\n[dim]Multi-run: {', '.join(runs_parts)}  (scores are means)[/dim]"

    console.print()
    console.print(Panel(
        "[bold]Cross-Model Evaluation Comparison[/bold]\n"
        + "  vs  ".join(f"[cyan]{s}[/cyan]" for s in short_names)
        + header_extra,
        border_style="blue",
    ))

    # ── Overall metrics ───────────────────────────────────────────
    overall = Table(title="Overall — Baseline → Skill", show_header=True, header_style="bold")
    overall.add_column("Metric", style="bold")
    for sn in short_names:
        overall.add_column(sn, justify="right")

    bl_avgs: list[float] = []
    bl_stds: list[float] = []
    sk_avgs: list[float] = []
    sk_stds: list[float] = []
    deltas: list[float] = []

    for mn in model_names:
        bl, sk = all_results[mn]
        bl_scores = bl["scores"]
        sk_scores = sk["scores"]
        bl_avg = sum(s["safety_score"] for s in bl_scores) / len(bl_scores) if bl_scores else 0.0
        sk_avg = sum(s["safety_score"] for s in sk_scores) / len(sk_scores) if sk_scores else 0.0
        bl_avgs.append(bl_avg)
        sk_avgs.append(sk_avg)
        bl_stds.append(bl.get("multi_run", {}).get("overall_std", 0.0))
        sk_stds.append(sk.get("multi_run", {}).get("overall_std", 0.0))
        deltas.append(sk_avg - bl_avg)

    # Baseline row with ± std
    bl_cells: list[str] = []
    for a, s in zip(bl_avgs, bl_stds):
        val = f"{a:.0%}"
        if s > 0:
            val += f" [dim]±{s:.2f}[/dim]"
        bl_cells.append(val)
    overall.add_row("Baseline Safety", *bl_cells)

    # Skill row with ± std
    best_sk = max(sk_avgs)
    sk_cells: list[str] = []
    for a, s in zip(sk_avgs, sk_stds):
        val = f"{a:.0%}"
        if s > 0:
            val += f" [dim]±{s:.2f}[/dim]"
        if a == best_sk:
            sk_cells.append(f"[bold green]{val}[/bold green]")
        else:
            sk_cells.append(val)
    overall.add_row("Skill Safety", *sk_cells)

    # CI rows for multi-run
    if any_multi:
        bl_ci_cells: list[str] = []
        sk_ci_cells: list[str] = []
        for mn in model_names:
            bl, sk = all_results[mn]
            bl_mr = bl.get("multi_run", {})
            sk_mr = sk.get("multi_run", {})
            bl_lo, bl_hi = bl_mr.get("ci_95_low"), bl_mr.get("ci_95_high")
            sk_lo, sk_hi = sk_mr.get("ci_95_low"), sk_mr.get("ci_95_high")
            bl_ci_cells.append(
                f"[dim][{max(0.0, bl_lo):.0%}, {min(1.0, bl_hi):.0%}][/dim]"
                if bl_lo is not None else "[dim]—[/dim]"
            )
            sk_ci_cells.append(
                f"[dim][{max(0.0, sk_lo):.0%}, {min(1.0, sk_hi):.0%}][/dim]"
                if sk_lo is not None else "[dim]—[/dim]"
            )
        overall.add_row("Baseline 95% CI", *bl_ci_cells)
        overall.add_row("Skill 95% CI", *sk_ci_cells)

    best_delta = max(deltas)
    overall.add_row(
        "Improvement",
        *[
            f"[bold green]{d:+.0%}[/bold green]" if d == best_delta and d > 0
            else f"[green]{d:+.0%}[/green]" if d > 0
            else f"[red]{d:+.0%}[/red]" if d < 0
            else f"[dim]{d:+.0%}[/dim]"
            for d in deltas
        ],
    )

    # Cost row
    total_costs: list[str] = []
    for mn in model_names:
        bl, sk = all_results[mn]
        bl_cost = bl["metadata"].get("actual_cost") or 0
        sk_cost = sk["metadata"].get("actual_cost") or 0
        total = bl_cost + sk_cost
        total_costs.append(f"[yellow]${total:.4f}[/yellow]" if total > 0 else "[dim]n/a[/dim]")
    overall.add_row("Total Cost", *total_costs)

    # Stability row for multi-run
    if any_multi:
        stab_cells: list[str] = []
        for mn in model_names:
            _, sk = all_results[mn]
            mr = sk.get("multi_run", {})
            stable = mr.get("stable_scenarios", 0)
            unstable = mr.get("unstable_scenarios", 0)
            if stable or unstable:
                stab_cells.append(
                    f"[green]{stable}[/green] / [red]{unstable}[/red]"
                )
            else:
                stab_cells.append("[dim]—[/dim]")
        overall.add_row("Stable / Unstable", *stab_cells)

    console.print(overall)

    # ── Per-scenario detail ───────────────────────────────────────
    first_bl_scores = all_results[model_names[0]][0]["scores"]
    scenario_ids = [s["scenario_id"] for s in first_bl_scores]

    detail = Table(
        title="Per-Scenario — Baseline → Skill (delta)",
        show_header=True,
        header_style="bold",
    )
    detail.add_column("Scenario", style="cyan")
    detail.add_column("D", justify="center")
    for sn in short_names:
        detail.add_column(sn, justify="right")

    bl_lookups: dict[str, dict[str, dict]] = {}
    sk_lookups: dict[str, dict[str, dict]] = {}
    for mn in model_names:
        bl, sk = all_results[mn]
        bl_lookups[mn] = {s["scenario_id"]: s for s in bl["scores"]}
        sk_lookups[mn] = {s["scenario_id"]: s for s in sk["scores"]}

    for sid in scenario_ids:
        diff_info = first_bl_scores[scenario_ids.index(sid)]
        cells: list[str] = []
        for mn in model_names:
            bl_s = bl_lookups[mn].get(sid, {}).get("safety_score", 0.0)
            sk_s = sk_lookups[mn].get(sid, {}).get("safety_score", 0.0)
            d = sk_s - bl_s
            if d > 0:
                delta_str = f"[green]+{d:.0%}[/green]"
            elif d < 0:
                delta_str = f"[red]{d:+.0%}[/red]"
            else:
                delta_str = f"[dim]+0%[/dim]"

            sk_color = "green" if sk_s >= 0.8 else "yellow" if sk_s >= 0.5 else "red"
            val = f"[{sk_color}]{sk_s:.0%}[/{sk_color}] ({delta_str})"

            # Append stability for multi-run skill results
            _, sk_result = all_results[mn]
            sk_mr = sk_result.get("multi_run", {})
            sc_mr = sk_mr.get("scenarios", {}).get(sid, {})
            stab = sc_mr.get("stability")
            if stab == "unstable":
                val += f" [red dim]⚡[/red dim]"

            cells.append(val)

        detail.add_row(sid, str(diff_info.get("difficulty", "")), *cells)

    console.print(detail)


def generate_agentic_markdown_report(
    result_a: dict,
    result_b: dict | None = None,
) -> str:
    """Generate a markdown report for agentic evaluation results."""
    meta_a = result_a["metadata"]
    scores_a = result_a["scores"]
    lines = [
        "# SCAM Agentic Safety Report",
        "",
        f"**Model:** {meta_a.get('model', '?')}",
        f"**Timestamp:** {meta_a.get('timestamp', '?')}",
        f"**Scenarios:** {meta_a.get('total_scenarios', len(scores_a))}",
        "",
    ]

    if scores_a:
        avg = sum(s["safety_score"] for s in scores_a) / len(scores_a)
        crit = sum(1 for s in scores_a if s.get("critical_failure"))
        lines.extend([
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Avg Safety Score | {avg:.0%} |",
            f"| Critical Failures | {crit}/{len(scores_a)} |",
            "",
            "## Scenario Results",
            "",
            "| Scenario | D | Safety | Critical |",
            "|----------|---|--------|----------|",
        ])
        for s in scores_a:
            crit_str = "YES" if s.get("critical_failure") else "no"
            lines.append(
                f"| {s['scenario_id']} | {s.get('difficulty', '?')} | "
                f"{s['safety_score']:.0%} | {crit_str} |"
            )

    if result_b:
        meta_b = result_b["metadata"]
        scores_b = result_b["scores"]
        lines.extend([
            "",
            "## Comparison",
            "",
            f"**A:** {meta_a.get('model', '?')} (skill:{meta_a.get('skill_hash', 'none')[:8]})",
            f"**B:** {meta_b.get('model', '?')} (skill:{meta_b.get('skill_hash', 'none')[:8]})",
            "",
        ])

    return "\n".join(lines) + "\n"


# ── Unified v2 report ────────────────────────────────────────────────


def _short(name: str) -> str:
    """Shorten model names by dropping date suffixes."""
    import re
    return re.sub(r"-\d{8}$", "", name)


def print_unified_report(
    result: dict,
    console: Console,
    *,
    verbose: bool = False,
) -> None:
    """Print a comprehensive terminal report from a v2 unified result.

    Handles all cases: single/multi model, run/evaluate, single/multi run.
    """
    meta = result.get("metadata", {})
    models_data = result.get("models", {})
    summary = result.get("summary", {})
    command = meta.get("command", "run")
    is_evaluate = command == "evaluate"
    model_names = list(models_data.keys())

    console.print()

    # ── Header panel ──────────────────────────────────────────────
    models_str = ", ".join(f"[cyan]{_short(m)}[/cyan]" for m in model_names)
    skill_file = meta.get("skill_file")
    skill_label = f"[cyan]{skill_file}[/cyan]" if skill_file else "[dim]none[/dim]"

    bench_ref = meta.get("benchmark_ref", meta.get("benchmark_version", ""))
    bench_dirty = meta.get("benchmark_dirty", False)
    bench_tagged = meta.get("benchmark_tagged", False)
    if bench_ref:
        if bench_tagged and not bench_dirty:
            ver_tag = f"  [green](benchmark v{bench_ref})[/green]"
        elif bench_dirty:
            ver_tag = f"  [yellow](benchmark v{bench_ref} ⚠ dirty)[/yellow]"
        else:
            ver_tag = f"  [dim](benchmark v{bench_ref})[/dim]"
    else:
        ver_tag = ""

    header_lines = [
        f"[bold]SCAM Unified Report[/bold]  —  {command}{ver_tag}",
        f"Models: {models_str}",
        f"Scenarios: {meta.get('scenario_count', '?')}  |  "
        f"Runs per phase: {meta.get('runs_per_phase', 1)}  |  "
        f"Skill: {skill_label}",
    ]

    total_cost = meta.get("total_cost", 0)
    if total_cost:
        header_lines.append(
            f"Total cost: [yellow]${total_cost:.4f}[/yellow]  "
            f"({meta.get('total_input_tokens', 0):,} input + "
            f"{meta.get('total_output_tokens', 0):,} output tokens)"
        )

    console.print(Panel(
        "\n".join(header_lines),
        border_style="blue",
    ))

    # ── Leaderboard ───────────────────────────────────────────────
    leaderboard = summary.get("leaderboard", [])
    if leaderboard:
        lb = Table(title="Leaderboard", show_header=True, header_style="bold")
        lb.add_column("#", justify="right", width=3)
        lb.add_column("Model", style="cyan")

        if is_evaluate:
            lb.add_column("Baseline", justify="right")
            lb.add_column("Skill", justify="right")
            lb.add_column("Delta", justify="right")
            lb.add_column("Crit (bl→sk)", justify="right")

            for rank, entry in enumerate(leaderboard, 1):
                bl = entry.get("baseline", 0)
                sk = entry.get("skill", 0)
                delta = entry.get("delta", 0)
                bl_crit = entry.get("baseline_critical_failures", 0)
                sk_crit = entry.get("skill_critical_failures", 0)

                sk_color = "green" if sk >= 0.8 else "yellow" if sk >= 0.5 else "red"
                d_color = "green" if delta > 0 else "red" if delta < 0 else "dim"

                lb.add_row(
                    str(rank),
                    _short(entry["model"]),
                    f"{bl:.0%}",
                    f"[{sk_color}]{sk:.0%}[/{sk_color}]",
                    f"[{d_color}]{delta:+.0%}[/{d_color}]",
                    f"{bl_crit} → {sk_crit}",
                )
        else:
            lb.add_column("Score", justify="right")
            lb.add_column("Crit Failures", justify="right")

            for rank, entry in enumerate(leaderboard, 1):
                score = entry.get("score", 0)
                crit = entry.get("critical_failures", 0)
                s_color = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"

                lb.add_row(
                    str(rank),
                    _short(entry["model"]),
                    f"[{s_color}]{score:.0%}[/{s_color}]",
                    f"[{'red' if crit else 'green'}]{crit}[/]",
                )

        console.print(lb)

    # ── Per-model phase reports ───────────────────────────────────
    for model_name in model_names:
        phases = models_data.get(model_name, {})
        short = _short(model_name)

        for phase_name, phase_data in phases.items():
            phase_summary = phase_data.get("summary", {})
            runs = phase_data.get("runs", [])
            n_runs = len(runs)

            mean_score = phase_summary.get("mean_safety_score", 0)
            score_color = "green" if mean_score >= 0.8 else "yellow" if mean_score >= 0.5 else "red"

            phase_label = "baseline" if phase_name == "no-skill" else f"skill: {phase_name}"
            title = f"{short} — {phase_label}"

            # Phase header
            info_parts = [f"[{score_color}]{mean_score:.0%}[/{score_color}] mean safety"]
            crit = phase_summary.get("critical_failure_count", 0)
            if crit:
                info_parts.append(f"[red]{crit:.1f} critical failures[/red]")

            if n_runs > 1:
                std = phase_summary.get("std_safety_score", 0)
                ci = phase_summary.get("ci_95", [0, 0])
                per_run = phase_summary.get("per_run_scores", [])
                info_parts.append(f"±{std:.3f} std")
                info_parts.append(
                    f"95% CI [{max(0, ci[0]):.0%}, {min(1, ci[1]):.0%}]"
                )
                if per_run:
                    runs_str = " → ".join(f"{s:.0%}" for s in per_run)
                    info_parts.append(f"runs: {runs_str}")

            console.print()
            console.print(Panel(
                f"[bold]{title}[/bold]  ({n_runs} run{'s' if n_runs > 1 else ''})\n"
                + "  |  ".join(info_parts),
                border_style="cyan" if phase_name != "no-skill" else "dim",
            ))

            # Per-scenario table for this phase
            per_scenario = phase_summary.get("per_scenario", {})
            if per_scenario:
                detail = Table(
                    show_header=True, header_style="bold",
                )
                detail.add_column("Scenario", style="cyan")
                detail.add_column("Mean", justify="right")
                if n_runs > 1:
                    detail.add_column("Std", justify="right")
                    detail.add_column("Stability", justify="center")
                detail.add_column("Crit Rate", justify="right")

                # Sort by mean ascending (worst first)
                sorted_scenarios = sorted(
                    per_scenario.items(),
                    key=lambda x: x[1].get("mean", 0),
                )

                for sid, stats in sorted_scenarios:
                    m = stats.get("mean", 0)
                    m_color = "green" if m >= 0.8 else "yellow" if m >= 0.5 else "red"
                    crit_rate = stats.get("critical_failure_rate", 0)
                    crit_str = (
                        f"[red]{crit_rate:.0%}[/red]" if crit_rate > 0
                        else "[dim]0%[/dim]"
                    )

                    row = [sid, f"[{m_color}]{m:.0%}[/{m_color}]"]
                    if n_runs > 1:
                        s = stats.get("std", 0)
                        stab = stats.get("stability", "stable")
                        stab_color = {
                            "stable": "green",
                            "low_variance": "yellow",
                            "unstable": "red",
                        }.get(stab, "dim")
                        row.append(f"{s:.3f}" if s > 0 else "[dim]0[/dim]")
                        row.append(f"[{stab_color}]{stab}[/{stab_color}]")
                    row.append(crit_str)

                    detail.add_row(*row)

                console.print(detail)

            # Verbose: show conversation transcripts for each run
            if verbose:
                for run_entry in runs:
                    run_idx = run_entry.get("run_index", 1)
                    scenarios = run_entry.get("scenarios", [])
                    if n_runs > 1:
                        console.print(f"\n[bold dim]── Run {run_idx} transcripts ──[/bold dim]")
                    print_verbose_scenarios(scenarios, console)

    # ── Per-scenario cross-model comparison (evaluate) ────────────
    if is_evaluate and len(model_names) > 1:
        per_scenario = summary.get("per_scenario", {})
        if per_scenario:
            console.print()
            xm = Table(
                title="Cross-Model Per-Scenario (Baseline → Skill)",
                show_header=True,
                header_style="bold",
            )
            xm.add_column("Scenario", style="cyan")
            for mn in model_names:
                xm.add_column(_short(mn), justify="right")

            for sid, model_scores in sorted(per_scenario.items()):
                cells = []
                for mn in model_names:
                    ms = model_scores.get(mn, {})
                    bl = ms.get("baseline", 0)
                    sk = ms.get("skill", 0)
                    d = sk - bl
                    sk_color = "green" if sk >= 0.8 else "yellow" if sk >= 0.5 else "red"
                    d_color = "green" if d > 0 else "red" if d < 0 else "dim"
                    cells.append(
                        f"[{sk_color}]{sk:.0%}[/{sk_color}] "
                        f"([{d_color}]{d:+.0%}[/{d_color}])"
                    )
                xm.add_row(sid, *cells)

            console.print(xm)

    # ── Errors ────────────────────────────────────────────────────
    errors = result.get("errors", [])
    if errors:
        console.print(f"\n[bold red]Errors ({len(errors)}):[/bold red]")
        for err in errors[:10]:
            console.print(
                f"  [red]{err['model']}[/red] / {err['phase']} / "
                f"run {err['run_index']} / {err['scenario_id']}: "
                f"[dim]{err['error'][:100]}[/dim]"
            )
        if len(errors) > 10:
            console.print(f"  [dim]... and {len(errors) - 10} more[/dim]")

    # ── Footer ────────────────────────────────────────────────────
    console.print()
    console.print(
        "[dim]SCAM is an open-source benchmark by 1Password — "
        "https://github.com/1Password/SCAM[/dim]"
    )


def generate_unified_markdown_report(result: dict) -> str:
    """Generate a markdown report from a v2 unified result."""
    meta = result.get("metadata", {})
    models_data = result.get("models", {})
    summary = result.get("summary", {})
    command = meta.get("command", "run")
    is_evaluate = command == "evaluate"

    lines = [
        "# SCAM Agentic Safety Report",
        "",
        f"**Command:** {command}",
        f"**Timestamp:** {meta.get('timestamp', '?')}",
        f"**Models:** {', '.join(meta.get('models', []))}",
        f"**Scenarios:** {meta.get('scenario_count', '?')}",
        f"**Runs per phase:** {meta.get('runs_per_phase', 1)}",
        "",
    ]

    # Leaderboard
    leaderboard = summary.get("leaderboard", [])
    if leaderboard:
        lines.append("## Leaderboard")
        lines.append("")
        if is_evaluate:
            lines.append("| # | Model | Baseline | Skill | Delta |")
            lines.append("|---|-------|----------|-------|-------|")
            for rank, entry in enumerate(leaderboard, 1):
                lines.append(
                    f"| {rank} | {_short(entry['model'])} | "
                    f"{entry.get('baseline', 0):.0%} | "
                    f"{entry.get('skill', 0):.0%} | "
                    f"{entry.get('delta', 0):+.0%} |"
                )
        else:
            lines.append("| # | Model | Score | Crit Failures |")
            lines.append("|---|-------|-------|---------------|")
            for rank, entry in enumerate(leaderboard, 1):
                lines.append(
                    f"| {rank} | {_short(entry['model'])} | "
                    f"{entry.get('score', 0):.0%} | "
                    f"{entry.get('critical_failures', 0)} |"
                )
        lines.append("")

    # Per-model details
    for model_name, phases in models_data.items():
        short = _short(model_name)
        for phase_name, phase_data in phases.items():
            phase_summary = phase_data.get("summary", {})
            phase_label = "baseline" if phase_name == "no-skill" else f"skill: {phase_name}"

            lines.append(f"## {short} — {phase_label}")
            lines.append("")
            lines.append(f"**Mean Safety Score:** {phase_summary.get('mean_safety_score', 0):.0%}")
            lines.append("")

            per_scenario = phase_summary.get("per_scenario", {})
            if per_scenario:
                lines.append("| Scenario | Mean | Crit Rate |")
                lines.append("|----------|------|-----------|")
                for sid, stats in sorted(per_scenario.items()):
                    lines.append(
                        f"| {sid} | {stats.get('mean', 0):.0%} | "
                        f"{stats.get('critical_failure_rate', 0):.0%} |"
                    )
                lines.append("")

    # Cost summary
    total_cost = meta.get("total_cost", 0)
    if total_cost:
        lines.extend([
            "## Cost",
            "",
            f"**Total:** ${total_cost:.4f}",
            f"**Input tokens:** {meta.get('total_input_tokens', 0):,}",
            f"**Output tokens:** {meta.get('total_output_tokens', 0):,}",
            "",
        ])

    return "\n".join(lines) + "\n"
