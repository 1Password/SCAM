"""Replay viewer — step through recorded scenario conversations.

Plays back a recorded agentic scenario with realistic visual effects:

* **User messages** appear character-by-character at human typing speed.
* **Assistant messages** stream word-by-word like real LLM token output,
  preceded by a brief "thinking" spinner.
* **Tool results** show a loading spinner then reveal the output.
* **System prompts** are skipped (they're always the same).
"""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


# ── Data loading ──────────────────────────────────────────────────────


def load_run(path: Path) -> dict:
    """Load a single run JSON file.

    If *path* is a directory (multi-run), list the ``run-*.json`` files
    and let the user pick one.
    """
    if path.is_dir():
        run_files = sorted(path.glob("run-*.json"))
        if not run_files:
            raise FileNotFoundError(f"No run-*.json files found in {path}")
        if len(run_files) == 1:
            path = run_files[0]
        else:
            console = Console()
            console.print(f"\n[bold]Found {len(run_files)} runs in[/bold] {path}\n")
            for i, rf in enumerate(run_files, 1):
                console.print(f"  [green]{i}[/green]  {rf.name}")
            console.print()
            raw = console.input(f"[bold]Select run [1]> [/bold]").strip()
            try:
                idx = int(raw) if raw else 1
            except ValueError:
                idx = 1
            idx = max(1, min(idx, len(run_files)))
            path = run_files[idx - 1]

    with open(path) as f:
        return json.load(f)


def load_run_v2(
    path: Path,
    *,
    model: str | None = None,
    phase: str | None = None,
    console: Console | None = None,
) -> list[dict]:
    """Load scenarios from a v2 unified result file.

    Provides interactive model → phase → run selection when the result
    contains multiple choices and no filters are provided.

    Returns a flat list of scenario score dicts suitable for
    ``select_scenario()`` and ``replay_scenario()``.
    """
    from scam.agentic.results import load_result

    console = console or Console()
    data = load_result(path)
    models_data = data.get("models", {})

    if not models_data:
        raise ValueError("No model data found in result file")

    # ── Model selection ───────────────────────────────────────────
    model_names = list(models_data.keys())
    if model:
        if model not in model_names:
            raise ValueError(
                f"Model '{model}' not found. Available: {', '.join(model_names)}"
            )
        chosen_model = model
    elif len(model_names) == 1:
        chosen_model = model_names[0]
    else:
        console.print(f"\n[bold]Models ({len(model_names)}):[/bold]")
        for i, mn in enumerate(model_names, 1):
            phases = models_data[mn]
            phase_labels = []
            for pn, pd in phases.items():
                score = pd.get("summary", {}).get("mean_safety_score", 0)
                n_runs = len(pd.get("runs", []))
                phase_labels.append(f"{pn} ({score:.0%}, {n_runs} run{'s' if n_runs > 1 else ''})")
            console.print(f"  [green]{i}[/green]  [cyan]{mn}[/cyan]  {' | '.join(phase_labels)}")
        console.print()
        raw = console.input("[bold]Select model [1]> [/bold]").strip()
        try:
            idx = int(raw) if raw else 1
        except ValueError:
            idx = 1
        idx = max(1, min(idx, len(model_names)))
        chosen_model = model_names[idx - 1]

    phases = models_data[chosen_model]

    # ── Phase selection ───────────────────────────────────────────
    phase_names = list(phases.keys())
    if phase:
        if phase not in phase_names:
            raise ValueError(
                f"Phase '{phase}' not found for {chosen_model}. "
                f"Available: {', '.join(phase_names)}"
            )
        chosen_phase = phase
    elif len(phase_names) == 1:
        chosen_phase = phase_names[0]
    else:
        console.print(f"\n[bold]Phases for {chosen_model}:[/bold]")
        for i, pn in enumerate(phase_names, 1):
            pd = phases[pn]
            score = pd.get("summary", {}).get("mean_safety_score", 0)
            n_runs = len(pd.get("runs", []))
            console.print(
                f"  [green]{i}[/green]  {pn}  "
                f"({score:.0%} mean, {n_runs} run{'s' if n_runs > 1 else ''})"
            )
        console.print()
        raw = console.input("[bold]Select phase [1]> [/bold]").strip()
        try:
            idx = int(raw) if raw else 1
        except ValueError:
            idx = 1
        idx = max(1, min(idx, len(phase_names)))
        chosen_phase = phase_names[idx - 1]

    phase_data = phases[chosen_phase]
    runs = phase_data.get("runs", [])

    if not runs:
        return []

    # ── Run selection (if multi-run) ──────────────────────────────
    if len(runs) == 1:
        chosen_run = runs[0]
    else:
        console.print(f"\n[bold]Runs for {chosen_model} / {chosen_phase} ({len(runs)}):[/bold]")
        for run in runs:
            idx = run.get("run_index", 0)
            score = run.get("safety_score", 0)
            s_color = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"
            console.print(
                f"  [green]{idx}[/green]  [{s_color}]{score:.0%}[/{s_color}]"
            )
        console.print()
        raw = console.input("[bold]Select run [1]> [/bold]").strip()
        try:
            idx = int(raw) if raw else 1
        except ValueError:
            idx = 1
        idx = max(1, min(idx, len(runs)))
        chosen_run = runs[idx - 1]

    console.print(
        f"\n[dim]Loaded: {chosen_model} / {chosen_phase} / "
        f"run {chosen_run.get('run_index', 1)}[/dim]"
    )

    return chosen_run.get("scenarios", [])


