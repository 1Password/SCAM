"""Tests for the replay viewer — scenario selection, rendering, and data loading."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from scam.agentic.replay import (
    _GAP_SEC,
    _THINK_SEC,
    _TOKEN_MS,
    _TOOL_EXEC_SEC,
    _TYPING_MS,
    _build_dangerous_set,
    _format_tool_call,
    _is_dangerous_call,
    _pretty_json,
    _stream_assistant,
    _stream_tool_result,
    _stream_user,
    _tokenize_words,
    _truncate,
    load_run,
    render_checkpoints,
    render_message,
    replay_scenario,
    select_scenario,
)


# ── Fixtures ──────────────────────────────────────────────────────


def _make_scenario(
    *,
    scenario_id: str = "test-scenario",
    safety_score: float = 0.0,
    critical_failure: bool = True,
    messages: list[dict] | None = None,
    tool_log: list[dict] | None = None,
    checkpoints: list[dict] | None = None,
) -> dict:
    """Build a minimal scenario score dict for testing."""
    return {
        "scenario_id": scenario_id,
        "category": "test_category",
        "difficulty": 3,
        "description": "Test scenario description",
        "safety_score": safety_score,
        "critical_failure": critical_failure,
        "turn_count": 2,
        "tool_call_count": 1,
        "dangerous_call_count": 1 if critical_failure else 0,
        "input_tokens": 100,
        "output_tokens": 50,
        "error": None,
        "checkpoints": checkpoints or [
            {
                "id": "check_1",
                "description": "Test checkpoint",
                "passed": not critical_failure,
                "weight": 5,
                "details": "test detail",
                "evaluated_by": "regex",
            }
        ],
        "turn_responses": ["Response 1"],
        "messages": messages or [
            {"role": "system", "content": "You are an AI assistant."},
            {"role": "user", "content": "Do something."},
            {
                "role": "assistant",
                "content": "Let me help.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "test_tool",
                            "arguments": '{"key": "value"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"result": "ok"}',
            },
            {"role": "assistant", "content": "Done."},
        ],
        "tool_log": tool_log or [
            {
                "tool": "test_tool",
                "arguments": {"key": "value"},
                "result": '{"result": "ok"}',
                "is_dangerous": False,
            }
        ],
    }


def _make_run(scores: list[dict] | None = None) -> dict:
    """Build a minimal run result dict."""
    return {
        "metadata": {
            "model": "test-model",
            "mode": "agentic",
            "skill_hash": "none",
            "timestamp": "2026-01-01T00:00:00Z",
            "total_scenarios": 3,
        },
        "scores": scores or [
            _make_scenario(scenario_id="pass-scenario", safety_score=1.0, critical_failure=False),
            _make_scenario(scenario_id="fail-scenario-1", safety_score=0.0),
            _make_scenario(scenario_id="fail-scenario-2", safety_score=0.43),
        ],
    }


# ── Truncation and formatting ─────────────────────────────────────


def test_truncate_short():
    """Short text is returned unchanged."""
    assert _truncate("line1\nline2", max_lines=5) == "line1\nline2"


def test_truncate_long():
    """Long text is truncated with indicator."""
    text = "\n".join(f"line{i}" for i in range(50))
    result = _truncate(text, max_lines=5)
    lines = result.split("\n")
    assert len(lines) == 6  # 5 lines + truncation indicator
    assert "truncated" in lines[-1]


def test_pretty_json_valid():
    """Valid JSON is pretty-printed."""
    raw = '{"a":1,"b":2}'
    result = _pretty_json(raw)
    assert '"a": 1' in result
    assert '"b": 2' in result


def test_pretty_json_invalid():
    """Invalid JSON is returned as-is."""
    raw = "not json"
    assert _pretty_json(raw) == raw


def test_format_tool_call_with_args():
    tc = {
        "function": {
            "name": "read_email",
            "arguments": '{"email_id": "email-1"}',
        }
    }
    result = _format_tool_call(tc)
    assert "read_email" in result
    assert "email-1" in result


def test_format_tool_call_no_args():
    tc = {
        "function": {"name": "list_emails", "arguments": "{}"},
    }
    result = _format_tool_call(tc)
    assert result == "list_emails()"


# ── Dangerous call detection ──────────────────────────────────────


def test_build_dangerous_set():
    tool_log = [
        {"tool": "open_url", "arguments": {"url": "https://evil.com"}, "is_dangerous": True},
        {"tool": "read_email", "arguments": {"email_id": "e1"}, "is_dangerous": False},
    ]
    ds = _build_dangerous_set(tool_log)
    assert len(ds) == 1
    assert ("open_url", json.dumps({"url": "https://evil.com"}, sort_keys=True)) in ds


def test_is_dangerous_call_match():
    ds = {("open_url", json.dumps({"url": "https://evil.com"}, sort_keys=True))}
    tc = {
        "function": {
            "name": "open_url",
            "arguments": '{"url": "https://evil.com"}',
        }
    }
    assert _is_dangerous_call(tc, ds) is True


def test_is_dangerous_call_no_match():
    ds = {("open_url", json.dumps({"url": "https://evil.com"}, sort_keys=True))}
    tc = {
        "function": {
            "name": "open_url",
            "arguments": '{"url": "https://safe.com"}',
        }
    }
    assert _is_dangerous_call(tc, ds) is False


# ── Scenario selector ─────────────────────────────────────────────


def test_select_scenario_worst_first():
    """Scenarios are sorted worst-first; picking #1 gives the lowest score."""
    run = _make_run()
    scores = run["scores"]
    console = Console(file=open("/dev/null", "w"))

    with patch.object(console, "input", return_value="1"):
        result = select_scenario(scores, console=console)

    assert result is not None
    assert result["safety_score"] == min(s["safety_score"] for s in scores)


