"""Agentic benchmark runner — multi-turn conversation loop with tool routing."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from scam.agentic.environment import ToolCallRecord, ToolRouter
from scam.agentic.evaluator import score_agentic
from scam.agentic.scenario import (
    STANDARD_TOOLS,
    AgenticScenario,
    load_agentic_scenarios,
)
from scam.models.base import BaseModel

logger = logging.getLogger("scam")

# Safety limit: max tool-call rounds per user turn before we force a text response.
DEFAULT_MAX_TOOL_ROUNDS = 15


@dataclass
class AgenticResult:
    """Raw result from running a single agentic scenario."""

    scenario_id: str
    messages: list[dict]
    tool_log: list[ToolCallRecord]
    turn_responses: list[str]  # Agent text responses, one per user turn
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


async def run_agentic_scenario(
    model: BaseModel,
    scenario: AgenticScenario,
    skill_content: str | None = None,
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
) -> AgenticResult:
    """Run a single agentic scenario through the model.

    Drives a multi-turn conversation: for each scripted user turn, the
    model may call tools (routed to the simulated environment) zero or
    more times before producing a text response.

    Args:
        model: The model to evaluate.
        scenario: The agentic scenario to run.
        skill_content: Optional skill content prepended to the system prompt.
        max_tool_rounds: Safety limit on tool-call rounds per turn.

    Returns:
        An :class:`AgenticResult` with the full message history and tool log.
    """
    router = ToolRouter(scenario.environment)

    # Build system prompt — optionally prepend skill content
    system_prompt = scenario.system_prompt
    if skill_content:
        # Strip YAML frontmatter (---\n...\n---) before injecting into prompt
        _sc = skill_content
        if _sc.startswith("---"):
            _end = _sc.find("\n---", 3)
            if _end != -1:
                _sc = _sc[_end + 4:].lstrip("\n")
        system_prompt = _sc + "\n\n---\n\n" + system_prompt

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    turn_responses: list[str] = []
    tools = STANDARD_TOOLS
    total_input_tokens = 0
    total_output_tokens = 0

    for turn_idx, turn in enumerate(scenario.turns, start=1):
        messages.append({"role": "user", "content": turn.content})

        # Tool-calling loop: the model may call tools multiple times
        # before producing a final text response for this turn.
        responded = False
        for _round in range(max_tool_rounds):
            try:
                response = await model.chat(messages, tools=tools)
            except Exception as exc:
                error_msg = f"Model error on turn {turn_idx}, round {_round + 1}: {exc}"
                logger.warning("Scenario %s: %s", scenario.id, error_msg)
                return AgenticResult(
                    scenario_id=scenario.id,
                    messages=messages,
                    tool_log=router.call_log,
                    turn_responses=turn_responses,
                    error=error_msg,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            total_input_tokens += response.input_tokens
            total_output_tokens += response.output_tokens

            if response.tool_calls:
                # Append the assistant message with tool calls
                messages.append(response.to_message())

                # Route each tool call through the simulated environment
                for tc in response.tool_calls:
                    result = router.handle(tc.name, tc.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
            else:
                # Model responded with text — turn is complete
                text = response.text or ""
                messages.append({"role": "assistant", "content": text})
                turn_responses.append(text)
                responded = True
                break

        if not responded:
            # Hit the safety limit — record what we have
            turn_responses.append(
                f"[SAFETY LIMIT] Agent made {max_tool_rounds} tool calls "
                f"without producing a text response on turn {turn_idx}."
            )

    return AgenticResult(
        scenario_id=scenario.id,
        messages=messages,
        tool_log=router.call_log,
        turn_responses=turn_responses,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )


async def run_agentic_benchmark(
    model_name: str,
    scenarios: list[AgenticScenario],
    skill_content: str | None = None,
    concurrency: int = 3,
    delay: float = 0.5,
    judge_model: str | None = None,
    *,
    progress: Progress | None = None,
    task_description: str | None = None,
) -> dict:
    """Run the agentic benchmark for a single model.

    Args:
        model_name: Name of the model to evaluate.
        scenarios: List of agentic scenarios.
        skill_content: Optional skill file content.
        concurrency: Max concurrent scenario evaluations.
        delay: Delay between scenario starts.
        judge_model: Optional model name for LLM-as-judge evaluation.
            When provided, text-based checkpoints that fail regex matching
            are re-evaluated by this model as a semantic fallback.
        progress: Optional shared ``rich.progress.Progress`` instance.
            When provided, a task is added to this instance instead of
            creating a new progress display.  This avoids multiple
            competing live displays when several benchmarks run in
            parallel.
        task_description: Label for the progress task.  Defaults to
            ``"Agentic eval: {model_name}"``.

    Returns:
        A result dict containing metadata and per-scenario scores.
    """
    from scam.models import create_model

    model = create_model(model_name)

    # Create judge if requested
    judge = None
    if judge_model:
        from scam.agentic.judge import JudgeEvaluator

        judge = JudgeEvaluator(judge_model)

    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    error_count = 0

    async def _run_one(scenario: AgenticScenario) -> dict:
        nonlocal error_count

        async with semaphore:
            if delay > 0:
                await asyncio.sleep(delay)

            try:
                result = await run_agentic_scenario(
                    model=model,
                    scenario=scenario,
                    skill_content=skill_content,
                )
            except Exception as exc:
                error_count += 1
                logger.warning("Scenario %s failed: %s", scenario.id, exc)
                return {
                    "scenario_id": scenario.id,
                    "category": scenario.category,
                    "difficulty": scenario.difficulty,
                    "error": str(exc),
                    "checkpoints": [],
                    "safety_score": 0.0,
                    "critical_failure": True,
                }

            if result.error:
                error_count += 1

            return await score_agentic(scenario, result, judge=judge)

    # Run evaluations with progress bar
    desc = task_description or f"Agentic eval: {model_name}"
    own_progress = progress is None

    if own_progress:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
        )
        progress.start()

    task = progress.add_task(desc, total=len(scenarios))

    try:
        async def _run_with_progress(scenario: AgenticScenario) -> dict:
            result = await _run_one(scenario)
            progress.advance(task)
            return result

        tasks = [_run_with_progress(s) for s in scenarios]
        results = await asyncio.gather(*tasks)
    finally:
        if own_progress:
            progress.stop()

    from scam.utils.config import calculate_cost, skill_hash as compute_skill_hash

    s_hash = compute_skill_hash(skill_content) if skill_content else "none"

    # Aggregate token usage across all scenarios
    total_input_tokens = sum(s.get("input_tokens", 0) for s in results)
    total_output_tokens = sum(s.get("output_tokens", 0) for s in results)
    actual_cost = calculate_cost(model_name, total_input_tokens, total_output_tokens)

    return {
        "metadata": {
            "model": model_name,
            "mode": "agentic",
            "skill_hash": s_hash,
            "judge_model": judge_model,
            "judge_enabled": judge_model is not None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_scenarios": len(scenarios),
            "completed_scenarios": len(scenarios) - error_count,
            "errored_scenarios": error_count,
            "incomplete": error_count > 0,
            "concurrency": concurrency,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "actual_cost": round(actual_cost, 6) if actual_cost is not None else None,
            "skill_content_preview": (
                (skill_content[:200] + "...") if skill_content and len(skill_content) > 200
                else skill_content
            ),
        },
        "scores": list(results),
    }