# ── Scenario selector ─────────────────────────────────────────────────


def select_scenario(
    scores: list[dict],
    *,
    console: Console | None = None,
) -> dict | None:
    """Display a scenario table and let the user pick one.

    All scenarios are shown, sorted worst-first so failures are
    prominent at the top.  Returns the selected scenario dict or
    *None* if the list is empty.
    """
    console = console or Console()

    candidates = list(scores)
    n_fail = sum(1 for s in candidates if s.get("safety_score", 1.0) < 1.0)
    label = f"Scenarios ({n_fail} failed / {len(candidates)} total)"

    # Sort worst-first
    candidates.sort(key=lambda s: s.get("safety_score", 0))

    if not candidates:
        console.print("[yellow]No scenarios found.[/yellow]")
        return None

    table = Table(title=label, show_header=True, header_style="bold")
    table.add_column("#", justify="right", style="green", width=4)
    table.add_column("Scenario", style="cyan")
    table.add_column("D", justify="center", width=3)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Crit", justify="center", width=5)
    table.add_column("Turns", justify="right", width=6)
    table.add_column("Tools", justify="right", width=6)

    for i, s in enumerate(candidates, 1):
        score = s.get("safety_score", 0)
        score_color = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"
        crit = "[red]YES[/red]" if s.get("critical_failure") else "[dim]—[/dim]"
        dang = s.get("dangerous_call_count", 0)
        tools_str = str(s.get("tool_call_count", 0))
        if dang:
            tools_str += f" [red]({dang} dangerous)[/red]"

        table.add_row(
            str(i),
            s.get("scenario_id", "?"),
            str(s.get("difficulty", "?")),
            f"[{score_color}]{score:.0%}[/{score_color}]",
            crit,
            str(s.get("turn_count", "?")),
            tools_str,
        )

    console.print()
    console.print(table)
    console.print()

    raw = console.input("[bold]Select scenario [1]> [/bold]").strip()
    try:
        idx = int(raw) if raw else 1
    except ValueError:
        idx = 1
    idx = max(1, min(idx, len(candidates)))

    return candidates[idx - 1]


# ── Message rendering ─────────────────────────────────────────────────

_ROLE_STYLES = {
    "system": ("dim", "dim", "System Prompt"),
    "user": ("blue", "bold blue", "User"),
    "assistant": ("green", "bold green", "Assistant"),
    "tool": ("yellow", "bold yellow", "Tool"),
}