def test_select_scenario_all_shown():
    """All scenarios are shown including perfect scores."""
    run = _make_run()
    scores = run["scores"]
    console = Console(file=open("/dev/null", "w"), record=True)

    with patch.object(console, "input", return_value="1"):
        select_scenario(scores, console=console)

    output = console.export_text()
    for s in scores:
        assert s["scenario_id"] in output


def test_select_scenario_empty():
    """Returns None when given an empty list."""
    console = Console(file=open("/dev/null", "w"))
    result = select_scenario([], console=console)
    assert result is None


# ── Data loading ──────────────────────────────────────────────────


def test_load_run_single_file():
    """Load from a single JSON file."""
    run = _make_run()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(run, f)
        f.flush()
        result = load_run(Path(f.name))
    assert result["metadata"]["model"] == "test-model"
    assert len(result["scores"]) == 3


def test_load_run_directory_single():
    """Load from a directory with one run file."""
    run = _make_run()
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "run-001.json"
        with open(path, "w") as f:
            json.dump(run, f)
        result = load_run(Path(td))
    assert result["metadata"]["model"] == "test-model"


def test_load_run_directory_multiple():
    """Load from a directory with multiple run files — picks user selection."""
    run = _make_run()
    with tempfile.TemporaryDirectory() as td:
        for i in range(1, 4):
            path = Path(td) / f"run-{i:03d}.json"
            with open(path, "w") as f:
                json.dump(run, f)

        console = Console(file=open("/dev/null", "w"))
        with patch.object(console, "input", return_value="2"):
            with patch("scam.agentic.replay.Console", return_value=console):
                result = load_run(Path(td))
    assert result["metadata"]["model"] == "test-model"


def test_load_run_empty_directory():
    """Raise error for empty directory."""
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FileNotFoundError):
            load_run(Path(td))


# ── Message rendering ─────────────────────────────────────────────


def test_render_system_message():
    """System messages render without crashing."""
    console = Console(file=open("/dev/null", "w"))
    msg = {"role": "system", "content": "System prompt line 1\nLine 2\nLine 3\nLine 4"}
    render_message(msg, console)  # Should not raise


def test_render_user_message():
    """User messages render without crashing."""
    console = Console(file=open("/dev/null", "w"))
    msg = {"role": "user", "content": "Hello, do something."}
    render_message(msg, console)


def test_render_assistant_text_only():
    """Assistant text-only messages render without crashing."""
    console = Console(file=open("/dev/null", "w"))
    msg = {"role": "assistant", "content": "Here is my response."}
    render_message(msg, console)


def test_render_assistant_with_tool_calls():
    """Assistant messages with tool calls render without crashing."""
    console = Console(file=open("/dev/null", "w"))
    msg = {
        "role": "assistant",
        "content": "Let me check.",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "list_emails", "arguments": "{}"},
            }
        ],
    }
    render_message(msg, console)


def test_render_dangerous_tool_call():
    """Dangerous tool calls get flagged."""
    console = Console(file=open("/dev/null", "w"))
    dangerous_set = {("open_url", json.dumps({"url": "https://evil.com"}, sort_keys=True))}
    msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "open_url",
                    "arguments": '{"url": "https://evil.com"}',
                },
            }
        ],
    }
    render_message(msg, console, dangerous_set=dangerous_set)


def test_render_tool_result():
    """Tool results render without crashing."""
    console = Console(file=open("/dev/null", "w"))
    msg = {
        "role": "tool",
        "tool_call_id": "call_abc12345",
        "content": '{"status": "ok"}',
    }
    render_message(msg, console)


def test_render_empty_content():
    """Messages with empty/None content don't crash."""
    console = Console(file=open("/dev/null", "w"))
    render_message({"role": "assistant", "content": None}, console)
    render_message({"role": "assistant", "content": ""}, console)
    render_message({"role": "user", "content": ""}, console)


# ── Checkpoint rendering ──────────────────────────────────────────


def test_render_checkpoints():
    """Checkpoint scorecard renders without crashing."""
    console = Console(file=open("/dev/null", "w"))
    scenario = _make_scenario(
        checkpoints=[
            {"id": "cp1", "description": "Check 1", "passed": True, "weight": 3, "details": "ok", "evaluated_by": "regex"},
            {"id": "cp2", "description": "Check 2", "passed": False, "weight": 10, "details": "failed", "evaluated_by": "tool_log"},
        ],
    )
    render_checkpoints(scenario, console)


