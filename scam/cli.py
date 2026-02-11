"""CLI entrypoint for SCAM benchmark."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scam.models.discovery import interactive_model_select, is_interactive_model_arg
from scam.utils.config import (
    AGENTIC_RESULTS_DIR,
    AGENTIC_SCENARIOS_DIR,
    RESULTS_DIR,
    SKILLS_DIR,
    estimate_agentic_cost,
    skill_hash as compute_skill_hash,
)

logger = logging.getLogger("scam")

console = Console()


# ── Shared helpers ────────────────────────────────────────────────────


def _resolve_model_names(
    model: str | None,
    interactive: bool,
    ctx: typer.Context,
) -> tuple[list[str], bool]:
    """Shared model name resolution for all run commands.

    Handles interactive selection, provider shorthand, and comma-separated
    model lists.  Exits with help if no model is specified.

    Returns ``(model_names, was_interactive)``.
    """
    if interactive:
        _, providers = is_interactive_model_arg(model)
        return interactive_model_select(providers=providers, console=console), True
    if model is not None:
        is_provider, providers = is_interactive_model_arg(model)
        if is_provider:
            return interactive_model_select(providers=providers, console=console), True
        return [m.strip() for m in model.split(",")], False
    # No --model and no --interactive → show help
    console.print(ctx.get_help())
    raise typer.Exit(0)


def _print_rerun_command(
    subcommand: str,
    model_names: list[str],
    *,
    skill: Path | None = None,
    judge_model: str | None = None,
    no_judge: bool = False,
    categories: str | None = None,
    difficulty: str | None = None,
    concurrency: int | None = None,
    delay: float | None = None,
    runs: int = 1,
    verbose: bool = False,
    parallel: int = 1,
) -> None:
    """Print the equivalent non-interactive CLI command for easy re-runs."""
    parts = ["scam", subcommand, "--model", ",".join(model_names)]
    if skill:
        parts.extend(["--skill", str(skill)])
    if no_judge:
        parts.append("--no-judge")
    elif judge_model and judge_model != "gpt-4o-mini":
        parts.extend(["--judge-model", judge_model])
    if categories:
        parts.extend(["--categories", categories])
    if difficulty:
        parts.extend(["--difficulty", difficulty])
    if concurrency is not None and concurrency != 3:
        parts.extend(["--concurrency", str(concurrency)])
    if delay is not None and delay != 0.5:
        parts.extend(["--delay", str(delay)])
    if runs > 1:
        parts.extend(["--runs", str(runs)])
    if verbose:
        parts.append("--verbose")
    if parallel > 1:
        parts.extend(["--parallel", str(parallel)])
    parts.append("--yes")

    console.print(f"\n[dim]Re-run:[/dim]  [bold]{' '.join(parts)}[/bold]")


def _write_error_log(result: dict, log_path: Path) -> None:
    """Write a human-readable error log when a run has failures."""
    errors = result.get("errors", [])
    meta = result.get("metadata", {})
    if not errors:
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "SCAM Error Log",
        "==============",
        f"Model:     {meta.get('model', 'unknown')}",
        f"Timestamp: {meta.get('timestamp', 'unknown')}",
        f"Skill:     {meta.get('skill_hash', 'none')}",
        f"Total:     {meta.get('total_scenarios', '?')}",
        f"Completed: {meta.get('completed_scenarios', '?')}",
        f"Errored:   {meta.get('errored_scenarios', '?')}",
        "",
        f"Errors ({len(errors)}):",
        "-" * 60,
    ]
    for err in errors:
        lines.append(f"  Scenario: {err.get('scenario_id', 'unknown')}")
        lines.append(f"  Time:     {err.get('timestamp', 'unknown')}")
        lines.append(f"  Error:    {err.get('error', '(no error message)')}")
        raw = err.get("raw_response", "")
        if raw:
            preview = raw[:800]
            if len(raw) > 800:
                preview += "... [truncated]"
            lines.append(f"  Raw response:")
            for rline in preview.splitlines():
                lines.append(f"    | {rline}")
        lines.append("")

    log_path.write_text("\n".join(lines) + "\n")


# ── Display helpers ───────────────────────────────────────────────────


def _short_name(name: str) -> str:
    """Shorten model names for display — drop date suffixes."""
    import re

    return re.sub(r"-\d{8}$", "", name)


def _scenario_summary(scenarios) -> str:
    """One-line summary of scenario counts by category."""
    from collections import Counter

    cats = Counter(s.category for s in scenarios)
    parts = []
    for cat, count in sorted(cats.items()):
        # Strip 'agentic_' prefix, replace underscores with spaces
        label = cat.removeprefix("agentic_").replace("_", " ")
        parts.append(f"{count} {label}")
    return f"{len(scenarios)} scenarios ({', '.join(parts)})"


def _build_config_panel(
    *,
    mode: str,
    model_names: list[str],
    scenario_summary: str,
    skill_label: str | None = None,
    judge_model: str | None = None,
    parallel: int = 1,
    runs: int = 1,
    cost_estimates: list[tuple[str, float | None]] | None = None,
) -> Panel:
    """Build a compact configuration summary panel."""
    short_names = [_short_name(mn) for mn in model_names]

    lines = [
        "[bold]Benchmark Configuration[/bold]",
        "",
        f"  [dim]Mode[/dim]       {mode}",
        f"  [dim]Models[/dim]     {', '.join(f'[cyan]{s}[/cyan]' for s in short_names)}",
        f"  [dim]Scenarios[/dim]  {scenario_summary}",
    ]
    if skill_label:
        lines.append(f"  [dim]Skill[/dim]      {skill_label}")
    if judge_model:
        lines.append(f"  [dim]Judge[/dim]      [cyan]{judge_model}[/cyan]")
    else:
        lines.append("  [dim]Judge[/dim]      [dim]disabled (--no-judge)[/dim]")
    if parallel > 1:
        lines.append(f"  [dim]Parallel[/dim]   {parallel}")
    if runs > 1:
        lines.append(f"  [dim]Runs[/dim]       {runs} per phase")

    if cost_estimates:
        total = 0.0
        cost_lines: list[str] = []
        for sn, est in cost_estimates:
            if est is not None:
                cost_lines.append(f"    {sn:<26s} [yellow]~${est:.2f}[/yellow]")
                total += est
        if cost_lines:
            lines.append("")
            lines.append("  [dim]Estimated cost[/dim]")
            lines.extend(cost_lines)
            if len(cost_lines) > 1:
                lines.append(f"    {'Total':<26s} [yellow bold]~${total:.2f}[/yellow bold]")

    return Panel("\n".join(lines), border_style="blue")


def _print_result_paths(
    all_paths: dict[str, list],
    console: Console,
) -> None:
    """Print all result file paths grouped by model."""
    if not all_paths:
        return
    console.print("\n[bold]Results saved:[/bold]")
    for mn, paths in all_paths.items():
        if paths:
            console.print(f"  [cyan]{_short_name(mn)}[/cyan]")
            for p in paths:
                console.print(f"    [green]{p}[/green]")


def _offer_html_export(
    result: dict,
    result_path: Path,
    console: Console,
    *,
    yes: bool = False,
) -> None:
    """After a run/eval, offer to export an HTML dashboard."""
    if yes:
        return

    console.print()
    raw = console.input("[bold]Export HTML dashboard? [y/N]> [/bold]").strip().lower()
    if raw not in ("y", "yes"):
        return

    from scam.agentic.export_html import export_result

    # Build a named export folder matching the result filename
    # e.g. results/agentic/scam-evaluate-1738944000.json → exports/scam-evaluate-1738944000/
    stem = result_path.stem  # "scam-evaluate-1738944000"
    export_dir = Path("exports") / stem

    try:
        written = export_result(result, export_dir)
        console.print(f"\n[bold green]Exported {len(written)} file(s):[/bold green]")
        for p in written:
            console.print(f"  [green]{p}[/green]")
        console.print()
    except Exception as e:
        console.print(f"[red]Export failed: {e}[/red]")


# ── Interactive wizard ────────────────────────────────────────────────


def _interactive_wizard(ctx: typer.Context) -> None:
    """Full interactive wizard invoked by ``scam -i``.

    Walks the user through model selection, mode (run vs evaluate),
    skill choice, and parallelization — then invokes the appropriate
    command with the resolved parameters.
    """
    from scam.models.discovery import interactive_model_select
    from scam.utils.config import SKILLS_DIR

    console.print(
        Panel(
            "[bold]SCAM — Interactive Benchmark Wizard[/bold]\n\n"
            "Configure and launch a benchmark in a few steps.",
            border_style="cyan",
        )
    )

    # ── Step 1: Mode ──────────────────────────────────────────────
    console.print("[bold]Step 1:[/bold] What would you like to do?\n")
    console.print("  [green]1[/green]  Run        — Single benchmark (with optional skill)")
    console.print("  [green]2[/green]  Evaluate   — Baseline vs skill comparison\n")

    mode_raw = console.input("[bold]Mode [1]> [/bold]").strip()
    mode = "evaluate" if mode_raw == "2" else "run"
    console.print()

    # ── Step 2: Models ────────────────────────────────────────────
    console.print("[bold]Step 2:[/bold] Select models\n")
    model_names = interactive_model_select(console=console)

    # ── Step 3: Skill (run mode only) ─────────────────────────────
    skill_path: Path | None = None
    if mode == "run":
        # Discover available skill files
        skill_files = sorted(SKILLS_DIR.glob("*.md"))
        # Filter out baseline.md — that's for the evaluate command
        skill_files = [f for f in skill_files if f.name != "baseline.md"]

        console.print("[bold]Step 3:[/bold] Use a skill file?\n")
        console.print("  [green]1[/green]  No skill (baseline behavior)")
        for idx, sf in enumerate(skill_files, 2):
            console.print(f"  [green]{idx}[/green]  {sf.name}")
        console.print()

        skill_raw = console.input("[bold]Skill [1]> [/bold]").strip()
        try:
            skill_idx = int(skill_raw) if skill_raw else 1
        except ValueError:
            skill_idx = 1

        if skill_idx >= 2 and skill_idx <= len(skill_files) + 1:
            skill_path = skill_files[skill_idx - 2]
            console.print(f"  Using skill: [cyan]{skill_path.name}[/cyan]\n")
        else:
            console.print("  No skill selected.\n")
    else:
        console.print(
            "[bold]Step 3:[/bold] Evaluate will compare [dim]no-skill[/dim] "
            "vs [cyan]security_expert.md[/cyan] automatically.\n"
        )

    # ── Step 4: Parallelization ───────────────────────────────────
    recommended = min(len(model_names), 3)
    console.print("[bold]Step 4:[/bold] Parallelization\n")
    console.print(
        f"  You selected {len(model_names)} model(s). "
        f"Recommended: run [cyan]{recommended}[/cyan] in parallel."
    )
    console.print(
        "  Each model runs its scenarios concurrently (--concurrency 3).\n"
    )

    parallel_raw = console.input(
        f"[bold]Parallel models [{recommended}]> [/bold]"
    ).strip()
    try:
        parallel = int(parallel_raw) if parallel_raw else recommended
        parallel = max(1, parallel)
    except ValueError:
        parallel = recommended

    console.print()

    # ── Step 5: Runs ──────────────────────────────────────────────
    console.print("[bold]Step 5:[/bold] Number of runs\n")
    console.print(
        "  Multiple runs reduce variance from LLM non-determinism."
    )
    console.print(
        "  Results are aggregated with mean, std, and 95% CI.\n"
    )

    runs_raw = console.input("[bold]Runs per model [1]> [/bold]").strip()
    try:
        num_runs = int(runs_raw) if runs_raw else 1
        num_runs = max(1, num_runs)
    except ValueError:
        num_runs = 1

    console.print()

    # ── Build re-run command & confirm ────────────────────────────
    model_str = ",".join(model_names)
    _print_rerun_command(
        mode,
        model_names,
        skill=skill_path,
        parallel=parallel,
        runs=num_runs,
    )

    # ── Invoke ────────────────────────────────────────────────────
    if mode == "run":
        ctx.invoke(
            run,
            ctx=ctx,
            model=model_str,
            interactive=False,
            skill=skill_path,
            output=None,
            categories=None,
            difficulty=None,
            concurrency=3,
            delay=0.5,
            yes=False,
            parallel=parallel,
            verbose=False,
            judge_model="gpt-4o-mini",
            no_judge=False,
            runs=num_runs,
        )
    else:
        ctx.invoke(
            evaluate,
            ctx=ctx,
            model=model_str,
            interactive=False,
            skill=None,
            output=None,
            report_path=None,
            categories=None,
            difficulty=None,
            concurrency=3,
            delay=0.5,
            yes=False,
            parallel=parallel,
            verbose=False,
            judge_model="gpt-4o-mini",
            no_judge=False,
            runs=num_runs,
        )


# ── Typer app ─────────────────────────────────────────────────────────


app = typer.Typer(
    name="scam",
    help=(
        "SCAM — Security Comprehension Awareness Measure.\n\n"
        "Test whether AI agents leak credentials, fall for phishing, "
        "and protect users — before users find out they don't.\n\n"
        "An open-source benchmark by 1Password. "
        "https://github.com/1Password/SCAM"
    ),
    add_completion=False,
    invoke_without_command=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    interactive: bool = typer.Option(
        False,
        "--interactive", "-i",
        help="Launch interactive wizard to configure and run a benchmark.",
    ),
) -> None:
    """SCAM — Security Comprehension Awareness Measure."""
    if ctx.invoked_subcommand is not None:
        return  # Normal subcommand routing — do nothing in callback.

    if not interactive:
        console.print(ctx.get_help())
        raise typer.Exit(0)

    # ── Interactive wizard ────────────────────────────────────────
    _interactive_wizard(ctx)


# ── Agentic: run (default) ───────────────────────────────────────────


@app.command()
def run(
    ctx: typer.Context,
    model: str = typer.Option(
        None,
        "--model", "-m",
        help="Model name(s), comma-separated. E.g. gpt-5.1,gpt-4o.",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive", "-i",
        help="Interactively select models from available provider APIs.",
    ),
    skill: Path = typer.Option(
        None,
        "--skill", "-s",
        help="Path to skill file (.md) to use as system prompt.",
        exists=True,
    ),
    output: Path = typer.Option(
        None,
        "--output", "-o",
        help="Output directory for results. Defaults to results/agentic/.",
    ),
    categories: str = typer.Option(
        None,
        "--categories", "-c",
        help="Comma-separated list of categories to include.",
    ),
    difficulty: str = typer.Option(
        None,
        "--difficulty", "-d",
        help="Comma-separated list of difficulty levels (1-5).",
    ),
    concurrency: int = typer.Option(
        3,
        "--concurrency", "-n",
        help="Max concurrent scenario evaluations.",
    ),
    delay: float = typer.Option(
        0.5,
        "--delay",
        help="Delay between scenario starts in seconds.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes", "-y",
        help="Skip confirmation prompt.",
    ),
    parallel: int = typer.Option(
        1,
        "--parallel", "-j",
        help="Run this many models in parallel (default: 1 = sequential).",
        min=1,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Print full conversation transcripts and tool call details for each scenario.",
    ),
    judge_model: str = typer.Option(
        "gpt-4o-mini",
        "--judge-model",
        help=(
            "Model to use as LLM judge for ambiguous evaluations. "
            "Text-based checkpoints that fail regex matching "
            "are re-evaluated by this model (~$0.005 per run). "
            "Default: gpt-4o-mini."
        ),
    ),
    no_judge: bool = typer.Option(
        False,
        "--no-judge",
        help="Disable the LLM judge. Regex-only evaluation (faster but less accurate).",
    ),
    runs: int = typer.Option(
        1,
        "--runs", "-r",
        help="Number of times to run the benchmark. Results stored per-run for variance analysis.",
        min=1,
    ),
) -> None:
    """Run agentic safety evaluation — multi-turn scenarios with tool use."""
    from scam.agentic.scenario import load_agentic_scenarios
    from scam.agentic.runner import run_agentic_benchmark
    from scam.agentic.results import build_unified_result, save_result
    from scam.agentic.reporting import print_unified_report

    if no_judge:
        judge_model = None

    model_names, was_interactive = _resolve_model_names(model, interactive, ctx)

    if was_interactive:
        _print_rerun_command(
            "run", model_names,
            skill=skill, judge_model=judge_model, no_judge=no_judge,
            categories=categories, difficulty=difficulty,
            concurrency=concurrency, delay=delay, runs=runs,
            verbose=verbose, parallel=parallel,
        )

    # Load agentic scenarios
    all_scenarios = load_agentic_scenarios()
    if not all_scenarios:
        console.print("[yellow]No agentic scenarios found.[/yellow]")
        raise typer.Exit(1)

    # Apply category/difficulty filters
    cat_filter = {c.strip() for c in categories.split(",")} if categories else None
    diff_filter = {int(d.strip()) for d in difficulty.split(",")} if difficulty else None

    filtered = all_scenarios
    if cat_filter:
        filtered = [s for s in filtered if s.category in cat_filter]
    if diff_filter:
        filtered = [s for s in filtered if s.difficulty in diff_filter]

    if not filtered:
        console.print("[yellow]No agentic scenarios match the given filters.[/yellow]")
        raise typer.Exit(1)

    # Load skill content
    skill_content = None
    if skill:
        skill_content = skill.read_text()

    phase_name = skill.stem if skill else "no-skill"

    # ── Configuration summary ─────────────────────────────────────
    cost_estimates = []
    total_estimated = 0.0
    for mn in model_names:
        est = estimate_agentic_cost(mn, len(filtered), num_runs=runs)
        cost_estimates.append((_short_name(mn), est))
        if est is not None:
            total_estimated += est

    skill_label = f"[cyan]{skill.name}[/cyan]" if skill else "[dim]none (baseline)[/dim]"

    console.print()
    console.print(_build_config_panel(
        mode="[cyan]Run[/cyan]",
        model_names=model_names,
        scenario_summary=_scenario_summary(filtered),
        skill_label=skill_label,
        judge_model=judge_model,
        parallel=parallel,
        runs=runs,
        cost_estimates=cost_estimates,
    ))

    if not yes:
        proceed = typer.confirm("Proceed?")
        if not proceed:
            raise typer.Exit(0)

    # ── Execute all runs ──────────────────────────────────────────
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    shared_progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
    )

    # collected_data: {model_name: {phase_name: [run_results]}}
    collected_data: dict[str, dict[str, list[dict]]] = {}
    is_multi_model = len(model_names) > 1

    async def _run_model(mn: str) -> None:
        short = _short_name(mn)

        async def _do_run(idx: int) -> dict:
            if runs > 1:
                desc = f"{short} · run {idx}/{runs}"
            else:
                desc = short if is_multi_model else None
            return await run_agentic_benchmark(
                model_name=mn,
                scenarios=filtered,
                skill_content=skill_content,
                concurrency=concurrency,
                delay=delay,
                judge_model=judge_model,
                progress=shared_progress,
                task_description=desc,
            )

        run_results = await asyncio.gather(
            *[_do_run(i) for i in range(1, runs + 1)]
        )
        collected_data[mn] = {phase_name: list(run_results)}

    async def _run_all() -> None:
        sem = asyncio.Semaphore(parallel)

        async def _guarded(mn: str) -> None:
            async with sem:
                await _run_model(mn)

        await asyncio.gather(*[_guarded(mn) for mn in model_names])

    with shared_progress:
        asyncio.run(_run_all())

    # ── Build unified result ──────────────────────────────────────
    skill_hash_val = compute_skill_hash(skill_content) if skill_content else None

    # Compute per-scenario content hashes for reproducibility
    from scam.utils.config import agentic_scenario_hash
    scenario_hashes: dict[str, str] = {}
    for sc in filtered:
        if sc.source_file:
            scenario_hashes[sc.id] = agentic_scenario_hash(sc.source_file)

    unified = build_unified_result(
        command="run",
        collected_data=collected_data,
        skill_file=skill.name if skill else None,
        skill_hash=skill_hash_val,
        skill_text=skill_content,
        judge_model=judge_model,
        scenario_count=len(filtered),
        categories_filter=categories,
        difficulty_filter=difficulty,
        scenario_hashes=scenario_hashes,
    )

    # ── Save single result file ───────────────────────────────────
    result_path = save_result(unified, output)

    # ── Report ────────────────────────────────────────────────────
    print_unified_report(unified, console, verbose=verbose)
    console.print(f"\nResults saved to [green]{result_path}[/green]")

    # ── Offer HTML export ─────────────────────────────────────────
    _offer_html_export(unified, result_path, console, yes=yes)


# ── Agentic: evaluate (default) ──────────────────────────────────────


@app.command()
def evaluate(
    ctx: typer.Context,
    model: str = typer.Option(
        None,
        "--model", "-m",
        help="Model name(s), comma-separated. E.g. gpt-5.1,gpt-4o.",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive", "-i",
        help="Interactively select models from available provider APIs.",
    ),
    skill: Path = typer.Option(
        None,
        "--skill", "-s",
        help="Path to the treatment skill file. Defaults to skills/security_expert.md.",
    ),
    output: Path = typer.Option(
        None,
        "--output", "-o",
        help="Directory for result files. Defaults to results/agentic/.",
    ),
    report_path: Path = typer.Option(
        None,
        "--report",
        help="Also write a markdown comparison report to this path.",
    ),
    categories: str = typer.Option(
        None,
        "--categories", "-c",
        help="Comma-separated list of categories to include.",
    ),
    difficulty: str = typer.Option(
        None,
        "--difficulty", "-d",
        help="Comma-separated list of difficulty levels (1-5).",
    ),
    concurrency: int = typer.Option(
        3,
        "--concurrency", "-n",
        help="Max concurrent scenario evaluations.",
    ),
    delay: float = typer.Option(
        0.5,
        "--delay",
        help="Delay between scenario starts in seconds.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes", "-y",
        help="Skip confirmation prompt.",
    ),
    parallel: int = typer.Option(
        1,
        "--parallel", "-j",
        help="Run this many models in parallel (default: 1 = sequential).",
        min=1,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Print full conversation transcripts and tool call details for each scenario.",
    ),
    judge_model: str = typer.Option(
        "gpt-4o-mini",
        "--judge-model",
        help=(
            "Model to use as LLM judge for ambiguous evaluations. "
            "Text-based checkpoints that fail regex matching "
            "are re-evaluated by this model (~$0.005 per run). "
            "Default: gpt-4o-mini."
        ),
    ),
    no_judge: bool = typer.Option(
        False,
        "--no-judge",
        help="Disable the LLM judge. Regex-only evaluation (faster but less accurate).",
    ),
    runs: int = typer.Option(
        1,
        "--runs", "-r",
        help="Number of times to run each phase. Results stored per-run for variance analysis.",
        min=1,
    ),
) -> None:
    """Run baseline vs skill agentic evaluation and compare results.

    Runs the agentic benchmark twice — once without a skill (baseline) and once
    with the security expert skill — then prints a side-by-side safety comparison.
    """
    from scam.agentic.scenario import load_agentic_scenarios
    from scam.agentic.runner import run_agentic_benchmark
    from scam.agentic.results import build_unified_result, save_result
    from scam.agentic.reporting import print_unified_report

    if no_judge:
        judge_model = None

    model_names, was_interactive = _resolve_model_names(model, interactive, ctx)

    if was_interactive:
        _print_rerun_command(
            "evaluate", model_names,
            skill=skill, judge_model=judge_model, no_judge=no_judge,
            categories=categories, difficulty=difficulty,
            concurrency=concurrency, delay=delay, runs=runs,
            verbose=verbose, parallel=parallel,
        )

    # Resolve skill path
    skill_path = skill or SKILLS_DIR / "security_expert.md"
    if not skill_path.exists():
        console.print(f"[red]Skill file not found: {skill_path}[/red]")
        raise typer.Exit(1)

    # Load agentic scenarios
    all_scenarios = load_agentic_scenarios()
    if not all_scenarios:
        console.print("[yellow]No agentic scenarios found.[/yellow]")
        raise typer.Exit(1)

    # Apply category/difficulty filters
    cat_filter = {c.strip() for c in categories.split(",")} if categories else None
    diff_filter = {int(d.strip()) for d in difficulty.split(",")} if difficulty else None

    filtered = all_scenarios
    if cat_filter:
        filtered = [s for s in filtered if s.category in cat_filter]
    if diff_filter:
        filtered = [s for s in filtered if s.difficulty in diff_filter]

    if not filtered:
        console.print("[yellow]No agentic scenarios match the given filters.[/yellow]")
        raise typer.Exit(1)

    skill_content = skill_path.read_text()

    # ── Configuration summary ─────────────────────────────────────
    cost_estimates = []
    total_estimated = 0.0
    for mn in model_names:
        est = estimate_agentic_cost(mn, len(filtered), num_runs=2 * runs)
        cost_estimates.append((_short_name(mn), est))
        if est is not None:
            total_estimated += est

    console.print()
    console.print(_build_config_panel(
        mode=f"[cyan]Evaluate[/cyan] (baseline vs {skill_path.name})",
        model_names=model_names,
        scenario_summary=_scenario_summary(filtered),
        judge_model=judge_model,
        parallel=parallel,
        runs=runs,
        cost_estimates=cost_estimates,
    ))

    if not yes:
        proceed = typer.confirm("Proceed?")
        if not proceed:
            raise typer.Exit(0)

    # ── Execute all runs ──────────────────────────────────────────
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    shared_progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
    )

    # collected_data: {model_name: {"no-skill": [...], skill_stem: [...]}}
    collected_data: dict[str, dict[str, list[dict]]] = {}
    skill_phase_name = skill_path.stem
    is_multi_model = len(model_names) > 1

    async def _eval_model(mn: str) -> None:
        short = _short_name(mn)

        async def _baseline_run(idx: int) -> dict:
            run_tag = f" {idx}/{runs}" if runs > 1 else ""
            return await run_agentic_benchmark(
                model_name=mn,
                scenarios=filtered,
                skill_content=None,
                concurrency=concurrency,
                delay=delay,
                judge_model=judge_model,
                progress=shared_progress,
                task_description=f"{short} · baseline{run_tag}",
            )

        async def _skill_run(idx: int) -> dict:
            run_tag = f" {idx}/{runs}" if runs > 1 else ""
            return await run_agentic_benchmark(
                model_name=mn,
                scenarios=filtered,
                skill_content=skill_content,
                concurrency=concurrency,
                delay=delay,
                judge_model=judge_model,
                progress=shared_progress,
                task_description=f"{short} · skill{run_tag}",
            )

        try:
            baseline_coros = [_baseline_run(i) for i in range(1, runs + 1)]
            skill_coros = [_skill_run(i) for i in range(1, runs + 1)]
            all_results = await asyncio.gather(
                *baseline_coros, *skill_coros,
                return_exceptions=True,
            )
        except Exception as e:
            console.print(f"[red]Error running evaluations for {mn}:[/red] {e}")
            return

        baseline_results: list[dict] = []
        skill_results: list[dict] = []
        for i, res in enumerate(all_results):
            if isinstance(res, Exception):
                console.print(f"[red]Error in run for {mn}:[/red] {res}")
                return
            if i < runs:
                baseline_results.append(res)
            else:
                skill_results.append(res)

        collected_data[mn] = {
            "no-skill": baseline_results,
            skill_phase_name: skill_results,
        }

    async def _eval_all() -> None:
        sem = asyncio.Semaphore(parallel)

        async def _guarded(mn: str) -> None:
            async with sem:
                await _eval_model(mn)

        await asyncio.gather(*[_guarded(mn) for mn in model_names])

    with shared_progress:
        asyncio.run(_eval_all())

    # ── Build unified result ──────────────────────────────────────
    skill_hash_val = compute_skill_hash(skill_content)

    # Compute per-scenario content hashes for reproducibility
    from scam.utils.config import agentic_scenario_hash
    scenario_hashes: dict[str, str] = {}
    for sc in filtered:
        if sc.source_file:
            scenario_hashes[sc.id] = agentic_scenario_hash(sc.source_file)

    unified = build_unified_result(
        command="evaluate",
        collected_data=collected_data,
        skill_file=skill_path.name,
        skill_hash=skill_hash_val,
        skill_text=skill_content,
        judge_model=judge_model,
        scenario_count=len(filtered),
        categories_filter=categories,
        difficulty_filter=difficulty,
        scenario_hashes=scenario_hashes,
    )

    # ── Save single result file ───────────────────────────────────
    result_path = save_result(unified, output)

    # ── Report ────────────────────────────────────────────────────
    print_unified_report(unified, console, verbose=verbose)
    console.print(f"\nResults saved to [green]{result_path}[/green]")

    # Optional markdown report
    if report_path:
        from scam.agentic.reporting import generate_unified_markdown_report
        md = generate_unified_markdown_report(unified)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(md)
        console.print(f"Report:  [green]{report_path}[/green]")

    # ── Offer HTML export ─────────────────────────────────────────
    _offer_html_export(unified, result_path, console, yes=yes)


# ── Replay viewer ─────────────────────────────────────────────────────


@app.command()
def replay(
    path: Path = typer.Argument(
        ...,
        help="Path to a v2 result JSON file.",
    ),
    speed: str = typer.Option(
        "medium",
        "--speed",
        "-s",
        help="Playback speed: slow, medium, or fast.",
    ),
    scenario: str = typer.Option(
        None,
        "--scenario",
        help="Jump directly to a scenario ID (skip selector).",
    ),
    model_filter: str = typer.Option(
        None,
        "--model", "-m",
        help="Filter to a specific model.",
    ),
    phase: str = typer.Option(
        None,
        "--phase",
        help="Filter to a specific phase (e.g. 'no-skill', 'security_expert').",
    ),
) -> None:
    """Replay a recorded scenario conversation from a v2 benchmark result.

    Load a result JSON, browse models/phases/scenarios, and watch the agent
    conversation auto-play with tool calls, results, and a final scorecard.
    """
    from scam.agentic.replay import (
        SPEED_PRESETS,
        load_run_v2,
        replay_scenario,
        select_scenario,
    )

    if speed not in SPEED_PRESETS:
        console.print(
            f"[red]Invalid speed '{speed}'. "
            f"Choose from: {', '.join(sorted(SPEED_PRESETS))}[/red]"
        )
        raise typer.Exit(1)

    run_path = Path(path)
    if not run_path.exists():
        console.print(f"[red]Path not found: {run_path}[/red]")
        raise typer.Exit(1)

    try:
        scores = load_run_v2(
            run_path,
            model=model_filter,
            phase=phase,
            console=console,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        console.print(f"[red]Error loading result: {e}[/red]")
        raise typer.Exit(1)

    if not scores:
        console.print("[yellow]No scenario scores found.[/yellow]")
        raise typer.Exit(1)

    # Direct scenario selection via --scenario flag
    if scenario:
        match = next((s for s in scores if s.get("scenario_id") == scenario), None)
        if not match:
            console.print(f"[red]Scenario '{scenario}' not found.[/red]")
            available = ", ".join(s.get("scenario_id", "?") for s in scores)
            console.print(f"[dim]Available: {available}[/dim]")
            raise typer.Exit(1)
        selected = match
    else:
        selected = select_scenario(
            scores,
            console=console,
        )
        if selected is None:
            raise typer.Exit(0)

    replay_scenario(selected, speed=speed, console=console)


# ── Export (HTML + video) ─────────────────────────────────────────────


@app.command()
def export(
    path: Path = typer.Argument(
        ...,
        help="Path to a v2 result JSON file.",
    ),
    output: Path = typer.Option(
        None,
        "--output", "-o",
        help="Output directory for exported files. Defaults to ./exports/.",
    ),
    scenario: str = typer.Option(
        None,
        "--scenario",
        help="Export only this scenario ID.",
    ),
    model_filter: str = typer.Option(
        None,
        "--model", "-m",
        help="Export only scenarios from this model.",
    ),
    phase: str = typer.Option(
        None,
        "--phase",
        help="Export only scenarios from this phase (e.g. 'no-skill', 'security_expert').",
    ),
    video: bool = typer.Option(
        False,
        "--video",
        help="Export as MP4 video instead of HTML.",
    ),
    fps: int = typer.Option(
        30,
        "--fps",
        help="Video frame rate (only used with --video).",
    ),
) -> None:
    """Export scenario replays as self-contained HTML pages or MP4 videos.

    Generates beautiful, shareable files from v2 benchmark results.
    HTML export produces a comprehensive dashboard with summary,
    per-model comparison, and per-scenario animated replays.
    MP4 videos produce standalone recordings suitable for sharing.
    """
    from scam.agentic.results import load_result

    run_path = Path(path)
    if not run_path.exists():
        console.print(f"[red]Path not found: {run_path}[/red]")
        raise typer.Exit(1)

    try:
        data = load_result(run_path)
    except (ValueError, json.JSONDecodeError) as e:
        console.print(f"[red]Error loading result: {e}[/red]")
        raise typer.Exit(1)

    # Default: exports/{result-stem}/ e.g. exports/scam-evaluate-1738944000/
    if output:
        out_dir = output
    else:
        out_dir = Path("./exports") / run_path.stem

    if video:
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
        from scam.agentic.export_video import export_all_videos_v2

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total} frames"),
                console=console,
            ) as progress:
                tasks: dict[str, int] = {}

                def _video_progress(
                    sid: str, current: int, total: int,
                ) -> None:
                    if sid not in tasks:
                        tasks[sid] = progress.add_task(sid, total=total)
                    progress.update(tasks[sid], completed=current, total=total)

                written = export_all_videos_v2(
                    data,
                    out_dir,
                    model=model_filter,
                    phase=phase,
                    scenario_id=scenario,
                    fps=fps,
                    progress_callback=_video_progress,
                )
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    else:
        from scam.agentic.export_html import export_result

        try:
            written = export_result(
                data,
                out_dir,
                model=model_filter,
                phase=phase,
                scenario_id=scenario,
            )
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    console.print(f"\n[bold green]Exported {len(written)} file(s):[/bold green]")
    for p in written:
        console.print(f"  [green]{p}[/green]")
    console.print()


# ── Report ───────────────────────────────────────────────────────────


@app.command()
def report(
    path: Path = typer.Argument(..., help="Path to a v2 result JSON file."),
    output: Path = typer.Option(
        None,
        "--output", "-o",
        help="Output path for markdown report.",
    ),
) -> None:
    """Generate a markdown report from a v2 benchmark result file."""
    from scam.agentic.results import load_result
    from scam.agentic.reporting import generate_unified_markdown_report

    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(1)

    try:
        data = load_result(path)
    except (ValueError, json.JSONDecodeError) as e:
        console.print(f"[red]Error loading result: {e}[/red]")
        raise typer.Exit(1)

    md = generate_unified_markdown_report(data)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md)
        console.print(f"Report saved to [green]{output}[/green]")
    else:
        console.print(md)


# ── Publish (GitHub Pages site) ───────────────────────────────────────


@app.command()
def publish(
    path: Path = typer.Argument(
        ...,
        help="Path to a v2 result JSON file.",
    ),
    output: Path = typer.Option(
        "docs",
        "--output", "-o",
        help="Output directory for the site (default: docs/).",
    ),
    skill: Path = typer.Option(
        "skills/security_expert.md",
        "--skill",
        help="Path to the skill file to feature on the site.",
    ),
) -> None:
    """Generate the GitHub Pages site from benchmark results.

    Produces a static site in docs/ with leaderboard, featured replays,
    and the security skill. Commit and push to deploy via GitHub Pages.

    Example:

        scam publish results/agentic/scam-evaluate-1770653270.json
    """
    from scam.agentic.results import load_result
    from scam.agentic.site_generator import generate_site

    run_path = Path(path)
    if not run_path.exists():
        console.print(f"[red]Path not found: {run_path}[/red]")
        raise typer.Exit(1)

    skill_path = Path(skill)
    if not skill_path.exists():
        console.print(f"[yellow]Warning: Skill file not found: {skill_path}[/yellow]")

    try:
        data = load_result(run_path)
    except (ValueError, json.JSONDecodeError) as e:
        console.print(f"[red]Error loading result: {e}[/red]")
        raise typer.Exit(1)

    out_dir = Path(output)

    written = generate_site(data, out_dir, skill_path)

    console.print(f"\n[bold green]Site generated ({len(written)} files):[/bold green]")
    for p in written:
        console.print(f"  [green]{p}[/green]")

    console.print(
        f"\n[dim]To deploy: commit the [bold]{out_dir}/[/bold] directory "
        f"and push to main.\n"
        f"Then enable GitHub Pages in repo settings → Pages → "
        f'Source: "Deploy from a branch" → Branch: main → Folder: /{out_dir}[/dim]'
    )


# ── Scenarios management ──────────────────────────────────────────────


@app.command()
def scenarios(
    list_scenarios: bool = typer.Option(
        False, "--list", "-l", help="List all available scenarios."
    ),
    validate: bool = typer.Option(
        False, "--validate", "-v", help="Validate all scenario files."
    ),
    categories_only: bool = typer.Option(
        False, "--categories", help="List categories only."
    ),
) -> None:
    """List, validate, or inspect benchmark scenarios."""
    if categories_only:
        _list_agentic_categories()
    elif validate:
        _validate_agentic_scenarios()
    elif list_scenarios:
        _list_agentic_scenarios()
    else:
        _agentic_summary()


# ── Agentic scenario management helpers ──────────────────────────────


def _list_agentic_categories() -> None:
    """List categories in agentic scenarios."""
    from scam.agentic.scenario import load_agentic_scenarios

    all_scenarios = load_agentic_scenarios()
    cats = set(s.category for s in all_scenarios)
    console.print("[bold]Available agentic categories:[/bold]")
    for c in sorted(cats):
        console.print(f"  • {c}")


def _agentic_summary() -> None:
    """Print an agentic scenario summary."""
    from scam.agentic.scenario import load_agentic_scenarios
    from collections import Counter

    all_scenarios = load_agentic_scenarios()
    if not all_scenarios:
        console.print("[yellow]No agentic scenarios found.[/yellow]")
        return

    console.print(f"\n[bold]Scenario Summary (agentic)[/bold]")
    console.print(f"Total: {len(all_scenarios)}")

    cats = Counter(s.category for s in all_scenarios)
    for cat, count in sorted(cats.items()):
        console.print(f"  • {cat}: {count}")

    diffs = Counter(s.difficulty for s in all_scenarios)
    console.print(f"\nBy difficulty:")
    for d in sorted(diffs):
        console.print(f"  • Level {d}: {diffs[d]}")


def _list_agentic_scenarios() -> None:
    """List all agentic scenarios in a table."""
    from scam.agentic.scenario import load_agentic_scenarios

    all_scenarios = load_agentic_scenarios()
    if not all_scenarios:
        console.print("[yellow]No agentic scenarios found.[/yellow]")
        return

    table = Table(title="All Scenarios (agentic)", show_header=True, header_style="bold")
    table.add_column("ID", style="cyan")
    table.add_column("Category")
    table.add_column("Diff", justify="center")
    table.add_column("Description")
    table.add_column("Turns", justify="center")
    table.add_column("Checkpoints", justify="center")

    for s in all_scenarios:
        table.add_row(
            s.id,
            s.category,
            str(s.difficulty),
            s.description,
            str(len(s.turns)),
            str(len(s.checkpoints)),
        )

    console.print(table)


def _validate_agentic_scenarios() -> None:
    """Validate agentic scenario YAML files."""
    import yaml

    errors: list[str] = []
    warnings: list[str] = []
    total = 0
    seen_ids: set[str] = set()

    if not AGENTIC_SCENARIOS_DIR.exists():
        console.print("[yellow]No agentic scenarios directory found.[/yellow]")
        return

    for yaml_file in sorted(AGENTIC_SCENARIOS_DIR.rglob("*.yaml")):
        # Skip template files
        if yaml_file.name.startswith("_"):
            continue

        try:
            with open(yaml_file) as f:
                docs = list(yaml.safe_load_all(f))
        except yaml.YAMLError as e:
            errors.append(f"{yaml_file}: Invalid YAML: {e}")
            continue

        for doc in docs:
            if doc is None:
                continue
            items = doc if isinstance(doc, list) else [doc]
            for item in items:
                total += 1
                sid = item.get("id", f"unknown-{total}")

                # Required top-level fields
                for field in ("id", "environment", "turns", "checkpoints"):
                    if field not in item:
                        errors.append(f"{yaml_file}: Missing required field '{field}' in {sid}")

                # Duplicate ID check
                if sid in seen_ids:
                    errors.append(f"{yaml_file}: Duplicate scenario ID: {sid}")
                seen_ids.add(sid)

                # Validate environment.emails
                env = item.get("environment", {})
                for email in env.get("emails", []):
                    for ef in ("id", "from", "subject", "body"):
                        if ef not in email:
                            errors.append(f"{sid}: email missing required field '{ef}'")

                # Validate checkpoints
                for cp in item.get("checkpoints", []):
                    for cf in ("id", "check_type", "weight"):
                        if cf not in cp:
                            errors.append(f"{sid}: checkpoint missing required field '{cf}'")

                # Warn on missing threat emails
                emails = env.get("emails", [])
                has_threat = any(e.get("threat") for e in emails)
                if not has_threat:
                    warnings.append(f"{sid}: no threat emails in environment")

    if errors:
        console.print(f"\n[red bold]Validation FAILED[/red bold] ({len(errors)} errors)")
        for e in errors:
            console.print(f"  [red]✗[/red] {e}")
    else:
        console.print(f"\n[green bold]Validation PASSED[/green bold]")

    if warnings:
        console.print(f"\n[yellow]Warnings ({len(warnings)}):[/yellow]")
        for w in warnings:
            console.print(f"  [yellow]⚠[/yellow] {w}")

    console.print(f"\nTotal agentic scenarios: {total}")
    console.print(f"Unique IDs: {len(seen_ids)}")


if __name__ == "__main__":
    app()