def _truncate(text: str, max_lines: int = 20) -> str:
    """Truncate text to *max_lines*, appending an indicator if cut."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + "\n[dim]... truncated ...[/dim]"


def _pretty_json(raw: str, max_lines: int = 20) -> str:
    """Try to pretty-print JSON; fall back to raw text."""
    try:
        obj = json.loads(raw)
        formatted = json.dumps(obj, indent=2)
        return _truncate(formatted, max_lines)
    except (json.JSONDecodeError, TypeError):
        return _truncate(raw, max_lines)


def _format_tool_call(tc: dict) -> str:
    """Format a single tool_call dict into a readable string."""
    fn = tc.get("function", {})
    name = fn.get("name", "unknown")
    args_raw = fn.get("arguments", "{}")
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        if args:
            parts = [f"{k}={json.dumps(v)}" for k, v in args.items()]
            return f"{name}({', '.join(parts)})"
        return f"{name}()"
    except (json.JSONDecodeError, TypeError):
        return f"{name}({args_raw})"


def _build_dangerous_set(tool_log: list[dict]) -> set[str]:
    """Build a set of (tool_name, args_json) for dangerous calls."""
    dangerous = set()
    for entry in tool_log:
        if entry.get("is_dangerous"):
            # Use tool name + sorted args as key
            args_key = json.dumps(entry.get("arguments", {}), sort_keys=True)
            dangerous.add((entry.get("tool", ""), args_key))
    return dangerous


def _is_dangerous_call(tc: dict, dangerous_set: set[str]) -> bool:
    """Check if a tool call matches a dangerous entry."""
    fn = tc.get("function", {})
    name = fn.get("name", "")
    args_raw = fn.get("arguments", "{}")
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        args_key = json.dumps(args, sort_keys=True)
    except (json.JSONDecodeError, TypeError):
        args_key = str(args_raw)
    return (name, args_key) in dangerous_set


def render_message(
    msg: dict,
    console: Console,
    *,
    dangerous_set: set[str] | None = None,
    is_first_system: bool = False,
) -> None:
    """Render a single conversation message as a Rich Panel."""
    role = msg.get("role", "unknown")
    content = msg.get("content") or ""
    border, title_style, label = _ROLE_STYLES.get(
        role, ("dim", "dim", role.title())
    )

    # ── System prompt: collapse to first 2 lines ──
    if role == "system":
        lines = content.split("\n")
        if len(lines) > 2:
            display = "\n".join(lines[:2]) + "\n[dim]...[/dim]"
        else:
            display = content
        console.print(Panel(
            display,
            title=f"[{title_style}]{label}[/{title_style}]",
            border_style=border,
            padding=(0, 1),
        ))
        return

    # ── User message ──
    if role == "user":
        console.print(Panel(
            Markdown(content) if content else "[dim](empty)[/dim]",
            title=f"[{title_style}]{label}[/{title_style}]",
            border_style=border,
            padding=(0, 1),
        ))
        return

    # ── Tool result ──
    if role == "tool":
        tool_id = msg.get("tool_call_id", "")
        short_id = tool_id[-8:] if len(tool_id) > 8 else tool_id
        pretty = _pretty_json(content)
        console.print(Panel(
            pretty,
            title=f"[{title_style}]Tool Result[/{title_style}] [dim]{short_id}[/dim]",
            border_style=border,
            padding=(0, 1),
        ))
        return

    # ── Assistant message ──
    tool_calls = msg.get("tool_calls") or []
    parts: list[str] = []

    if content:
        parts.append(content)

    if tool_calls:
        if parts:
            parts.append("")  # blank line separator
        dangerous_set = dangerous_set or set()
        for tc in tool_calls:
            is_dang = _is_dangerous_call(tc, dangerous_set)
            call_str = _format_tool_call(tc)
            if is_dang:
                parts.append(f"  [red bold]DANGEROUS[/red bold] [red]{call_str}[/red]")
            else:
                parts.append(f"  [cyan]{call_str}[/cyan]")

    # Check if any tool call is dangerous — use red border
    has_dangerous = any(
        _is_dangerous_call(tc, dangerous_set or set())
        for tc in tool_calls
    )

    if has_dangerous:
        border = "red"
        title_style = "bold red"
        label = "Assistant [red]⚠ DANGEROUS[/red]"

    body = "\n".join(parts) if parts else "[dim](no response)[/dim]"

    # For text-heavy responses, use Markdown rendering
    if content and not tool_calls:
        console.print(Panel(
            Markdown(content),
            title=f"[{title_style}]{label}[/{title_style}]",
            border_style=border,
            padding=(0, 1),
        ))
    else:
        console.print(Panel(
            body,
            title=f"[{title_style}]{label}[/{title_style}]",
            border_style=border,
            padding=(0, 1),
        ))


# ── Checkpoint scorecard ──────────────────────────────────────────────


def render_checkpoints(scenario: dict, console: Console) -> None:
    """Render the checkpoint scorecard after a replay."""
    checkpoints = scenario.get("checkpoints", [])
    sid = scenario.get("scenario_id", "?")
    score = scenario.get("safety_score", 0)
    crit = scenario.get("critical_failure", False)

    score_color = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"

    table = Table(
        title=f"Checkpoint Results — {sid} ([{score_color}]{score:.0%}[/{score_color}])",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Result", justify="center", width=6)
    table.add_column("Weight", justify="right", width=6)
    table.add_column("Checkpoint", style="cyan")
    table.add_column("Description")
    table.add_column("Details", style="dim")

    for cp in checkpoints:
        passed = cp.get("passed", False)
        result_str = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        weight = cp.get("weight", 0)
        table.add_row(
            result_str,
            f"[dim]{weight}w[/dim]",
            cp.get("id", "?"),
            cp.get("description", ""),
            cp.get("details", ""),
        )

    console.print()
    console.print(table)

    if crit:
        console.print(
            f"\n  [red bold]CRITICAL FAILURE[/red bold] — "
            f"Safety score: [{score_color}]{score:.0%}[/{score_color}]"
        )
    else:
        console.print(
            f"\n  Safety score: [{score_color}]{score:.0%}[/{score_color}]"
        )


# ── Speed presets and timing ──────────────────────────────────────────
#
# Three named presets calibrated to feel natural at each pace:
#
#   slow   — leisurely; typing ~40 WPM, LLM tokens visible individually
#   medium — brisk default; typing ~70 WPM, tokens flow smoothly
#   fast   — scan mode; everything happens quickly
#
# User typing uses per-character delays with jitter and word-boundary
# pauses.  LLM streaming uses per-token (≈word) delays.  Tool results
# use a spinner whose duration is randomised within a range.

SPEED_PRESETS: set[str] = {"slow", "medium", "fast"}

# Base milliseconds per character for user typing effect.
# ~30 WPM slow, ~50 WPM medium, ~90 WPM fast (avg word ≈ 5 chars).
_TYPING_MS: dict[str, int] = {"slow": 120, "medium": 65, "fast": 28}

# Base milliseconds per token (≈word) for LLM streaming effect.
# Slow enough to read along; fast just skims.
_TOKEN_MS: dict[str, int] = {"slow": 180, "medium": 80, "fast": 22}

# (min, max) seconds for the "Thinking…" spinner before assistant text.
_THINK_SEC: dict[str, tuple[float, float]] = {
    "slow": (2.0, 3.5),
    "medium": (1.0, 2.0),
    "fast": (0.3, 0.6),
}

# (min, max) seconds for the tool-execution spinner.
_TOOL_EXEC_SEC: dict[str, tuple[float, float]] = {
    "slow": (2.5, 4.5),
    "medium": (1.2, 2.5),
    "fast": (0.4, 0.8),
}

# Pause between consecutive messages (seconds).
_GAP_SEC: dict[str, float] = {"slow": 1.5, "medium": 0.8, "fast": 0.3}

# Extra pause before a user message that follows an assistant/tool turn,
# simulating the human reading the response and deciding what to type.
_USER_THINK_SEC: dict[str, tuple[float, float]] = {
    "slow": (3.0, 5.0),
    "medium": (1.5, 3.0),
    "fast": (0.5, 1.0),
}

# Cap animation length so very long messages don't drag.
_MAX_TYPING_CHARS = 300
_MAX_STREAM_TOKENS = 120

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _tokenize_words(text: str) -> list[str]:
    """Split *text* into word-boundary tokens (word + trailing space)."""
    return re.findall(r"\S+\s*", text) if text else []


# ── Streaming renderers ──────────────────────────────────────────────


def _stream_user(content: str, console: Console, speed: str) -> None:
    """Render a user message with a human-typing effect.

    Characters appear one-by-one with realistic cadence: jitter between
    keystrokes, longer pauses at word boundaries and punctuation, and an
    animated cursor while "typing".
    """
    if not content:
        console.print(Panel(
            "[dim](empty)[/dim]",
            title="[bold blue]User[/bold blue]",
            border_style="blue",
            padding=(0, 1),
        ))
        return

    base_s = _TYPING_MS[speed] / 1000.0
    chars = list(content)
    animate_n = min(len(chars), _MAX_TYPING_CHARS)

    with Live(console=console, refresh_per_second=30) as live:
        displayed = ""
        for i, char in enumerate(chars):
            displayed += char
            if i < animate_n:
                live.update(Panel(
                    Text(displayed + "▌"),
                    title="[bold blue]User[/bold blue]",
                    border_style="blue",
                    padding=(0, 1),
                ))
                delay = base_s * random.uniform(0.5, 1.5)
                if char in " \n":
                    delay *= 2.0          # pause between words
                elif char in ".,;:!?":
                    delay *= 3.0          # pause at punctuation
                time.sleep(delay)
            elif i == animate_n:
                # Cap reached — reveal the rest instantly
                displayed = content

        # Final render without cursor
        live.update(Panel(
            content,
            title="[bold blue]User[/bold blue]",
            border_style="blue",
            padding=(0, 1),
        ))


def _stream_assistant(
    content: str,
    tool_calls: list[dict],
    console: Console,
    speed: str,
    dangerous_set: set,
) -> None:
    """Render an assistant message with LLM-style token streaming.

    Shows a brief "thinking" spinner, then streams words at typical LLM
    token speed.  If the message includes tool calls they appear after
    the text is complete.
    """
    has_dangerous = any(
        _is_dangerous_call(tc, dangerous_set) for tc in (tool_calls or [])
    )
    border = "red" if has_dangerous else "green"
    title_style = "bold red" if has_dangerous else "bold green"
    label = "Assistant [red]⚠ DANGEROUS[/red]" if has_dangerous else "Assistant"
    title = f"[{title_style}]{label}[/{title_style}]"

    base_s = _TOKEN_MS[speed] / 1000.0
    tokens = _tokenize_words(content) if content else []
    animate_n = min(len(tokens), _MAX_STREAM_TOKENS)

    think_lo, think_hi = _THINK_SEC[speed]
    think_dur = random.uniform(think_lo, think_hi)

    with Live(console=console, refresh_per_second=30) as live:
        # ── Phase 1: "Thinking…" spinner ──
        start = time.time()
        frame = 0
        while time.time() - start < think_dur:
            ch = _SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]
            live.update(Panel(
                f"[dim]{ch} Thinking…[/dim]",
                title=title,
                border_style=border,
                padding=(0, 1),
            ))
            time.sleep(0.08)
            frame += 1

        # ── Phase 2: stream tokens ──
        displayed = ""
        for i, token in enumerate(tokens):
            displayed += token
            if i < animate_n:
                live.update(Panel(
                    Text(displayed + "█"),
                    title=title,
                    border_style=border,
                    padding=(0, 1),
                ))
                delay = base_s * random.uniform(0.8, 1.2)
                stripped = token.rstrip()
                if stripped and stripped[-1] in ".!?:":
                    delay *= 2.5          # sentence boundary pause
                elif stripped and stripped[-1] in ",;":
                    delay *= 1.5
                time.sleep(delay)
            elif i == animate_n:
                displayed = content

        # ── Phase 3: final render ──
        parts: list[str] = []
        if content:
            parts.append(content)
        if tool_calls:
            if parts:
                parts.append("")
            for tc in tool_calls:
                is_dang = _is_dangerous_call(tc, dangerous_set)
                call_str = _format_tool_call(tc)
                if is_dang:
                    parts.append(
                        f"  [red bold]⚠ DANGEROUS[/red bold] [red]{call_str}[/red]"
                    )
                else:
                    parts.append(f"  [cyan]{call_str}[/cyan]")

        body = "\n".join(parts) if parts else "[dim](no response)[/dim]"

        if content and not tool_calls:
            live.update(Panel(
                Markdown(content),
                title=title,
                border_style=border,
                padding=(0, 1),
            ))
        else:
            live.update(Panel(
                body,
                title=title,
                border_style=border,
                padding=(0, 1),
            ))


def _stream_tool_result(
    content: str,
    tool_call_id: str,
    console: Console,
    speed: str,
) -> None:
    """Render a tool result with a loading spinner then the output."""
    short_id = tool_call_id[-8:] if len(tool_call_id) > 8 else tool_call_id
    title = f"[bold yellow]Tool Result[/bold yellow] [dim]{short_id}[/dim]"

    exec_lo, exec_hi = _TOOL_EXEC_SEC[speed]
    wait = random.uniform(exec_lo, exec_hi)

    with Live(console=console, refresh_per_second=12) as live:
        # Spinner phase
        start = time.time()
        frame = 0
        while time.time() - start < wait:
            ch = _SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]
            live.update(Panel(
                f"[dim]{ch} Executing…[/dim]",
                title=title,
                border_style="yellow dim",
                padding=(0, 1),
            ))
            time.sleep(0.08)
            frame += 1

        # Reveal result
        pretty = _pretty_json(content)
        live.update(Panel(
            pretty,
            title=title,
            border_style="yellow",
            padding=(0, 1),
        ))


# ── Auto-play loop ────────────────────────────────────────────────────


def replay_scenario(
    scenario: dict,
    *,
    speed: str = "medium",
    console: Console | None = None,
) -> None:
    """Auto-play a scenario conversation with realistic visual effects.

    * System prompts are skipped (always the same).
    * User messages appear with a character-by-character typing effect.
    * Assistant messages stream word-by-word like real LLM output.
    * Tool results show a loading spinner then reveal the output.

    When the console is not a real terminal (tests, piped output), falls
    back to instant static rendering via :func:`render_message`.

    Args:
        scenario: A scenario score dict containing ``messages``,
            ``tool_log``, ``checkpoints``, etc.
        speed: Playback speed preset — ``"slow"``, ``"medium"``, or
            ``"fast"``.
        console: Rich console instance.
    """
    console = console or Console()
    messages = scenario.get("messages", [])
    tool_log = scenario.get("tool_log", [])
    dangerous_set = _build_dangerous_set(tool_log)

    sid = scenario.get("scenario_id", "?")
    desc = scenario.get("description", "")
    diff = scenario.get("difficulty", "?")
    score = scenario.get("safety_score", 0)
    score_color = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"

    # Count non-system messages for the header
    visible = [m for m in messages if m.get("role") != "system"]

    # Header
    console.print()
    console.print(Panel(
        f"[bold]{sid}[/bold]  [dim]D{diff}[/dim]\n"
        f"{desc}\n\n"
        f"[dim]{len(visible)} messages  ·  "
        f"{scenario.get('tool_call_count', 0)} tool calls  ·  "
        f"Score: [{score_color}]{score:.0%}[/{score_color}][/dim]",
        title="[bold cyan]Scenario Replay[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))

    if not visible:
        console.print("[yellow]No messages to replay.[/yellow]")
        return

    animated = console.is_terminal
    gap = _GAP_SEC.get(speed, _GAP_SEC["medium"])
    think_lo, think_hi = _USER_THINK_SEC.get(speed, _USER_THINK_SEC["medium"])
    prev_role: str | None = None

    try:
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []
            tool_call_id = msg.get("tool_call_id", "")

            # Skip system prompts
            if role == "system":
                continue

            if animated:
                if role == "user":
                    # Longer pause when user follows the agent — reading
                    # the response and deciding what to type next.
                    if prev_role in ("assistant", "tool"):
                        time.sleep(random.uniform(think_lo, think_hi))
                    else:
                        time.sleep(gap)
                    _stream_user(content, console, speed)
                elif role == "assistant":
                    time.sleep(gap)
                    _stream_assistant(
                        content, tool_calls, console, speed, dangerous_set,
                    )
                elif role == "tool":
                    _stream_tool_result(content, tool_call_id, console, speed)
            else:
                # Static fallback for non-terminal (tests, piped output)
                render_message(
                    msg, console,
                    dangerous_set=dangerous_set,
                    is_first_system=False,
                )

            prev_role = role

        # Scorecard
        if animated:
            time.sleep(gap * 2)
        render_checkpoints(scenario, console)
        console.print()

    except KeyboardInterrupt:
        console.print("\n[dim]Replay stopped.[/dim]")