# ── Full replay ───────────────────────────────────────────────────


def test_replay_scenario_runs():
    """Full replay completes without crashing (static path for non-terminal)."""
    console = Console(file=open("/dev/null", "w"))
    scenario = _make_scenario()
    replay_scenario(scenario, speed="fast", console=console)


def test_replay_empty_messages():
    """Replay with no messages doesn't crash."""
    console = Console(file=open("/dev/null", "w"))
    scenario = _make_scenario(messages=[])
    replay_scenario(scenario, speed="fast", console=console)


def test_replay_skips_system_prompts():
    """System messages should be skipped in replay."""
    console = Console(file=open("/dev/null", "w"), record=True)
    scenario = _make_scenario(messages=[
        {"role": "system", "content": "SECRET SYSTEM PROMPT"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ])
    replay_scenario(scenario, speed="fast", console=console)
    output = console.export_text()
    # System prompt content should NOT appear in the rendered output
    # (the static fallback for non-terminal still calls render_message
    # but skips system role in the loop)
    assert "SECRET SYSTEM PROMPT" not in output


def test_replay_system_only_messages():
    """Replay with only system messages shows 'no messages' warning."""
    console = Console(file=open("/dev/null", "w"), record=True)
    scenario = _make_scenario(messages=[
        {"role": "system", "content": "System prompt only"},
    ])
    replay_scenario(scenario, speed="fast", console=console)
    output = console.export_text()
    assert "No messages" in output


# ── Tokenizer ────────────────────────────────────────────────────


def test_tokenize_words_basic():
    """Tokenizer splits on word boundaries preserving trailing space."""
    tokens = _tokenize_words("Hello world! How are you?")
    # Each token is word + trailing whitespace
    assert tokens[0] == "Hello "
    assert tokens[-1] == "you?"
    assert len(tokens) == 5


def test_tokenize_words_empty():
    """Empty string returns empty list."""
    assert _tokenize_words("") == []


def test_tokenize_words_single():
    """Single word with no trailing space."""
    tokens = _tokenize_words("Hello")
    assert tokens == ["Hello"]


# ── Speed presets ────────────────────────────────────────────────


def test_speed_presets_consistency():
    """All timing dicts have entries for all three presets."""
    for preset in ("slow", "medium", "fast"):
        assert preset in _TYPING_MS
        assert preset in _TOKEN_MS
        assert preset in _THINK_SEC
        assert preset in _TOOL_EXEC_SEC
        assert preset in _GAP_SEC


def test_typing_speed_ordering():
    """Slow has higher ms/char than medium, which is higher than fast."""
    assert _TYPING_MS["slow"] > _TYPING_MS["medium"] > _TYPING_MS["fast"]


def test_token_speed_ordering():
    """Slow has higher ms/token than medium, which is higher than fast."""
    assert _TOKEN_MS["slow"] > _TOKEN_MS["medium"] > _TOKEN_MS["fast"]


# ── Streaming functions (static/non-terminal path) ──────────────


def test_stream_user_empty_content():
    """_stream_user with empty content renders without crashing."""
    console = Console(file=open("/dev/null", "w"))
    _stream_user("", console, "fast")


def test_stream_user_non_terminal():
    """_stream_user prints a panel when console is not a terminal."""
    console = Console(file=open("/dev/null", "w"), record=True)
    _stream_user("Hello, world!", console, "fast")
    output = console.export_text()
    # Content should appear in the static panel
    assert "Hello, world!" in output


def test_stream_assistant_non_terminal():
    """_stream_assistant renders text without crashing on non-terminal."""
    console = Console(file=open("/dev/null", "w"))
    _stream_assistant("I can help.", [], console, "fast", set())


def test_stream_assistant_with_tool_calls():
    """_stream_assistant handles tool calls without crashing."""
    console = Console(file=open("/dev/null", "w"))
    tcs = [{
        "id": "c1", "type": "function",
        "function": {"name": "read_email", "arguments": '{"id": 1}'},
    }]
    _stream_assistant("Let me check.", tcs, console, "fast", set())


def test_stream_assistant_dangerous():
    """_stream_assistant flags dangerous tool calls."""
    console = Console(file=open("/dev/null", "w"), record=True)
    ds = {("open_url", json.dumps({"url": "https://evil.com"}, sort_keys=True))}
    tcs = [{
        "id": "c1", "type": "function",
        "function": {"name": "open_url", "arguments": '{"url": "https://evil.com"}'},
    }]
    _stream_assistant("", tcs, console, "fast", ds)
    output = console.export_text()
    assert "DANGEROUS" in output


def test_stream_tool_result_non_terminal():
    """_stream_tool_result renders JSON result without crashing."""
    console = Console(file=open("/dev/null", "w"), record=True)
    _stream_tool_result('{"status": "ok"}', "call_abc123", console, "fast")
    output = console.export_text()
    assert "ok" in output
