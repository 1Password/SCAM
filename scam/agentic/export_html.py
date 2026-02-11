"""HTML export — generate self-contained replay pages from run JSON.

Produces two kinds of output:

* **Individual pages** — one per scenario (``{scenario-id}.html``)
* **Combined page** — sidebar navigation across all scenarios (``index.html``)

Everything is inlined (CSS, JS, data) so the files work offline with no
external dependencies.  The visual design is inspired by
https://developer.1password.com/docs/cli.
"""

from __future__ import annotations

import html
import json
from pathlib import Path


# ── Data preparation ─────────────────────────────────────────────────


def _format_tool_call(tc: dict) -> str:
    """Format a tool_call dict into ``name(arg=val, ...)``."""
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


def _build_dangerous_set(tool_log: list[dict]) -> set[tuple[str, str]]:
    """Build a set of (tool_name, args_json) tuples for dangerous calls."""
    dangerous: set[tuple[str, str]] = set()
    for entry in tool_log:
        if entry.get("is_dangerous"):
            args_key = json.dumps(entry.get("arguments", {}), sort_keys=True)
            dangerous.add((entry.get("tool", ""), args_key))
    return dangerous


def _is_dangerous_call(tc: dict, dangerous_set: set) -> bool:
    fn = tc.get("function", {})
    name = fn.get("name", "")
    args_raw = fn.get("arguments", "{}")
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        args_key = json.dumps(args, sort_keys=True)
    except (json.JSONDecodeError, TypeError):
        args_key = str(args_raw)
    return (name, args_key) in dangerous_set


def prepare_scenario_data(scenario: dict) -> dict:
    """Extract and structure data for HTML rendering.

    Returns a JSON-serializable dict suitable for embedding in a
    ``<script>`` tag.  Tool result messages are folded into the
    preceding assistant message's ``tool_calls`` entries so the
    output contains only ``user`` and ``assistant`` messages.
    """
    messages = scenario.get("messages", [])
    tool_log = scenario.get("tool_log", [])
    dangerous_set = _build_dangerous_set(tool_log)

    # Pre-build tool_call_id → pretty-printed result content
    tool_results: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") == "tool":
            tcid = msg.get("tool_call_id", "")
            content = msg.get("content", "")
            try:
                obj = json.loads(content)
                content = json.dumps(obj, indent=2)
                # Unescape newlines/tabs inside string values so they
                # render as real line-breaks in the <pre> display.
                # This text is only shown visually, never re-parsed.
                content = content.replace("\\n", "\n")
                content = content.replace("\\t", "\t")
            except (json.JSONDecodeError, TypeError):
                pass
            tool_results[tcid] = content

    prepared_messages: list[dict] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        # Skip system prompts and tool results (results folded into assistant)
        if role in ("system", "tool"):
            continue

        entry: dict = {"role": role, "content": msg.get("content") or ""}

        if role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                formatted: list[dict] = []
                for tc in tool_calls:
                    tcid = tc.get("id", "")
                    short_id = tcid[-8:] if len(tcid) > 8 else tcid
                    formatted.append({
                        "call_str": _format_tool_call(tc),
                        "dangerous": _is_dangerous_call(tc, dangerous_set),
                        "result": tool_results.get(tcid, ""),
                        "tool_call_id": short_id,
                    })
                entry["tool_calls"] = formatted

        prepared_messages.append(entry)

    # Merge consecutive tool-call-only assistant messages into one bubble
    merged: list[dict] = []
    for entry in prepared_messages:
        is_tc_only = (
            entry["role"] == "assistant"
            and not entry["content"].strip()
            and "tool_calls" in entry
        )
        if (
            is_tc_only
            and merged
            and merged[-1]["role"] == "assistant"
            and not merged[-1]["content"].strip()
            and "tool_calls" in merged[-1]
        ):
            merged[-1]["tool_calls"].extend(entry["tool_calls"])
        else:
            merged.append(entry)
    prepared_messages = merged

    return {
        "scenario_id": scenario.get("scenario_id", "unknown"),
        "description": scenario.get("description", ""),
        "category": scenario.get("category", ""),
        "difficulty": scenario.get("difficulty", 0),
        "safety_score": scenario.get("safety_score", 0),
        "critical_failure": scenario.get("critical_failure", False),
        "turn_count": scenario.get("turn_count", 0),
        "tool_call_count": scenario.get("tool_call_count", 0),
        "dangerous_call_count": scenario.get("dangerous_call_count", 0),
        "checkpoints": scenario.get("checkpoints", []),
        "messages": prepared_messages,
    }


# ── HTML generation ──────────────────────────────────────────────────

_CSS = """\
:root {
  --bg: #f9f9fb;
  --surface: #ffffff;
  --sidebar-bg: #0f1117;
  --sidebar-hover: rgba(255,255,255,0.05);
  --sidebar-active-bg: rgba(99,138,255,0.22);
  --sidebar-active-border: #7ba0ff;
  --sidebar-text: #8b8fa3;
  --sidebar-text-bright: #e0e2ea;
  --accent: #0572EC;
  --accent-soft: #e8f2fd;
  --text: #1a1c23;
  --text-secondary: #71757e;
  --text-tertiary: #a0a4ad;
  --border: #ebedf0;
  --border-light: #f3f4f6;
  --code-bg: #1a1c25;
  --code-text: #cfd1d8;
  --pass: #0d9668;
  --pass-bg: #edfcf5;
  --pass-border: #8adcc0;
  --fail: #dc3545;
  --fail-bg: #fef2f3;
  --fail-border: #f5a3aa;
  --warn: #c87617;
  --warn-bg: #fefaec;
  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --mono: 'JetBrains Mono', 'SF Mono', SFMono-Regular, ui-monospace, Menlo, monospace;
  --radius: 10px;
  --radius-sm: 6px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 15px; }
body {
  font-family: var(--font);
  color: var(--text);
  background: var(--bg);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ── Layout ── */
.layout { display: flex; min-height: 100vh; }
.sidebar {
  width: 272px; min-width: 180px; max-width: 480px;
  background: var(--sidebar-bg);
  color: var(--sidebar-text);
  padding: 20px 0;
  position: fixed;
  top: 0; left: 0; bottom: 0;
  overflow-y: auto;
  z-index: 10;
  border-right: 1px solid rgba(255,255,255,0.06);
}
.sidebar::-webkit-scrollbar { width: 4px; }
.sidebar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 4px; }
.sidebar-resize {
  position: absolute; top: 0; right: 0; bottom: 0; width: 8px;
  cursor: col-resize; z-index: 20;
  transform: translateX(50%);
}
.sidebar-resize::after {
  content: ''; position: absolute; top: 0; bottom: 0;
  left: 3px; width: 2px;
  transition: background 0.12s;
}
.sidebar-resize:hover::after, .sidebar-resize.dragging::after {
  background: var(--accent);
}
.sidebar h2 {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 0 20px;
  margin-bottom: 12px;
  color: #555a6b;
  font-weight: 600;
}
.sidebar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px 9px 20px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: background 0.12s;
  border-left: 2px solid transparent;
}
.sidebar-item:hover { background: var(--sidebar-hover); }
.sidebar-item.active {
  background: var(--sidebar-active-bg);
  border-left-color: var(--sidebar-active-border);
  color: #fff;
  font-weight: 600;
}
.sidebar-item.active .name {
  color: #fff;
}
.sidebar-item .score-badge {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 9px;
  flex-shrink: 0;
}
.sidebar-item .name {
  flex: 1; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-weight: 450;
}
.sidebar-item .diff {
  font-size: 0.65rem;
  color: #555a6b;
  flex-shrink: 0;
  font-weight: 500;
}

.content {
  flex: 1;
  max-width: 760px;
  margin: 0 auto;
  padding: 32px 28px 100px;
}
.content.with-sidebar {
  margin-left: 272px;
  margin-right: auto;
  padding-left: 48px;
}

/* ── Run header ── */
.run-header {
  background: var(--sidebar-bg);
  color: #fff;
  padding: 20px 28px;
  border-radius: var(--radius);
  margin-bottom: 28px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.run-header-icon {
  width: 36px; height: 36px;
  background: rgba(99,138,255,0.15);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  flex-shrink: 0;
}
.run-header-text { flex: 1; min-width: 0; }
.run-header-text h1 { font-size: 1.15rem; font-weight: 600; line-height: 1.3; }
.run-header-text .meta { font-size: 0.78rem; color: #71757e; margin-top: 2px; }
.run-header-text .meta span + span::before { content: "\\00b7"; margin: 0 8px; }
.run-header-right { flex-shrink: 0; }
.run-tag {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  letter-spacing: 0.01em;
}
.skill-tag { background: rgba(99,138,255,0.15); color: #a3bcff; }
.baseline-tag { background: rgba(255,255,255,0.08); color: #71757e; }

/* ── Scenario header ── */
.scenario-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border);
}
.scenario-header .left { flex: 1; min-width: 0; }
.scenario-header h2 {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.scenario-header .diff-badge {
  font-size: 0.65rem;
  background: var(--border);
  color: var(--text-secondary);
  padding: 1px 7px;
  border-radius: 9px;
  font-weight: 600;
}
.scenario-header .desc {
  color: var(--text-secondary);
  margin-top: 4px;
  font-size: 0.85rem;
  line-height: 1.5;
}
.scenario-header .score-pill {
  font-size: 1.5rem;
  font-weight: 700;
  flex-shrink: 0;
  padding: 4px 0;
  text-align: right;
}
.scenario-header .score-pill-label {
  display: block;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-tertiary);
  margin-bottom: 2px;
}

/* ── Recording stage ── */
.recording-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 56px 32px;
  margin-bottom: 24px;
  background: linear-gradient(145deg, #f8f9fb 0%, #eef1f5 100%);
  border: 1px dashed var(--border);
  border-radius: var(--radius);
}
.stage-icon {
  width: 72px; height: 72px;
  display: flex; align-items: center; justify-content: center;
  background: var(--accent);
  color: #fff;
  border-radius: 50%;
  margin-bottom: 16px;
  box-shadow: 0 4px 20px rgba(5, 114, 236, 0.25);
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}
.stage-icon:hover {
  transform: scale(1.06);
  box-shadow: 0 6px 28px rgba(5, 114, 236, 0.35);
}
.stage-title {
  font-size: 1.05rem; font-weight: 700; color: var(--text);
  margin-bottom: 4px;
}
.stage-sub {
  font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 20px;
}
.stage-actions {
  display: flex; gap: 10px; align-items: center;
}

/* ── Video export command snippet ── */
.video-cmd {
  margin-top: 18px; width: 100%; max-width: 560px;
}
.video-cmd-label {
  font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.05em;
  color: #94a3b8; margin-bottom: 5px; font-weight: 600;
}
.video-cmd-box {
  display: flex; align-items: center; gap: 8px;
  background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px;
  padding: 8px 12px; cursor: pointer; transition: border-color 0.15s;
}
.video-cmd-box:hover { border-color: #94a3b8; }
.video-cmd-box code {
  flex: 1; font-family: 'SF Mono','Fira Code','Consolas',monospace;
  font-size: 0.72rem; color: #334155; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.video-cmd-copy {
  font-size: 0.68rem; font-weight: 600; color: var(--accent);
  white-space: nowrap; flex-shrink: 0;
}

.btn-play-lg {
  display: inline-flex; align-items: center;
  padding: 10px 28px; border-radius: 8px; border: none;
  background: var(--accent); color: #fff;
  font-family: var(--font); font-size: 0.92rem; font-weight: 700;
  cursor: pointer; transition: background 0.12s, transform 0.1s;
}
.btn-play-lg:hover { background: #0461c8; transform: translateY(-1px); }
.btn-ghost {
  display: inline-flex; align-items: center;
  padding: 10px 20px; border-radius: 8px;
  border: 1px solid var(--border); background: transparent;
  font-family: var(--font); font-size: 0.85rem; font-weight: 600;
  color: var(--text-secondary); cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.btn-ghost:hover { background: var(--border-light); color: var(--text); }

/* ── Inline controls (during/after playback) ── */
.inline-controls {
  display: flex; gap: 8px; align-items: center; margin-bottom: 16px;
}

/* ── Controls ── */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  border-radius: var(--radius-sm);
  font-family: var(--font);
  cursor: pointer;
  transition: all 0.12s;
  font-weight: 500;
}
.btn-play {
  background: var(--accent);
  color: #fff;
  padding: 9px 20px;
  font-size: 0.85rem;
  font-weight: 600;
}
.btn-play:hover { background: #0461c8; }
.btn-secondary {
  background: var(--border-light);
  color: var(--text-secondary);
  padding: 9px 16px;
  font-size: 0.82rem;
}
.btn-secondary:hover { background: var(--border); color: var(--text); }

/* ── Chat thread ── */
.chat-thread { display: flex; flex-direction: column; }

/* ── Messages ── */
.message {
  display: flex;
  gap: 14px;
  padding: 20px 0;
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.message + .message { border-top: 1px solid var(--border-light); }
.message.visible { opacity: 1; transform: translateY(0); }
.message.static-mode { opacity: 1; transform: none; transition: none; }

/* Avatars — small, clean */
.avatar {
  width: 28px; height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.avatar svg { width: 16px; height: 16px; }
.message.user .avatar { background: #e8ecf1; }
.message.assistant .avatar { background: var(--accent-soft); transition: background 0.35s ease; }
.message.assistant.dangerous .avatar { background: var(--fail-bg); }

/* Danger alert animation */
@keyframes danger-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(220,53,69,0.45); }
  40%  { box-shadow: 0 0 0 10px rgba(220,53,69,0); }
  100% { box-shadow: 0 0 0 0 rgba(220,53,69,0); }
}
@keyframes danger-shake {
  0%, 100% { transform: translateX(0); }
  15%  { transform: translateX(-4px); }
  30%  { transform: translateX(4px); }
  45%  { transform: translateX(-3px); }
  60%  { transform: translateX(3px); }
  75%  { transform: translateX(-1px); }
  90%  { transform: translateX(1px); }
}
.message.danger-alert {
  animation: danger-shake 0.5s ease;
}
.message.danger-alert .avatar {
  animation: danger-pulse 0.8s ease;
}

/* Content */
.msg-content { flex: 1; min-width: 0; }
.msg-sender {
  font-size: 0.78rem;
  font-weight: 600;
  margin-bottom: 3px;
  color: var(--text);
  display: flex;
  align-items: center;
}
.msg-sender .danger-tag {
  background: var(--fail);
  color: #fff;
  font-size: 0.6rem;
  padding: 1px 5px;
  border-radius: 3px;
  margin-left: auto;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  font-weight: 700;
}

.msg-body {
  font-size: 0.88rem;
  line-height: 1.7;
  color: var(--text);
  word-wrap: break-word;
  overflow-wrap: break-word;
}

/* ── Markdown ── */
.msg-body p { margin-bottom: 0.6em; }
.msg-body p:last-child { margin-bottom: 0; }
.msg-body strong { font-weight: 600; }
.msg-body em { font-style: italic; }
.msg-body ul, .msg-body ol { padding-left: 1.3em; margin-bottom: 0.6em; }
.msg-body li { margin-bottom: 0.2em; }
.msg-body li::marker { color: var(--text-tertiary); }
.msg-body code {
  font-family: var(--mono);
  background: #f0f1f4;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.84em;
}
.msg-body pre {
  background: var(--code-bg);
  color: var(--code-text);
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
  margin: 8px 0;
  font-size: 0.8rem;
  line-height: 1.55;
}
.msg-body pre code { background: none; padding: 0; font-size: inherit; color: inherit; }
.msg-body h1, .msg-body h2, .msg-body h3 {
  font-weight: 700;
  margin: 1em 0 0.4em;
  line-height: 1.35;
  color: var(--text);
}
.msg-body h1 { font-size: 1.2em; }
.msg-body h2 { font-size: 1.08em; }
.msg-body h3 { font-size: 0.98em; }
.msg-body *:first-child { margin-top: 0; }
.msg-body hr { border: none; border-top: 1px solid var(--border); margin: 1em 0; }
.msg-body blockquote {
  border-left: 3px solid var(--border);
  padding-left: 12px;
  color: var(--text-secondary);
  margin: 0.5em 0;
}
/* Tables */
.msg-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.6em 0;
  font-size: 0.84em;
}
.msg-body thead th {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 2px solid var(--border);
  font-weight: 600;
  font-size: 0.85em;
  color: var(--text-secondary);
}
.msg-body tbody td {
  padding: 5px 10px;
  border-bottom: 1px solid var(--border-light);
  vertical-align: top;
}
.msg-body tbody tr:last-child td { border-bottom: none; }

/* ── Tool call accordion ── */
.tc-list { margin-top: 12px; display: flex; flex-direction: column; gap: 4px; }
.tc-accordion {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--surface);
}
.tc-accordion.dangerous { border-color: var(--fail-border); }
.tc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  cursor: pointer;
  user-select: none;
  transition: background 0.1s;
  font-size: 0.78rem;
}
.tc-header:hover { background: var(--border-light); }
.tc-accordion.dangerous .tc-header:hover { background: var(--fail-bg); }
.tc-arrow {
  font-size: 0.55rem;
  transition: transform 0.15s;
  color: var(--text-tertiary);
  flex-shrink: 0;
}
.tc-accordion.open .tc-arrow { transform: rotate(90deg); }
.tc-name {
  font-family: var(--mono);
  font-size: 0.76rem;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
}
.tc-accordion.dangerous .tc-name { color: var(--fail); }
.tc-status { flex-shrink: 0; display: flex; align-items: center; font-size: 0.8rem; }
.tc-body { display: none; border-top: 1px solid var(--border); }
.tc-accordion.open .tc-body { display: block; }
.tc-accordion.dangerous .tc-body { border-top-color: var(--fail-border); }

/* JSON */
.json-output {
  background: var(--code-bg);
  color: var(--code-text);
  font-family: var(--mono);
  font-size: 0.75rem;
  padding: 12px 14px;
  overflow-x: auto;
  white-space: pre;
  max-height: 300px;
  overflow-y: auto;
  line-height: 1.55;
}
.json-output .json-key { color: #7ec8e3; }
.json-output .json-string { color: #87c9a5; }
.json-output .json-number { color: #e8a0bf; }
.json-output .json-bool { color: #e0c777; }
.json-output .json-null { color: #71757e; font-style: italic; }

/* ── Animations ── */
.cursor {
  display: inline-block;
  width: 2px; height: 1em;
  background: var(--accent);
  vertical-align: text-bottom;
  animation: blink 0.8s step-end infinite;
  margin-left: 1px;
}
@keyframes blink { 50% { opacity: 0; } }

.spinner {
  display: inline-block;
  width: 14px; height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.thinking-dots span {
  animation: dotpulse 1.4s infinite;
  display: inline-block;
  width: 6px; height: 6px;
  background: var(--text-tertiary);
  border-radius: 50%;
  margin-right: 4px;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; margin-right: 0; }
@keyframes dotpulse {
  0%, 80%, 100% { opacity: 0.25; transform: scale(0.85); }
  40% { opacity: 1; transform: scale(1); }
}

/* ── Checkpoints ── */
.checkpoints {
  margin-top: 36px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.cp-header {
  padding: 14px 20px;
  background: var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.cp-header h3 { font-size: 0.85rem; font-weight: 600; }
.cp-header .score-tag { font-size: 0.85rem; font-weight: 700; }
.cp-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 20px;
  font-size: 0.82rem;
  border-top: 1px solid var(--border-light);
}
.cp-row:first-of-type { border-top: 1px solid var(--border); }
.cp-icon {
  flex-shrink: 0;
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  margin-top: 1px;
}
.cp-icon svg { width: 16px; height: 16px; }
.cp-icon.pass svg { color: var(--pass); }
.cp-icon.fail svg { color: var(--fail); }
.cp-info { flex: 1; min-width: 0; }
.cp-info .cp-title {
  font-size: 0.82rem;
  color: var(--text);
  font-weight: 600;
  line-height: 1.4;
}
.cp-info .cp-explanation {
  color: var(--text-tertiary);
  font-size: 0.78rem;
  margin-top: 4px;
  line-height: 1.5;
}
.cp-verdict {
  flex-shrink: 0;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 2px 8px;
  border-radius: 4px;
  margin-top: 1px;
}
.cp-verdict.pass { color: var(--pass); background: #e6ffec; }
.cp-verdict.fail { color: var(--fail); background: #ffeef0; }
.critical-banner {
  background: var(--fail-bg);
  border-top: 1px solid var(--fail-border);
  color: var(--fail);
  padding: 10px 20px;
  font-weight: 600;
  font-size: 0.82rem;
}

.score-green { color: var(--pass); }
.score-yellow { color: var(--warn); }
.score-red { color: var(--fail); }

/* ── Responsive ── */
@media (max-width: 900px) {
  .sidebar { display: none; }
  .content.with-sidebar { margin-left: 0; }
}
"""

_JS = """\
(function() {
  "use strict";

  // ── State ─────────────────────────────────────────────────
  let currentScenarioIdx = 0;
  let playing = false;
  let abortController = null;
  let hasPlayed = false;

  const TYPING_MS  = 28;
  const TOKEN_MS   = 35;
  const THINK_MS   = 1000;
  const TOOL_MS    = 1200;
  const GAP_MS     = 500;
  const USER_THINK = 1200;

  // ── Smooth auto-scroll ────────────────────────────────────
  // Lerp-based RAF scroller: continuously tracks a target element
  // so content that grows (typing, expanding accordions) is followed
  // smoothly without competing native smooth-scroll animations.
  var _sc = (function() {
    var container = null;   // null → window scroll
    var raf = null;
    var el = null;          // element being followed

    function getY()  { return container ? container.scrollTop : (window.pageYOffset || document.documentElement.scrollTop); }
    function setY(y) { if (container) container.scrollTop = y; else window.scrollTo(0, y); }
    function vh()    { return container ? container.clientHeight : window.innerHeight; }
    function vTop()  { return container ? container.getBoundingClientRect().top : 0; }

    function tick() {
      if (!el) { raf = null; return; }
      var rect = el.getBoundingClientRect();
      var h = vh();
      var pad = Math.min(80, h * 0.15);        // comfort zone at bottom
      var bottom = rect.bottom - vTop();        // element bottom relative to viewport/container
      var cur = getY();

      if (bottom > h - pad) {                   // element extends below comfort zone
        var diff = cur + (bottom - (h - pad)) - cur;
        if (diff > 0.5) {
          setY(cur + Math.max(1, diff * 0.15)); // lerp 15% per frame → ~250ms to 90%
        }
      }
      raf = requestAnimationFrame(tick);
    }

    return {
      setContainer: function(c) { container = c; },
      follow: function(target) {
        el = target;
        if (!raf) raf = requestAnimationFrame(tick);
      },
      stop: function() {
        el = null;
        if (raf) { cancelAnimationFrame(raf); raf = null; }
      },
      jump: function(y) {
        this.stop();
        setY(y);
      }
    };
  })();
  window.__setScrollContainer = function(c) { _sc.setContainer(c); };

  // ── Helpers ───────────────────────────────────────────────
  function sleep(ms) {
    return new Promise((resolve, reject) => {
      const id = setTimeout(resolve, ms);
      if (abortController) {
        abortController.signal.addEventListener("abort", () => {
          clearTimeout(id);
          reject(new DOMException("Aborted", "AbortError"));
        });
      }
    });
  }

  function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function scoreColor(s) {
    if (s >= 0.8) return "score-green";
    if (s >= 0.5) return "score-yellow";
    return "score-red";
  }

  function scoreBadgeBg(s) {
    if (s >= 0.8) return "background:#edfcf5;color:#0d9668;";
    if (s >= 0.5) return "background:#fefaec;color:#c87617;";
    return "background:#fef2f3;color:#dc3545;";
  }

  // ── Inline markdown formatting ──────────────────────────
  function inlineFmt(s) {
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\\*\\*\\*(.+?)\\*\\*\\*/g, '<strong><em>$1</em></strong>');
    s = s.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
    s = s.replace(/\\*(.+?)\\*/g, '<em>$1</em>');
    s = s.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g,
      '<a href="$2" target="_blank" rel="noopener" style="color:var(--accent);">$1</a>');
    return s;
  }

  // ── Block-level markdown renderer (line-by-line) ────────
  function renderMarkdown(text) {
    if (!text) return "";
    var h = escHtml(text);
    var lines = h.split('\\n');
    var result = [];
    var i = 0;
    var inCode = false;
    var codeBuf = [];

    while (i < lines.length) {
      var line = lines[i];

      if (/^```/.test(line)) {
        if (inCode) {
          result.push('<pre><code>' + codeBuf.join('\\n') + '</code></pre>');
          codeBuf = [];
          inCode = false;
        } else {
          inCode = true;
        }
        i++; continue;
      }
      if (inCode) { codeBuf.push(line); i++; continue; }

      if (/^\\d+[.)] /.test(line)) {
        var olItems = [];
        var curItem = inlineFmt(lines[i].replace(/^\\d+[.)] /, ''));
        i++;
        while (i < lines.length) {
          if (/^\\d+[.)] /.test(lines[i])) {
            olItems.push('<li>' + curItem + '</li>');
            curItem = inlineFmt(lines[i].replace(/^\\d+[.)] /, ''));
            i++;
          } else if (lines[i].trim() === '') {
            // blank line — peek ahead, continue list if next non-blank is numbered
            var peek = i + 1;
            while (peek < lines.length && lines[peek].trim() === '') peek++;
            if (peek < lines.length && /^\\d+[.)] /.test(lines[peek])) {
              i = peek;
            } else {
              break;
            }
          } else if (/^```/.test(lines[i]) || /^#{1,3} /.test(lines[i]) || /^[-*+] /.test(lines[i])) {
            break;
          } else {
            // continuation line — append to current item
            curItem += '<br>' + inlineFmt(lines[i]);
            i++;
          }
        }
        olItems.push('<li>' + curItem + '</li>');
        result.push('<ol>' + olItems.join('') + '</ol>');
        continue;
      }

      if (/^[-*+] /.test(line)) {
        var ulItems = [];
        var curItem = inlineFmt(lines[i].replace(/^[-*+] /, ''));
        i++;
        while (i < lines.length) {
          if (/^[-*+] /.test(lines[i])) {
            ulItems.push('<li>' + curItem + '</li>');
            curItem = inlineFmt(lines[i].replace(/^[-*+] /, ''));
            i++;
          } else if (lines[i].trim() === '') {
            var peek = i + 1;
            while (peek < lines.length && lines[peek].trim() === '') peek++;
            if (peek < lines.length && /^[-*+] /.test(lines[peek])) {
              i = peek;
            } else {
              break;
            }
          } else if (/^```/.test(lines[i]) || /^#{1,3} /.test(lines[i]) || /^\\d+[.)] /.test(lines[i])) {
            break;
          } else {
            curItem += '<br>' + inlineFmt(lines[i]);
            i++;
          }
        }
        ulItems.push('<li>' + curItem + '</li>');
        result.push('<ul>' + ulItems.join('') + '</ul>');
        continue;
      }

      if (/^### /.test(line)) { result.push('<h3>' + inlineFmt(line.slice(4)) + '</h3>'); i++; continue; }
      if (/^## /.test(line))  { result.push('<h2>' + inlineFmt(line.slice(3)) + '</h2>'); i++; continue; }
      if (/^# /.test(line))   { result.push('<h1>' + inlineFmt(line.slice(2)) + '</h1>'); i++; continue; }

      if (/^-{3,}$/.test(line.trim())) { result.push('<hr>'); i++; continue; }

      if (/^&gt; /.test(line)) {
        result.push('<blockquote>' + inlineFmt(line.slice(5)) + '</blockquote>');
        i++; continue;
      }

      // Table: line starts with | and next line is a separator row
      if (/^\\|/.test(line) && i + 1 < lines.length && /^\\|[-\\s|:]+\\|$/.test(lines[i + 1].trim())) {
        var headerCells = line.split('|').filter(function(c, ci, arr) { return ci > 0 && ci < arr.length - 1; });
        i += 2; // skip header + separator
        var rows = [];
        while (i < lines.length && /^\\|/.test(lines[i])) {
          var cells = lines[i].split('|').filter(function(c, ci, arr) { return ci > 0 && ci < arr.length - 1; });
          rows.push(cells);
          i++;
        }
        var tbl = '<table><thead><tr>';
        headerCells.forEach(function(c) { tbl += '<th>' + inlineFmt(c.trim()) + '</th>'; });
        tbl += '</tr></thead><tbody>';
        rows.forEach(function(row) {
          tbl += '<tr>';
          row.forEach(function(c) { tbl += '<td>' + inlineFmt(c.trim()) + '</td>'; });
          tbl += '</tr>';
        });
        tbl += '</tbody></table>';
        result.push(tbl);
        continue;
      }

      if (line.trim() === '') { result.push(''); i++; continue; }

      result.push(inlineFmt(line));
      i++;
    }

    if (inCode && codeBuf.length) {
      result.push('<pre><code>' + codeBuf.join('\\n') + '</code></pre>');
    }

    var out = [];
    var pBuf = [];
    for (var j = 0; j < result.length; j++) {
      var r = result[j];
      if (r === '') {
        if (pBuf.length) { out.push('<p>' + pBuf.join('<br>') + '</p>'); pBuf = []; }
        continue;
      }
      if (/^<(h[1-3]|ul|ol|pre|blockquote|hr|table)/.test(r)) {
        if (pBuf.length) { out.push('<p>' + pBuf.join('<br>') + '</p>'); pBuf = []; }
        out.push(r);
      } else {
        pBuf.push(r);
      }
    }
    if (pBuf.length) { out.push('<p>' + pBuf.join('<br>') + '</p>'); }

    return out.join('');
  }

  // ── JSON syntax highlighter ───────────────────────────────
  function highlightJson(text) {
    if (!text) return "";
    var h = escHtml(text);
    h = h.replace(/&quot;([^&]*?)&quot;\\s*:/g,
      '<span class="json-key">&quot;$1&quot;</span>:');
    h = h.replace(/:\\s*&quot;([^&]*?)&quot;/g,
      ': <span class="json-string">&quot;$1&quot;</span>');
    h = h.replace(/(\\[|,)\\s*&quot;([^&]*?)&quot;/g,
      '$1 <span class="json-string">&quot;$2&quot;</span>');
    h = h.replace(/:\\s*(-?\\d+\\.?\\d*)/g,
      ': <span class="json-number">$1</span>');
    h = h.replace(/:\\s*(true|false)/g,
      ': <span class="json-bool">$1</span>');
    h = h.replace(/:\\s*(null)/g,
      ': <span class="json-null">$1</span>');
    return h;
  }

  // ── Accordion toggle ──────────────────────────────────────
  function toggleTc(header) {
    header.closest('.tc-accordion').classList.toggle('open');
  }

  // ── SVG icons ────────────────────────────────────────────
  const ICON_USER = '<svg viewBox="0 0 24 24" fill="none" stroke="#5a6270" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
  const ICON_BOT  = '<svg viewBox="0 0 24 24" fill="none" stroke="#0572EC" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>';
  const ICON_WARN = '<svg viewBox="0 0 24 24" fill="none" stroke="#dc3545" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>';

  // ── Render scenario ───────────────────────────────────────
  function renderScenario(idx) {
    stop();
    currentScenarioIdx = idx;
    hasPlayed = false;
    const sc = window.__SCAM_DATA__.scenarios[idx];
    const container = document.getElementById("scenario-content");

    // In dashboard mode, sidebar highlighting is handled by showScenario()
    var isDashboard = !!(window.__SCAM_DATA__.sections && window.__SCAM_DATA__.sections.length);
    if (!isDashboard) {
      document.querySelectorAll(".sidebar-item").forEach((el, i) => {
        el.classList.toggle("active", i === idx);
      });
    }

    const sc_color = scoreColor(sc.safety_score);
    const pct = Math.round(sc.safety_score * 100);

    let h = `<div class="scenario-header">
      <div class="left">
        <h2>${escHtml(sc.scenario_id)} <span class="diff-badge">D${sc.difficulty}</span></h2>
        <div class="desc">${escHtml(sc.description)}</div>
      </div>
      <div class="score-pill ${sc_color}"><span class="score-pill-label">Safety</span>${pct}%</div>
    </div>`;

    h += `<div class="recording-stage" id="recording-stage">
      <div class="stage-icon" onclick="window.__play()">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <polygon points="6 3 20 12 6 21" fill="currentColor"/>
        </svg>
      </div>
      <div class="stage-title">Agent Recording</div>
      <div class="stage-sub">${sc.messages.length} messages &middot; ${sc.tool_call_count} tool calls${sc.dangerous_call_count > 0 ? ' &middot; <span style="color:var(--fail);">' + sc.dangerous_call_count + ' dangerous</span>' : ''}</div>
      <div class="stage-actions">
        <button class="btn btn-play-lg" onclick="window.__play()">&#9654;&ensp;Play Recording</button>
        <button class="btn btn-ghost" onclick="window.__showStatic()">Show Transcript</button>
      </div>
      <div id="video-cmd" class="video-cmd" style="display:none;"></div>
    </div>`;

    h += `<div class="inline-controls" id="inline-controls" style="display:none;">
      <div id="inline-phase-toggle" style="display:inline-flex;"></div>
      <button class="btn btn-play" id="btn-play" onclick="window.__play()" style="display:none;">&#8635; Replay</button>
      <button class="btn btn-secondary" id="btn-skip" onclick="window.__showStatic()" style="display:none;">Skip to End</button>
      <span id="watch-other" style="display:none;"></span>
    </div>`;

    h += `<div class="chat-thread" id="messages-container" style="display:none;">`;
    sc.messages.forEach((msg, i) => {
      h += renderMessageHTML(msg, i);
    });
    h += `</div>`;

    h += `<div id="checkpoints-wrap" style="display:none;">`;
    h += renderCheckpointsHTML(sc);
    h += `</div>`;

    container.innerHTML = h;
    _sc.jump(0);
  }

  // ── Mark a message element as dangerous (avatar + tag + accordions) ──
  function markDangerous(el, animate) {
    if (el.classList.contains("dangerous")) return;
    el.classList.add("dangerous");
    // Upgrade avatar
    el.querySelector(".avatar").innerHTML = ICON_WARN;
    // Add sender tag
    const sender = el.querySelector(".msg-sender");
    if (sender && !sender.querySelector(".danger-tag")) {
      sender.insertAdjacentHTML("beforeend", '<span class="danger-tag">Failed Benchmark</span>');
    }
    // Upgrade all dangerous accordion items and auto-expand them
    el.querySelectorAll('.tc-accordion[data-dangerous="1"]').forEach(function(acc) {
      acc.classList.add("dangerous");
      acc.classList.add("open");
      var nameEl = acc.querySelector(".tc-name");
      if (nameEl && nameEl.textContent.indexOf("\\u26A0") !== 0) {
        nameEl.textContent = "\\u26A0 " + nameEl.textContent;
      }
    });
    // Attention animation
    if (animate) {
      el.classList.add("danger-alert");
      el.addEventListener("animationend", function handler() {
        el.classList.remove("danger-alert");
        el.removeEventListener("animationend", handler);
      });
    }
  }

  // ── Message rendering (user + assistant only) ─────────────
  function renderMessageHTML(msg, idx) {
    const role = msg.role;
    const cls = "message " + role;
    const senderLabel = role === "user" ? "You" : "Assistant";

    let bodyInner = '<span class="msg-text"></span>';

    if (role === "assistant" && msg.tool_calls && msg.tool_calls.length) {
      bodyInner += '<div class="tc-list" style="display:none;">';
      msg.tool_calls.forEach(function(tc, ti) {
        const dangerAttr = tc.dangerous ? ' data-dangerous="1"' : "";
        bodyInner += '<div class="tc-accordion" id="msg-' + idx + '-tc-' + ti + '"' + dangerAttr + ' style="display:none;">'
          + '<div class="tc-header" onclick="window.__toggleTc(this)">'
          + '<span class="tc-arrow">\\u25B6</span>'
          + '<span class="tc-name">' + escHtml(tc.call_str) + '</span>'
          + '<span class="tc-status"></span>'
          + '</div>'
          + '<div class="tc-body">'
          + '<div class="json-output">' + highlightJson(tc.result || "") + '</div>'
          + '</div></div>';
      });
      bodyInner += '</div>';
    }

    const avatarIcon = role === "user" ? ICON_USER : ICON_BOT;

    return '<div class="' + cls + '" id="msg-' + idx + '" data-idx="' + idx + '">'
      + '<div class="avatar">' + avatarIcon + '</div>'
      + '<div class="msg-content">'
      + '<div class="msg-sender">' + senderLabel + '</div>'
      + '<div class="msg-body">' + bodyInner + '</div>'
      + '</div></div>';
  }

  function _cleanCheckpointDetail(detail, passed) {
    if (!detail) return "";
    var d = detail;
    // Extract judge reasoning from patterns like "no match found (judge concurred: [judge] ...)"
    var judgeMatch = d.match(/\\(judge concurred:\\s*\\[judge\\]\\s*(.*?)\\)$/);
    if (judgeMatch) return judgeMatch[1].trim();
    // Extract standalone judge reasoning "[judge] ..."
    if (d.indexOf("[judge] ") === 0) return d.substring(8).trim();
    // Clean up tool_log results: "agent called tool_name({...})"
    var toolMatch = d.match(/^agent called (\\w+)\\((.+)\\)$/s);
    if (toolMatch) {
      var toolName = toolMatch[1].replace(/_/g, " ");
      // Try to summarize common dangerous actions
      if (toolName === "send email" || toolName === "reply to email" || toolName === "forward email") {
        try {
          var args = JSON.parse(toolMatch[2]);
          if (args.to) return "The agent sent an email to " + args.to + ".";
          return "The agent sent an email.";
        } catch(e) {}
        return "The agent sent an email despite the risk.";
      }
      if (toolName === "fill form") {
        return "The agent submitted credentials on a form.";
      }
      if (toolName === "open url") {
        try {
          var args2 = JSON.parse(toolMatch[2]);
          if (args2.url) return "The agent navigated to " + args2.url;
          return "The agent navigated to the URL.";
        } catch(e2) {}
        return "The agent navigated to a suspicious URL.";
      }
      if (toolName === "post content") {
        return "The agent posted sensitive content publicly.";
      }
      return "The agent called " + toolName + ".";
    }
    // Clean up simple regex matches: "matched: 'phishing'"
    if (d.indexOf("matched:") === 0) {
      return passed ? "The agent flagged the threat." : "";
    }
    if (d.indexOf("warned instead of refusing:") === 0) {
      return "The agent warned about the threat but did not refuse outright.";
    }
    // Tool log "no dangerous X calls found"
    if (d.indexOf("no dangerous") === 0 && d.indexOf("calls found") > 0) {
      return passed ? "The agent avoided the dangerous action." : "";
    }
    if (d.indexOf("no refusal or warning found") === 0) {
      var inner = d.match(/\\(judge concurred:\\s*\\[judge\\]\\s*(.*?)\\)$/);
      if (inner) return inner[1].trim();
      return "The agent did not refuse or flag the suspicious request.";
    }
    if (d.indexOf("no match found") === 0) {
      var inner2 = d.match(/\\(judge concurred:\\s*\\[judge\\]\\s*(.*?)\\)$/);
      if (inner2) return inner2[1].trim();
      return passed ? "" : "The agent did not detect the threat.";
    }
    return d;
  }

  function renderCheckpointsHTML(sc) {
    const pct = Math.round(sc.safety_score * 100);
    const sc_color = scoreColor(sc.safety_score);

    const passIcon = '<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clip-rule="evenodd"/></svg>';
    const failIcon = '<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd"/></svg>';

    let h = `<div class="checkpoints">`;
    h += `<div class="cp-header"><h3>Safety Checkpoints</h3><span class="score-tag ${sc_color}">${pct}% safety</span></div>`;

    (sc.checkpoints || []).forEach(cp => {
      const cls = cp.passed ? "pass" : "fail";
      const icon = cp.passed ? passIcon : failIcon;
      const verdict = cp.passed ? "Passed" : "Failed";
      const explanation = _cleanCheckpointDetail(cp.details || "", cp.passed);

      h += `<div class="cp-row">
        <div class="cp-icon ${cls}">${icon}</div>
        <div class="cp-info">
          <div class="cp-title">${escHtml(cp.description || "")}</div>
          ${explanation ? '<div class="cp-explanation">' + escHtml(explanation) + '</div>' : ''}
        </div>
        <span class="cp-verdict ${cls}">${verdict}</span>
      </div>`;
    });

    if (sc.critical_failure) {
      h += `<div class="critical-banner">Critical failure &mdash; safety score ${pct}%</div>`;
    }
    h += `</div>`;
    return h;
  }

  // ── Animation engine ──────────────────────────────────────
  function _showChatThread() {
    var stage = document.getElementById("recording-stage");
    var thread = document.getElementById("messages-container");
    var controls = document.getElementById("inline-controls");
    if (stage) stage.style.display = "none";
    if (thread) thread.style.display = "";
    if (controls) controls.style.display = "";
  }

  async function play() {
    if (playing) return;

    // If replaying, re-render the scenario to reset DOM state
    if (hasPlayed) {
      renderScenario(currentScenarioIdx);
      // Re-inject dashboard-level decorations (phase toggles etc.)
      if (typeof window.__onReplay === "function") window.__onReplay();
    }

    _showChatThread();
    playing = true;
    abortController = new AbortController();

    document.getElementById("btn-play").style.display = "none";
    document.getElementById("btn-skip").style.display = "";

    const sc = window.__SCAM_DATA__.scenarios[currentScenarioIdx];
    const msgs = sc.messages;
    let prevRole = null;

    try {
      for (let i = 0; i < msgs.length; i++) {
        const msg = msgs[i];
        const el = document.getElementById("msg-" + i);
        if (!el) continue;

        const textEl = el.querySelector(".msg-text");
        const content = msg.content || "";

        // Gap between messages
        if (msg.role === "user" && prevRole === "assistant") {
          await sleep(USER_THINK);
        } else if (i > 0) {
          await sleep(GAP_MS);
        }

        el.classList.add("visible");
        _sc.follow(el);

        if (msg.role === "user") {
          // Typing animation
          const chars = content.split("");
          const cap = Math.min(chars.length, 300);
          for (let c = 0; c < chars.length; c++) {
            if (c < cap) {
              textEl.innerHTML = escHtml(content.substring(0, c + 1)) + '<span class="cursor"></span>';
              let d = TYPING_MS * (0.5 + Math.random());
              if (chars[c] === " " || chars[c] === "\\n") d *= 2;
              else if (".,;:!?".includes(chars[c])) d *= 3;
              await sleep(d);
            } else {
              textEl.textContent = content;
              break;
            }
          }
          textEl.textContent = content;

        } else if (msg.role === "assistant") {
          const tcList = el.querySelector(".tc-list");
          const hasTc = msg.tool_calls && msg.tool_calls.length > 0;

          // Thinking dots
          textEl.innerHTML = '<span class="thinking-dots"><span></span><span></span><span></span></span>';
          await sleep(THINK_MS);

          // Stream text if present
          if (content) {
            const tokens = content.match(/\\S+\\s*/g) || [];
            const cap = Math.min(tokens.length, 120);
            let shown = "";
            for (let t = 0; t < tokens.length; t++) {
              shown += tokens[t];
              if (t < cap) {
                textEl.innerHTML = renderMarkdown(shown) + '<span class="cursor"></span>';
                let d = TOKEN_MS * (0.8 + Math.random() * 0.4);
                const stripped = tokens[t].trim();
                if (stripped && ".!?:".includes(stripped[stripped.length - 1])) d *= 2.5;
                await sleep(d);
              } else {
                textEl.innerHTML = renderMarkdown(content);
                break;
              }
            }
            textEl.innerHTML = renderMarkdown(content);
          } else {
            textEl.innerHTML = "";
          }

          // Animate tool calls one by one
          if (hasTc && tcList) {
            tcList.style.display = "";
            for (let ti = 0; ti < msg.tool_calls.length; ti++) {
              const tc = msg.tool_calls[ti];
              const tcEl = document.getElementById("msg-" + i + "-tc-" + ti);
              if (!tcEl) continue;

              // Reveal accordion header with spinner
              tcEl.style.display = "";
              const statusEl = tcEl.querySelector(".tc-status");
              statusEl.innerHTML = '<span class="spinner"></span>';
              _sc.follow(tcEl);

              await sleep(TOOL_MS);

              // Replace spinner with checkmark
              statusEl.innerHTML = '<span style="color:var(--pass);">\\u2713</span>';

              // Mark message as dangerous once a dangerous call resolves
              if (tc.dangerous) {
                markDangerous(el, true);
              }
            }
          }
        }

        prevRole = msg.role;
      }
    } catch (e) {
      if (e.name !== "AbortError") throw e;
    }

    playing = false;
    hasPlayed = true;
    _sc.stop();
    var cpw = document.getElementById("checkpoints-wrap");
    if (cpw) {
      cpw.style.display = "";
      // Briefly follow the checkpoints so they scroll into view
      _sc.follow(cpw);
      setTimeout(function() { _sc.stop(); }, 600);
    }
    const pb = document.getElementById("btn-play");
    if (pb) { pb.innerHTML = "&#8635; Replay"; pb.style.display = ""; }
    const sk = document.getElementById("btn-skip");
    if (sk) sk.style.display = "none";
    if (typeof window.__onPlaybackDone === "function") window.__onPlaybackDone();
  }

  function stop() {
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    playing = false;
    _sc.stop();
    const playBtn = document.getElementById("btn-play");
    const skipBtn = document.getElementById("btn-skip");
    if (playBtn) playBtn.style.display = "";
    if (skipBtn) skipBtn.style.display = "none";
  }

  function showStatic() {
    stop();
    _showChatThread();
    const sc = window.__SCAM_DATA__.scenarios[currentScenarioIdx];
    sc.messages.forEach(function(msg, i) {
      const el = document.getElementById("msg-" + i);
      if (!el) return;
      el.classList.add("visible", "static-mode");
      const textEl = el.querySelector(".msg-text");

      if (msg.role === "user") {
        textEl.textContent = msg.content || "";
      } else if (msg.role === "assistant") {
        textEl.innerHTML = renderMarkdown(msg.content || "");

        // Mark dangerous if any tool call is dangerous
        if (msg.tool_calls && msg.tool_calls.some(function(tc) { return tc.dangerous; })) {
          markDangerous(el);
        }

        // Reveal all tool call accordions (collapsed, clickable)
        const tcList = el.querySelector(".tc-list");
        if (tcList) {
          tcList.style.display = "";
          tcList.querySelectorAll(".tc-accordion").forEach(function(acc) {
            acc.style.display = "";
            const st = acc.querySelector(".tc-status");
            if (st) st.innerHTML = '<span style="color:var(--pass);">\\u2713</span>';
          });
        }
      }
    });

    // Show checkpoints and replay button, hide skip
    var cpw = document.getElementById("checkpoints-wrap");
    if (cpw) cpw.style.display = "";
    hasPlayed = true;
    const pb = document.getElementById("btn-play");
    if (pb) { pb.innerHTML = "&#8635; Replay"; pb.style.display = ""; }
    const sk2 = document.getElementById("btn-skip");
    if (sk2) sk2.style.display = "none";
    if (typeof window.__onPlaybackDone === "function") window.__onPlaybackDone();
  }

  // ── Sidebar navigation ────────────────────────────────────
  function initSidebar() {
    document.querySelectorAll(".sidebar-item").forEach((el, i) => {
      el.addEventListener("click", () => renderScenario(i));
    });
  }

  // ── Init ──────────────────────────────────────────────────
  window.__play = play;
  window.__stop = stop;
  window.__showStatic = showStatic;
  window.__toggleTc = toggleTc;
  window.__renderScenario = renderScenario;

  document.addEventListener("DOMContentLoaded", () => {
    var data = window.__SCAM_DATA__ || {};
    var isDashboard = !!(data.sections && data.sections.length);

    // In dashboard mode the dashboard extension manages sidebar clicks.
    if (!isDashboard) {
      initSidebar();
    }

    // Only auto-render when we have a top-level scenarios array (single-export).
    if (data.scenarios && data.scenarios.length > 0) {
      renderScenario(0);
    }
  });
})();
"""


def _score_color_class(score: float) -> str:
    if score >= 0.8:
        return "score-green"
    if score >= 0.5:
        return "score-yellow"
    return "score-red"


def _score_badge_style(score: float) -> str:
    if score >= 0.8:
        return "background:#edfcf5;color:#0d9668;"
    if score >= 0.5:
        return "background:#fefaec;color:#c87617;"
    return "background:#fef2f3;color:#dc3545;"


def generate_html(
    scenarios: list[dict],
    metadata: dict,
    *,
    combined: bool = True,
) -> str:
    """Generate a self-contained HTML replay page.

    Args:
        scenarios: List of prepared scenario dicts (from
            :func:`prepare_scenario_data`).
        metadata: Run metadata dict (model, timestamp, etc.).
        combined: If True, generates a sidebar+content layout for
            multi-scenario navigation.  If False, generates a
            single-scenario page.
    """
    model = metadata.get("model", "unknown")
    timestamp = metadata.get("timestamp", "")
    if "T" in str(timestamp):
        timestamp = str(timestamp).split("T")[0]
    total = metadata.get("total_scenarios", len(scenarios))
    judge = metadata.get("judge_model", "")

    # Sort scenarios worst-first for sidebar
    sorted_scenarios = sorted(scenarios, key=lambda s: s.get("safety_score", 0))

    data_json = json.dumps(
        {"scenarios": sorted_scenarios, "metadata": metadata},
        indent=None,
        default=str,
    )

    sidebar_html = ""
    if combined and len(scenarios) > 1:
        n_fail = sum(1 for s in scenarios if s.get("safety_score", 1) < 1.0)
        sidebar_html = '<div class="sidebar">\n'
        sidebar_html += (
            f'  <h2>{n_fail} failed &middot; {len(scenarios)} total</h2>\n'
        )
        for i, sc in enumerate(sorted_scenarios):
            pct = round(sc["safety_score"] * 100)
            style = _score_badge_style(sc["safety_score"])
            active = " active" if i == 0 else ""
            sidebar_html += (
                f'  <div class="sidebar-item{active}" data-idx="{i}">\n'
                f'    <span class="name">{html.escape(sc["scenario_id"])}</span>\n'
                f'    <span class="diff">D{sc["difficulty"]}</span>\n'
                f'    <span class="score-badge" style="{style}">{pct}%</span>\n'
                f'  </div>\n'
            )
        sidebar_html += '</div>\n'

    content_cls = "content with-sidebar" if (combined and len(scenarios) > 1) else "content"

    skill_hash = metadata.get("skill_hash", "none")
    has_skill = skill_hash and skill_hash != "none"

    meta_parts = []
    if timestamp:
        meta_parts.append(f"<span>{html.escape(str(timestamp))}</span>")
    meta_parts.append(f"<span>{total} scenarios</span>")
    if judge:
        meta_parts.append(f"<span>Judge: {html.escape(judge)}</span>")

    skill_html = ""
    if has_skill:
        short_hash = html.escape(str(skill_hash)[:12])
        skill_html = (
            f'<span class="run-tag skill-tag">Skill &middot; {short_hash}</span>'
        )
    else:
        skill_html = '<span class="run-tag baseline-tag">No skill (baseline)</span>'

    header_html = f"""<div class="run-header">
  <div class="run-header-icon">&#9881;</div>
  <div class="run-header-text">
    <h1>{html.escape(model)}</h1>
    <div class="meta">{''.join(meta_parts)}</div>
  </div>
  <div class="run-header-right">{skill_html}</div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SCAM Replay &mdash; {html.escape(model)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{_CSS}
</style>
</head>
<body>
<div class="layout">
{sidebar_html}
<div class="{content_cls}">
{header_html}
<div id="scenario-content"></div>
</div>
</div>
<script>
window.__SCAM_DATA__ = {data_json};
</script>
<script>
{_JS}
</script>
</body>
</html>"""


def generate_single_html(scenario: dict, metadata: dict) -> str:
    """Generate a standalone HTML page for a single scenario."""
    return generate_html([scenario], metadata, combined=False)


def generate_combined_html(scenarios: list[dict], metadata: dict) -> str:
    """Generate a combined HTML page with sidebar navigation."""
    return generate_html(scenarios, metadata, combined=True)


# ── File export ──────────────────────────────────────────────────────


def export_scenarios(
    run_data: dict,
    output_dir: Path,
    *,
    scenario_id: str | None = None,
    combined_only: bool = False,
) -> list[Path]:
    """Export HTML replay files from run data.

    Args:
        run_data: Loaded run JSON dict.
        output_dir: Directory to write HTML files into.
        scenario_id: If set, export only this scenario.
        combined_only: If True, skip individual scenario files.

    Returns:
        List of paths to written files.
    """
    metadata = run_data.get("metadata", {})
    scores = run_data.get("scores", [])

    if scenario_id:
        scores = [s for s in scores if s.get("scenario_id") == scenario_id]
        if not scores:
            raise ValueError(f"Scenario '{scenario_id}' not found in run data")

    prepared = [prepare_scenario_data(s) for s in scores]
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Individual scenario pages
    if not combined_only:
        for sc_data in prepared:
            sid = sc_data["scenario_id"]
            page = generate_single_html(sc_data, metadata)
            path = output_dir / f"{sid}.html"
            path.write_text(page, encoding="utf-8")
            written.append(path)

    # Combined index page (only if multiple scenarios or explicitly requested)
    if len(prepared) > 1 or combined_only:
        page = generate_combined_html(prepared, metadata)
        path = output_dir / "index.html"
        path.write_text(page, encoding="utf-8")
        written.append(path)

    return written


# ── V2 dashboard export ──────────────────────────────────────────────

import re as _re


def _short_model(name: str) -> str:
    """Shorten model names by dropping date suffixes."""
    return _re.sub(r"-\d{8}$", "", name)


def _build_dashboard_data(
    result: dict,
    *,
    model: str | None = None,
    phase: str | None = None,
    scenario_id: str | None = None,
) -> dict:
    """Build the data structure for the v2 dashboard.

    Returns a dict with ``metadata``, ``summary``, ``models``, and ``sections``.
    Each section is a model+phase group with prepared scenario data.
    """
    meta = result.get("metadata", {})
    models_data = result.get("models", {})
    result_summary = result.get("summary", {})

    sections: list[dict] = []

    for model_name, phases in models_data.items():
        if model and model_name != model:
            continue
        for phase_name, phase_data in phases.items():
            if phase and phase_name != phase:
                continue

            phase_summary = phase_data.get("summary", {})
            runs = phase_data.get("runs", [])
            if not runs:
                continue

            # Use first run for scenario data
            first_run = runs[0]
            scenarios = first_run.get("scenarios", [])

            if scenario_id:
                scenarios = [
                    s for s in scenarios
                    if s.get("scenario_id") == scenario_id
                ]

            prepared = [prepare_scenario_data(s) for s in scenarios]
            # Sort worst-first
            prepared.sort(key=lambda s: s.get("safety_score", 0))

            short = _short_model(model_name)
            phase_label = "baseline" if phase_name == "no-skill" else f"skill: {phase_name}"

            sections.append({
                "id": f"{model_name}_{phase_name}",
                "label": f"{short} — {phase_label}",
                "model": model_name,
                "short_model": short,
                "phase": phase_name,
                "phase_label": phase_label,
                "mean_score": phase_summary.get("mean_safety_score", 0),
                "critical_failures": phase_summary.get("critical_failure_count", 0),
                "n_runs": len(runs),
                "scenarios": prepared,
            })

    return {
        "metadata": meta,
        "summary": result_summary,
        "models": models_data,
        "sections": sections,
    }


def _score_bg(score: float) -> str:
    """CSS background for a score cell in the heatmap."""
    if score >= 1.0:
        return "background:#d1fae5;color:#065f46;"
    if score >= 0.8:
        return "background:#ecfdf5;color:#047857;"
    if score >= 0.5:
        return "background:#fefce8;color:#92400e;"
    if score >= 0.2:
        return "background:#fff1f2;color:#9f1239;"
    return "background:#fecdd3;color:#881337;"


def _delta_html(delta: float) -> str:
    """Render a delta value as colored HTML."""
    if delta > 0:
        return f'<span class="delta-pos">+{delta:.0%}</span>'
    if delta < 0:
        return f'<span class="delta-neg">{delta:+.0%}</span>'
    return '<span class="delta-zero">+0%</span>'


def _bar_html(value: float, color: str = "var(--accent)") -> str:
    """Render a horizontal percentage bar."""
    pct = max(0, min(100, round(value * 100)))
    return (
        f'<div class="bar-track">'
        f'<div class="bar-fill" style="width:{pct}%;background:{color};"></div>'
        f'</div>'
    )


def _generate_summary_html(
    result_summary: dict,
    meta: dict,
    models_data: dict | None = None,
) -> str:
    """Generate the comprehensive summary dashboard HTML."""
    leaderboard = result_summary.get("leaderboard", [])
    command = meta.get("command", "run")
    is_evaluate = command == "evaluate"
    timestamp = meta.get("timestamp", "")
    if "T" in str(timestamp):
        timestamp = str(timestamp).split("T")[0]
    models_data = models_data or {}

    p: list[str] = []

    # ── Hero header ──────────────────────────────────────────────
    skill = meta.get("skill_file") or "none"
    n_models = len(meta.get("models", []))
    n_scenarios = meta.get("scenario_count", "?")
    n_runs = meta.get("runs_per_phase", 1)

    # Compute aggregate stats
    avg_improvement = 0
    if is_evaluate and leaderboard:
        avg_improvement = sum(e.get("delta", 0) for e in leaderboard) / len(leaderboard)
    best_skill = max((e.get("skill", e.get("score", 0)) for e in leaderboard), default=0) if leaderboard else 0

    skill_html = html.escape(skill)
    if meta.get("skill_text"):
        skill_html = f'<a href="#" class="skill-link" onclick="window.__showSkillModal();return false;">{skill_html}</a>'
    else:
        skill_html = f"<strong>{skill_html}</strong>"

    bench_ref = meta.get("benchmark_ref", meta.get("benchmark_version", ""))
    bench_dirty = meta.get("benchmark_dirty", False)
    bench_tagged = meta.get("benchmark_tagged", False)
    if bench_ref:
        if bench_tagged and not bench_dirty:
            ver_tag = f'<span class="bench-ver bench-release">v{html.escape(bench_ref)}</span>'
        elif bench_dirty:
            ver_tag = f'<span class="bench-ver bench-dirty" title="Results from a dirty working tree — scenario files may differ from the tagged release">v{html.escape(bench_ref)}</span>'
        else:
            ver_tag = f'<span class="bench-ver bench-dev" title="Results from an untagged or development commit">v{html.escape(bench_ref)}</span>'
        ver_tag += " &middot; "
    else:
        ver_tag = ""

    p.append(f"""<div class="dash-hero">
  <div class="dash-hero-text">
    <h1>SCAM Benchmark Results</h1>
    <p class="dash-hero-sub">{ver_tag}{html.escape(command)} &middot; {html.escape(str(timestamp))} &middot; Skill: {skill_html}</p>
  </div>
</div>""")

    # ── Executive summary ──────────────────────────────────────────
    if is_evaluate:
        method_desc = (
            "</p><p>This evaluation runs each scenario twice per model: "
            "once without any guidance (<strong>baseline</strong>) and once with "
            "a security skill prepended to the system prompt (<strong>skill</strong>). "
            "The difference measures how much targeted instructions improve safety."
        )
    else:
        method_desc = ""
    p.append(f"""<div class="exec-summary">
  <p><strong>SCAM</strong> (Security Comprehension Awareness Measure) is an open benchmark
  that tests whether AI agents protect users when they have access to real-world tools
  like email, credential stores, and web forms.</p>
  <p>Unlike static classification benchmarks, every scenario here is a multi-turn
  conversation where the agent must independently recognize a threat, warn the user,
  and refuse to carry out dangerous actions. Scenarios cover phishing, social engineering,
  credential exposure, e-commerce scams, data leakage, and multi-stage
  attacks.{method_desc}</p>
</div>""")

    # ── KPI cards ────────────────────────────────────────────────
    p.append('<div class="kpi-row">')

    p.append(f'<div class="kpi-card"><div class="kpi-value">{n_models}</div><div class="kpi-label">Models</div></div>')
    p.append(f'<div class="kpi-card"><div class="kpi-value">{n_scenarios}</div><div class="kpi-label">Scenarios</div></div>')
    p.append(f'<div class="kpi-card"><div class="kpi-value">{n_runs}</div><div class="kpi-label">Runs / Phase</div></div>')

    if is_evaluate and avg_improvement:
        imp_cls = "kpi-good" if avg_improvement > 0 else "kpi-bad"
        p.append(f'<div class="kpi-card"><div class="kpi-value {imp_cls}">{avg_improvement:+.0%}</div><div class="kpi-label">Avg Improvement</div></div>')

    if best_skill:
        bs_cls = "kpi-good" if best_skill >= 0.8 else ""
        p.append(f'<div class="kpi-card"><div class="kpi-value {bs_cls}">{best_skill:.0%}</div><div class="kpi-label">Best Score</div></div>')

    p.append('</div>')

    # ── Leaderboard ──────────────────────────────────────────────
    if leaderboard:
        p.append('<div class="dash-section"><h2>Leaderboard</h2>')
        model_names = meta.get("models", [])

        if is_evaluate:
            for rank, entry in enumerate(leaderboard, 1):
                mn = entry["model"]
                short = _short_model(mn)
                bl = entry.get("baseline", 0)
                sk = entry.get("skill", 0)
                delta = entry.get("delta", 0)
                bl_crit = entry.get("baseline_critical_failures", 0)
                sk_crit = entry.get("skill_critical_failures", 0)
                sk_cls = _score_color_class(sk)

                # Get multi-run data for this model
                bl_phase = models_data.get(mn, {}).get("no-skill", {})
                sk_phase_name = next((k for k in models_data.get(mn, {}) if k != "no-skill"), None)
                sk_phase = models_data.get(mn, {}).get(sk_phase_name, {}) if sk_phase_name else {}
                bl_summary = bl_phase.get("summary", {})
                sk_summary = sk_phase.get("summary", {})

                bl_std = bl_summary.get("std_safety_score", 0)
                sk_std = sk_summary.get("std_safety_score", 0)
                bl_ci = bl_summary.get("ci_95", [])
                sk_ci = sk_summary.get("ci_95", [])
                bl_runs = bl_summary.get("per_run_scores", [])
                sk_runs = sk_summary.get("per_run_scores", [])
                n_phase_runs = len(bl_runs) or 1

                # Quantitative reproducibility metrics (baseline and skill)
                bl_per = bl_summary.get("per_scenario", {})
                sk_per = sk_summary.get("per_scenario", {})

                bl_stds = [v.get("std", 0) for v in bl_per.values()]
                sk_stds = [v.get("std", 0) for v in sk_per.values()]
                bl_mean_sigma = sum(bl_stds) / len(bl_stds) if bl_stds else 0
                sk_mean_sigma = sum(sk_stds) / len(sk_stds) if sk_stds else 0
                bl_max_sigma = max(bl_stds) if bl_stds else 0
                sk_max_sigma = max(sk_stds) if sk_stds else 0
                bl_pct_determ = sum(1 for s in bl_stds if s == 0) / len(bl_stds) if bl_stds else 0
                sk_pct_determ = sum(1 for s in sk_stds if s == 0) / len(sk_stds) if sk_stds else 0

                p.append(f"""<div class="lb-card">
  <div class="lb-rank">#{rank}</div>
  <div class="lb-body">
    <div class="lb-name">{html.escape(short)}</div>
    <div class="lb-bars">
      <div class="lb-bar-group">
        <span class="lb-bar-label">Baseline</span>
        {_bar_html(bl, '#94a3b8')}
        <span class="lb-bar-value">{bl:.0%}{f' <span class="lb-ci">&plusmn;{bl_std:.2f}</span>' if bl_std else ''}</span>
      </div>
      <div class="lb-bar-group">
        <span class="lb-bar-label">Skill</span>
        {_bar_html(sk, '#0d9668' if sk >= 0.8 else '#c87617' if sk >= 0.5 else '#dc3545')}
        <span class="lb-bar-value {sk_cls}">{sk:.0%}{f' <span class="lb-ci">&plusmn;{sk_std:.2f}</span>' if sk_std else ''}</span>
      </div>
    </div>
    <div class="lb-stats">
      <span class="lb-stat">{_delta_html(delta)} improvement</span>
      <span class="lb-stat">Crit failures: {bl_crit:.0f} &rarr; {sk_crit:.0f}</span>""")

                if bl_ci:
                    p.append(f'      <span class="lb-stat">Baseline 95% CI: [{max(0, bl_ci[0]):.0%}, {min(1, bl_ci[1]):.0%}]</span>')
                if sk_ci:
                    p.append(f'      <span class="lb-stat">Skill 95% CI: [{max(0, sk_ci[0]):.0%}, {min(1, sk_ci[1]):.0%}]</span>')

                if n_phase_runs > 1:
                    # Quantitative reproducibility comparison
                    sigma_improve_cls = "delta-pos" if sk_mean_sigma < bl_mean_sigma else "delta-neg" if sk_mean_sigma > bl_mean_sigma else "delta-zero"
                    determ_improve_cls = "delta-pos" if sk_pct_determ > bl_pct_determ else "delta-neg" if sk_pct_determ < bl_pct_determ else "delta-zero"
                    p.append(f"""    </div>
    <div class="repro-section">
      <div class="repro-title">Reproducibility ({n_phase_runs} runs &times; {len(sk_per) or len(bl_per)} scenarios)</div>
      <table class="repro-table">
        <thead><tr><th></th><th>Baseline</th><th>Skill</th><th>Change</th></tr></thead>
        <tbody>
          <tr>
            <td class="repro-label">Mean &sigma; across scenarios</td>
            <td>{bl_mean_sigma:.3f}</td>
            <td>{sk_mean_sigma:.3f}</td>
            <td class="{sigma_improve_cls}">{sk_mean_sigma - bl_mean_sigma:+.3f}</td>
          </tr>
          <tr>
            <td class="repro-label">Max &sigma; (worst-case)</td>
            <td>{bl_max_sigma:.3f}</td>
            <td>{sk_max_sigma:.3f}</td>
            <td class="{sigma_improve_cls}">{sk_max_sigma - bl_max_sigma:+.3f}</td>
          </tr>
          <tr>
            <td class="repro-label">Deterministic (&sigma;=0)</td>
            <td>{bl_pct_determ:.0%}</td>
            <td>{sk_pct_determ:.0%}</td>
            <td class="{determ_improve_cls}">{sk_pct_determ - bl_pct_determ:+.0%}</td>
          </tr>
        </tbody>
      </table>
    </div>""")

                    if sk_runs:
                        bl_runs_dots = " ".join(
                            f'<span class="run-dot" style="{_score_bg(s)}" title="Run {i+1}: {s:.0%}">{s:.0%}</span>'
                            for i, s in enumerate(bl_runs)
                        ) if bl_runs else ""
                        sk_runs_dots = " ".join(
                            f'<span class="run-dot" style="{_score_bg(s)}" title="Run {i+1}: {s:.0%}">{s:.0%}</span>'
                            for i, s in enumerate(sk_runs)
                        )
                        p.append(f'    <div class="lb-runs">')
                        if bl_runs_dots:
                            p.append(f'      <div class="lb-runs-row"><span class="lb-runs-label">Baseline runs:</span> {bl_runs_dots}</div>')
                        p.append(f'      <div class="lb-runs-row"><span class="lb-runs-label">Skill runs:</span> {sk_runs_dots}</div>')
                        p.append(f'    </div>')
                else:
                    # Single run, no reproducibility data
                    pass

                p.append('  </div>\n</div>')
        else:
            # run command — single phase
            for rank, entry in enumerate(leaderboard, 1):
                mn = entry["model"]
                short = _short_model(mn)
                score = entry.get("score", 0)
                crit = entry.get("critical_failures", 0)
                s_cls = _score_color_class(score)
                bar_color = '#0d9668' if score >= 0.8 else '#c87617' if score >= 0.5 else '#dc3545'

                p.append(f"""<div class="lb-card">
  <div class="lb-rank">#{rank}</div>
  <div class="lb-body">
    <div class="lb-name">{html.escape(short)}</div>
    <div class="lb-bars">
      <div class="lb-bar-group">
        <span class="lb-bar-label">Score</span>
        {_bar_html(score, bar_color)}
        <span class="lb-bar-value {s_cls}">{score:.0%}</span>
      </div>
    </div>
    <div class="lb-stats">
      <span class="lb-stat">Critical failures: {crit:.0f}</span>
    </div>
  </div>
</div>""")

        p.append('</div>')

    # ── Per-model detail cards ───────────────────────────────────
    if is_evaluate and models_data:
        model_names = meta.get("models", [])
        p.append('<div class="dash-section"><h2>Per-Model Breakdown</h2>')

        for mn in model_names:
            phases = models_data.get(mn, {})
            short = _short_model(mn)

            bl_phase = phases.get("no-skill", {})
            sk_phase_name = next((k for k in phases if k != "no-skill"), None)
            sk_phase = phases.get(sk_phase_name, {}) if sk_phase_name else {}
            bl_summary = bl_phase.get("summary", {})
            sk_summary = sk_phase.get("summary", {})
            bl_per = bl_summary.get("per_scenario", {})
            sk_per = sk_summary.get("per_scenario", {})

            p.append(f'<div class="model-detail-card"><h3>{html.escape(short)}</h3>')
            p.append('<table class="detail-table"><thead><tr>')
            p.append('<th>Scenario</th><th>Baseline</th><th>Skill</th><th>Delta</th>')
            p.append('<th>Failure Rate <span class="info-tip" data-tip="Percentage of runs where the agent critically failed this scenario — i.e. executed a dangerous action without any warning. Shown as baseline → skill.">&#9432;</span></th>')
            p.append('</tr></thead><tbody>')

            all_sids = list(dict.fromkeys(list(bl_per.keys()) + list(sk_per.keys())))
            all_sids.sort(key=lambda sid: sk_per.get(sid, {}).get("mean", 0))

            for sid in all_sids:
                bl_s = bl_per.get(sid, {})
                sk_s = sk_per.get(sid, {})
                bl_mean = bl_s.get("mean", 0)
                sk_mean = sk_s.get("mean", 0)
                delta = sk_mean - bl_mean
                bl_crit_sc = bl_s.get("critical_failure_rate", 0)
                sk_crit_sc = sk_s.get("critical_failure_rate", 0)

                # Color the failure rate transition
                if bl_crit_sc == 0 and sk_crit_sc == 0:
                    crit_cls = "crit-clear"
                elif sk_crit_sc == 0 and bl_crit_sc > 0:
                    crit_cls = "crit-fixed"
                elif sk_crit_sc < bl_crit_sc:
                    crit_cls = "crit-improved"
                elif sk_crit_sc > bl_crit_sc:
                    crit_cls = "crit-worse"
                else:
                    crit_cls = "crit-unchanged"

                bl_c = f'{bl_crit_sc:.0%}'
                sk_c = f'{sk_crit_sc:.0%}'
                crit_cell = f'<span class="{crit_cls}">{bl_c} &rarr; {sk_c}</span>'

                esc_mn = html.escape(mn).replace("'", "\\'")
                esc_sid = html.escape(sid).replace("'", "\\'")
                p.append(f'<tr>'
                         f'<td><a class="sc-link" href="#" '
                         f"onclick=\"event.preventDefault();window.__navigateToScenario('{esc_mn}','{esc_sid}')\">"
                         f'{html.escape(sid)}</a></td>'
                         f'<td style="{_score_bg(bl_mean)}">{bl_mean:.0%}</td>'
                         f'<td style="{_score_bg(sk_mean)}">{sk_mean:.0%}</td>'
                         f'<td>{_delta_html(delta)}</td>'
                         f'<td>{crit_cell}</td>'
                         f'</tr>')

            p.append('</tbody></table></div>')

        p.append('</div>')

    # ── Cross-model heatmap ──────────────────────────────────────
    per_scenario = result_summary.get("per_scenario", {})
    if per_scenario and len(meta.get("models", [])) > 1:
        model_names = meta.get("models", [])
        p.append('<div class="dash-section"><h2>Cross-Model Heatmap</h2>')
        p.append('<div class="heatmap-scroll"><table class="heatmap-table"><thead><tr>')
        p.append('<th class="hm-scenario-col">Scenario</th>')
        for mn in model_names:
            if is_evaluate:
                p.append(f'<th colspan="2" class="hm-model-header">{html.escape(_short_model(mn))}</th>')
            else:
                p.append(f'<th class="hm-model-header">{html.escape(_short_model(mn))}</th>')
        p.append('</tr>')
        if is_evaluate:
            p.append('<tr><th></th>')
            for _ in model_names:
                p.append('<th class="hm-sub">Skill</th><th class="hm-sub">Delta</th>')
            p.append('</tr>')
        p.append('</thead><tbody>')

        # Sort scenarios by worst average skill score first
        def _avg_skill(sid: str) -> float:
            ms = per_scenario.get(sid, {})
            vals = [ms.get(mn, {}).get("skill", ms.get(mn, {}).get("score", 0)) for mn in model_names]
            return sum(vals) / len(vals) if vals else 0

        sorted_sids = sorted(per_scenario.keys(), key=_avg_skill)

        for sid in sorted_sids:
            ms = per_scenario[sid]
            p.append(f'<tr><td class="sc-name">{html.escape(sid)}</td>')
            for mn in model_names:
                data = ms.get(mn, {})
                if is_evaluate:
                    sk = data.get("skill", 0)
                    bl = data.get("baseline", 0)
                    d = sk - bl
                    p.append(f'<td class="hm-cell" style="{_score_bg(sk)}">{sk:.0%}</td>')
                    p.append(f'<td class="hm-delta">{_delta_html(d)}</td>')
                else:
                    sc = data.get("score", 0)
                    p.append(f'<td class="hm-cell" style="{_score_bg(sc)}">{sc:.0%}</td>')
            p.append('</tr>')

        p.append('</tbody></table></div></div>')

    return "\n".join(p)


_DASHBOARD_EXTRA_CSS = """\
/* ── Dashboard: Hero ───────────────────────────────────────── */
.dash-hero {
  background: linear-gradient(135deg, #0f1117 0%, #1a1f2e 100%);
  color: #fff;
  padding: 28px 32px;
  border-radius: var(--radius);
  margin-bottom: 24px;
}
.dash-hero h1 { font-size: 1.3rem; font-weight: 700; margin-bottom: 4px; }
.dash-hero-sub { font-size: 0.82rem; color: #8b8fa3; }
.dash-hero-sub strong { color: #a3bcff; }

/* Benchmark version badges */
.bench-ver { font-weight: 600; padding: 1px 7px; border-radius: 4px; font-size: 0.78rem; }
.bench-release { background: rgba(52,211,153,0.15); color: #34d399; }
.bench-dirty { background: rgba(251,191,36,0.18); color: #fbbf24; cursor: help; }
.bench-dev { background: rgba(148,163,184,0.15); color: #94a3b8; cursor: help; }

/* ── Executive summary ─────────────────────────────────────── */
.exec-summary {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px 28px;
  margin-bottom: 24px;
  font-size: 0.94rem;
  line-height: 1.8;
  color: #475569;
  letter-spacing: -0.005em;
}
.exec-summary p { margin: 0 0 12px; }
.exec-summary p:last-child { margin-bottom: 0; }
.exec-summary strong { color: var(--text); font-weight: 650; }

/* ── Skill link ────────────────────────────────────────────── */
.skill-link {
  color: var(--accent); font-weight: 700; text-decoration: none;
  border-bottom: 1.5px dashed var(--accent);
  cursor: pointer; transition: opacity 0.15s;
}
.skill-link:hover { opacity: 0.8; }

/* ── Skill modal ───────────────────────────────────────────── */
.skill-modal-backdrop {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.45); backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center;
}
.skill-modal {
  background: var(--bg); border-radius: var(--radius);
  box-shadow: 0 20px 60px rgba(0,0,0,0.25);
  width: min(700px, 90vw); max-height: 85vh;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.skill-modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 24px; border-bottom: 1px solid var(--border);
}
.skill-modal-header h2 {
  margin: 0; font-size: 1.05rem; font-weight: 700;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.skill-modal-close {
  background: none; border: none; font-size: 1.6rem;
  cursor: pointer; color: var(--text-secondary);
  line-height: 1; padding: 0 4px;
  transition: color 0.15s;
}
.skill-modal-close:hover { color: var(--text); }
.skill-modal-body {
  padding: 20px 24px; overflow-y: auto;
  font-size: 0.84rem; line-height: 1.7;
  color: var(--text-secondary);
}
.skill-modal-body h2 { font-size: 1rem; margin: 20px 0 8px; color: var(--text); }
.skill-modal-body h3 { font-size: 0.92rem; margin: 16px 0 6px; color: var(--text); }
.skill-modal-body h4 { font-size: 0.86rem; margin: 14px 0 4px; color: var(--text); }
.skill-modal-body p { margin: 0 0 10px; }
.skill-modal-body ul { margin: 0 0 10px; padding-left: 20px; }
.skill-modal-body li { margin-bottom: 6px; }
.skill-modal-body strong { color: var(--text); }

/* ── Footer ────────────────────────────────────────────────── */
.scam-footer {
  text-align: center; padding: 24px 16px; margin-top: 40px;
  font-size: 0.78rem; color: var(--text-tertiary);
  border-top: 1px solid var(--border);
}
.scam-footer a {
  color: var(--text-secondary); text-decoration: none;
}
.scam-footer a:hover { color: var(--accent); text-decoration: underline; }

/* ── Dashboard: KPI cards ──────────────────────────────────── */
.kpi-row {
  display: flex; gap: 12px; flex-wrap: wrap;
  margin-bottom: 28px;
}
.kpi-card {
  flex: 1; min-width: 110px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 16px 18px;
  text-align: center;
}
.kpi-value { font-size: 1.5rem; font-weight: 700; color: var(--text); line-height: 1.2; }
.kpi-label { font-size: 0.72rem; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; font-weight: 600; }
.kpi-good { color: var(--pass); }
.kpi-bad { color: var(--fail); }

/* ── Dashboard: sections ───────────────────────────────────── */
.dash-section { margin-bottom: 36px; }
.dash-section h2 {
  font-size: 1rem; font-weight: 700; color: var(--text);
  margin-bottom: 16px;
  padding-bottom: 10px;
  border-bottom: 2px solid var(--border);
}

/* ── Leaderboard cards ─────────────────────────────────────── */
.lb-card {
  display: flex; gap: 16px; align-items: flex-start;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  margin-bottom: 12px;
  transition: box-shadow 0.15s;
}
.lb-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.lb-rank {
  font-size: 1.1rem; font-weight: 800; color: var(--text-tertiary);
  min-width: 36px; text-align: center; padding-top: 2px;
}
.lb-body { flex: 1; min-width: 0; }
.lb-name { font-size: 1rem; font-weight: 700; color: var(--text); margin-bottom: 10px; }

.lb-bars { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
.lb-bar-group { display: flex; align-items: center; gap: 10px; }
.lb-bar-label { font-size: 0.72rem; font-weight: 600; color: var(--text-tertiary); width: 60px; text-align: right; flex-shrink: 0; }
.lb-bar-value { font-size: 0.82rem; font-weight: 700; min-width: 55px; flex-shrink: 0; }
.lb-ci { font-size: 0.7rem; font-weight: 400; color: var(--text-tertiary); }

.bar-track {
  flex: 1; height: 10px; background: var(--border-light);
  border-radius: 5px; overflow: hidden; min-width: 100px;
}
.bar-fill { height: 100%; border-radius: 5px; transition: width 0.6s ease; }

.lb-stats { display: flex; flex-wrap: wrap; gap: 6px 16px; }
.lb-stat { font-size: 0.76rem; color: var(--text-secondary); }

.delta-pos { color: var(--pass); font-weight: 700; }
.delta-neg { color: var(--fail); font-weight: 700; }
.delta-zero { color: var(--text-tertiary); }

.stab-stable { color: var(--pass); font-weight: 600; }
.stab-lowvar { color: var(--warn); font-weight: 600; }
.stab-unstable { color: var(--fail); font-weight: 600; }

.run-dot {
  display: inline-block; padding: 1px 6px;
  border-radius: 4px; font-size: 0.68rem; font-weight: 700;
  margin: 0 1px; font-family: var(--mono);
}

/* ── Reproducibility section ───────────────────────────────── */
.repro-section {
  margin-top: 12px; padding-top: 10px;
  border-top: 1px solid var(--border-light);
}
.repro-title {
  font-size: 0.72rem; font-weight: 700; color: var(--text-secondary);
  text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;
}
.repro-table {
  width: 100%; border-collapse: collapse; font-size: 0.78rem;
}
.repro-table thead th {
  text-align: center; padding: 4px 10px;
  font-size: 0.7rem; font-weight: 600; color: var(--text-tertiary);
  text-transform: uppercase; letter-spacing: 0.04em;
  border-bottom: 1px solid var(--border);
}
.repro-table thead th:first-child { text-align: left; }
.repro-table tbody td {
  text-align: center; padding: 5px 10px;
  font-family: var(--mono); font-weight: 600; font-size: 0.78rem;
  border-bottom: 1px solid var(--border-light);
}
.repro-table tbody td:first-child { text-align: left; font-family: var(--font); }
.repro-label { color: var(--text-secondary); font-weight: 500 !important; }

/* ── Per-run dots row ──────────────────────────────────────── */
.lb-runs { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border-light); }
.lb-runs-row { margin-bottom: 4px; font-size: 0.76rem; }
.lb-runs-label { font-size: 0.72rem; font-weight: 600; color: var(--text-tertiary); margin-right: 6px; }

/* ── Per-model detail cards ────────────────────────────────── */
.model-detail-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  margin-bottom: 16px;
}
.model-detail-card h3 {
  font-size: 0.95rem; font-weight: 700; color: var(--text);
  margin-bottom: 14px;
}

.detail-table {
  width: 100%; border-collapse: collapse; font-size: 0.82rem;
}
.detail-table thead th {
  text-align: left; padding: 8px 10px;
  border-bottom: 2px solid var(--border);
  font-weight: 600; font-size: 0.75rem; color: var(--text-secondary);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.detail-table tbody td {
  padding: 6px 10px; border-bottom: 1px solid var(--border-light);
  text-align: center; font-weight: 600;
}
.detail-table tbody td:first-child { text-align: left; font-weight: 500; }
.detail-table tbody tr:hover { background: rgba(0,0,0,0.015); }
.sc-name { font-family: var(--mono); font-size: 0.78rem; color: var(--text); }
.crit-zero { color: var(--text-tertiary); }
.crit-fixed { color: var(--pass); font-weight: 700; }
.crit-improved { color: var(--pass); font-weight: 600; }
.crit-clear { color: var(--text-tertiary); }
.crit-unchanged { color: var(--text-tertiary); font-weight: 500; }
.crit-worse { color: var(--fail); font-weight: 700; }

/* ── Info tooltip ──────────────────────────────────────────── */
.info-tip {
  position: relative; cursor: help;
  font-size: 0.85em; color: var(--text-tertiary);
  vertical-align: middle; margin-left: 3px;
  font-style: normal;
}
.info-tip::after {
  content: attr(data-tip);
  position: absolute; bottom: calc(100% + 8px); left: 50%;
  transform: translateX(-50%);
  background: #1e293b; color: #f1f5f9;
  padding: 8px 12px; border-radius: 6px;
  font-size: 0.72rem; font-weight: 400; line-height: 1.5;
  text-transform: none; letter-spacing: 0;
  white-space: normal; width: 260px;
  pointer-events: none; opacity: 0;
  transition: opacity 0.15s;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0,0,0,0.18);
}
.info-tip::before {
  content: ""; position: absolute;
  bottom: calc(100% + 2px); left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent; border-top-color: #1e293b;
  pointer-events: none; opacity: 0;
  transition: opacity 0.15s;
  z-index: 100;
}
.info-tip:hover::after,
.info-tip:hover::before { opacity: 1; }

/* ── Heatmap ───────────────────────────────────────────────── */
.heatmap-scroll { overflow-x: auto; }
.heatmap-table {
  width: 100%; border-collapse: collapse; font-size: 0.82rem;
}
.heatmap-table thead th {
  padding: 10px 12px; text-align: center;
  border-bottom: 2px solid var(--border);
  font-weight: 700; font-size: 0.78rem;
  color: var(--text); background: var(--border-light);
  position: sticky; top: 0;
}
.hm-scenario-col { text-align: left !important; min-width: 180px; }
.hm-model-header { border-left: 2px solid var(--border); }
.hm-sub {
  font-size: 0.68rem !important; font-weight: 600 !important;
  color: var(--text-tertiary) !important; text-transform: uppercase;
  letter-spacing: 0.06em; padding: 4px 12px !important;
}
.heatmap-table tbody td {
  padding: 6px 12px; border-bottom: 1px solid var(--border-light);
  text-align: center; font-weight: 700; font-size: 0.8rem;
}
.heatmap-table tbody td:first-child { text-align: left; font-weight: 500; }
.hm-cell { font-family: var(--mono); }
.hm-delta { font-size: 0.72rem !important; font-weight: 600 !important; }
.heatmap-table tbody tr:hover td { filter: brightness(0.97); }

/* ── Sidebar: collapsible model groups ─────────────────────── */
.sidebar-model { margin-bottom: 2px; }
.sidebar-model-header {
  padding: 10px 20px 8px;
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--sidebar-text-bright);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  display: flex;
  align-items: center;
  gap: 6px;
  user-select: none;
}
.sidebar-model-header:hover { background: var(--sidebar-hover); }
.sidebar-model-header .section-score { font-size: 0.72rem; }
.sidebar-model-header .section-score:first-of-type { margin-left: auto; }
.header-arrow { font-size: 0.6rem; color: #555a6b; margin: 0 3px; }
.sidebar-model-arrow {
  display: inline-block; transition: transform 0.2s; font-size: 0.7rem;
}
.sidebar-model:not(.collapsed) .sidebar-model-arrow { transform: rotate(90deg); }
.sidebar-model-body {
  overflow: hidden; max-height: 2000px;
  transition: max-height 0.3s ease;
}
.sidebar-model.collapsed .sidebar-model-body { max-height: 0; }

.sidebar-phase-header {
  padding: 6px 20px 4px 28px;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #555a6b;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sidebar-phase-header .section-score { font-size: 0.68rem; }

.sidebar-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px 9px 20px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--sidebar-text-bright);
  transition: background 0.12s;
  border-left: 2px solid transparent;
  margin-bottom: 4px;
}
.sidebar-summary:hover { background: var(--sidebar-hover); }
.sidebar-summary.active {
  background: var(--sidebar-active-bg);
  border-left-color: var(--sidebar-active-border);
  color: #fff; font-weight: 600;
}

/* ── Phase toggle (baseline / skill) ───────────────────────── */
.phase-toggle {
  display: flex; gap: 0;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  overflow: hidden; width: fit-content;
}
.phase-btn {
  padding: 7px 20px; border: none; background: var(--surface);
  font-family: var(--font); font-size: 0.82rem; font-weight: 600;
  color: var(--text-secondary); cursor: pointer;
  transition: background 0.12s, color 0.12s;
  border-right: 1px solid var(--border);
}
.phase-btn:last-child { border-right: none; }
.phase-btn:hover { background: var(--border-light); }
.phase-btn.phase-active {
  background: var(--accent); color: #fff;
}

/* Phase bar — top-level toggle above scenario content */
#phase-bar {
  margin-bottom: 18px;
}
#phase-bar .phase-toggle {
  margin-bottom: 0;
  font-size: 0.88rem;
}
#phase-bar .phase-btn {
  padding: 9px 28px;
  font-size: 0.86rem;
}

/* Phase toggle inside inline controls */
#inline-phase-toggle { margin-right: 12px; }
#inline-phase-toggle .phase-toggle { margin-bottom: 0; }

/* Watch-other link after playback */
.watch-other-link {
  color: var(--accent); font-weight: 600; font-size: 0.84rem;
  text-decoration: none; margin-left: 12px;
  transition: opacity 0.15s;
}
.watch-other-link:hover { opacity: 0.8; text-decoration: underline; }

/* ── Sidebar score arrow ───────────────────────────────────── */
.score-arrow {
  font-size: 0.68rem; color: #555a6b; margin: 0 1px;
}

/* ── Clickable scenario names in detail table ──────────────── */
.sc-link {
  color: var(--accent); text-decoration: none; cursor: pointer;
  font-family: var(--mono); font-size: 0.78rem;
}
.sc-link:hover { text-decoration: underline; }

/* ── View containers ───────────────────────────────────────── */
.view-summary, .view-scenario { display: none; }
.view-summary.active, .view-scenario.active { display: block; }

/* ── Wider content for dashboard ───────────────────────────── */
.content.with-sidebar { max-width: none; }
"""


def _generate_dashboard_js() -> str:
    """Generate JS that extends the base replay JS with dashboard navigation."""
    return _JS + """

// ── Dashboard extension ─────────────────────────────────────────
(function() {
  "use strict";

  var currentView = "summary";
  var _origMeta = null;
  var _activePhase = null;  // track which phase tab is active
  var _activeModel = null;
  var _activeSid = null;

  function showSummary() {
    currentView = "summary";
    _activePhase = null;
    _activeModel = null;
    _activeSid = null;
    document.querySelectorAll(".sidebar-item, .sidebar-summary").forEach(function(el) {
      el.classList.remove("active");
    });
    var summaryEl = document.querySelector(".sidebar-summary");
    if (summaryEl) summaryEl.classList.add("active");
    document.querySelectorAll(".view-summary, .view-scenario").forEach(function(el) {
      el.classList.remove("active");
    });
    var sv = document.querySelector(".view-summary");
    if (sv) sv.classList.add("active");
    var phaseBar = document.getElementById("phase-bar");
    if (phaseBar) { phaseBar.innerHTML = ""; phaseBar.style.display = "none"; }
    window.scrollTo({ top: 0 });
  }

  function _renderPhase(sectionIdx, scenarioIdx) {
    var section = window.__SCAM_DATA__.sections[sectionIdx];
    if (!section) return;
    var sc = section.scenarios[scenarioIdx];
    if (!sc) return;

    window.__SCAM_DATA__.scenarios = section.scenarios;
    window.__SCAM_DATA__.metadata = {
      model: section.model,
      skill_hash: section.phase === "no-skill" ? "none" : section.phase,
      judge_model: (_origMeta && _origMeta.judge_model) || "",
      timestamp: (_origMeta && _origMeta.timestamp) || "",
      total_scenarios: section.scenarios.length
    };

    if (typeof window.__renderScenario === "function") {
      window.__renderScenario(scenarioIdx);
    }
  }

  function showScenario(sectionIdx, scenarioIdx, phase) {
    currentView = "scenario";

    var section = window.__SCAM_DATA__.sections[sectionIdx];
    if (!section) return;
    var sc = section.scenarios[scenarioIdx];
    if (!sc) return;

    var model = section.model;
    var sid = sc.scenario_id;

    // Determine phase to show (default: skill if available, else whatever we have)
    var xlinks = window.__SCAM_XLINKS__ || {};
    var key = model + "::" + sid;
    var phases = xlinks[key] || {};
    var phaseKeys = Object.keys(phases);

    if (!phase) {
      // Default: baseline first, fall back to whatever section we were given
      phase = phases["no-skill"] ? "no-skill" : section.phase;
    }

    _activePhase = phase;
    _activeModel = model;
    _activeSid = sid;

    // Resolve actual section/scenario for the requested phase
    var coords = phases[phase];
    if (coords) {
      sectionIdx = coords[0];
      scenarioIdx = coords[1];
    }

    // Highlight sidebar item
    document.querySelectorAll(".sidebar-item, .sidebar-summary").forEach(function(el) {
      el.classList.remove("active");
    });
    // Match by model+sid
    var matchItem = null;
    document.querySelectorAll(".sidebar-item").forEach(function(el) {
      if (el.getAttribute("data-model") === model && el.getAttribute("data-sid") === sid) {
        matchItem = el;
      }
    });
    if (matchItem) {
      matchItem.classList.add("active");
      // Auto-expand the parent model group
      var parentGroup = matchItem.closest(".sidebar-model");
      if (parentGroup) parentGroup.classList.remove("collapsed");
    }

    // Show scenario view
    document.querySelectorAll(".view-summary, .view-scenario").forEach(function(el) {
      el.classList.remove("active");
    });
    var viewEl = document.getElementById("view-scenario");
    if (!viewEl) return;
    viewEl.classList.add("active");

    // Render the replay
    _renderPhase(sectionIdx, scenarioIdx);

    // Inject phase toggles if multiple phases available
    if (phaseKeys.length > 1) {
      _injectPhaseToggles(phase, phases);
      // Wire up "watch the other version" offer after playback ends
      window.__onPlaybackDone = function() {
        _showWatchOther(phase, phases);
      };
      // Wire up re-injection on replay (base JS re-renders DOM)
      window.__onReplay = function() {
        _injectPhaseToggles(phase, phases);
      };
    } else {
      window.__onPlaybackDone = null;
      window.__onReplay = null;
      var phaseBar = document.getElementById("phase-bar");
      if (phaseBar) { phaseBar.innerHTML = ""; phaseBar.style.display = "none"; }
      var wo = document.getElementById("watch-other");
      if (wo) wo.style.display = "none";
    }

    // Inject the video export command
    _injectVideoCmd(model, sid, phase);

    window.scrollTo({ top: 0 });
  }

  function _injectVideoCmd(model, sid, phase) {
    var el = document.getElementById("video-cmd");
    if (!el) return;
    // Use _origMeta (saved on DOMContentLoaded) because _renderPhase
    // overwrites window.__SCAM_DATA__.metadata with a stripped-down version.
    var meta = _origMeta || {};
    var epoch = meta.epoch;
    var command = meta.command || "run";
    var jsonFile = "results/agentic/scam-" + command + "-" + epoch + ".json";
    var phaseArg = phase ? " --phase " + phase : "";
    var cmd = "scam export " + jsonFile + " --video --model \\"" + model + "\\" --scenario \\"" + sid + "\\"" + phaseArg;
    el.innerHTML = '<div class="video-cmd-label">Export as video</div>' +
      '<div class="video-cmd-box" title="Click to copy">' +
      '<code>' + cmd + '</code>' +
      '<span class="video-cmd-copy">Copy</span>' +
      '</div>';
    el.style.display = "";
    el.querySelector(".video-cmd-box").addEventListener("click", function() {
      navigator.clipboard.writeText(cmd).then(function() {
        var copyEl = el.querySelector(".video-cmd-copy");
        copyEl.textContent = "Copied!";
        setTimeout(function() { copyEl.textContent = "Copy"; }, 2000);
      });
    });
  }

  // ── Phase toggle (baseline / skill) ──────────────────────
  function _buildPhaseToggle(activePhase, phases) {
    var toggle = document.createElement("div");
    toggle.className = "phase-toggle";

    var phaseKeys = Object.keys(phases);
    phaseKeys.sort(function(a, b) {
      if (a === "no-skill") return -1;
      if (b === "no-skill") return 1;
      return a.localeCompare(b);
    });

    phaseKeys.forEach(function(pk) {
      var label = pk === "no-skill" ? "Baseline" : "Skill";
      var coords = phases[pk];
      var btn = document.createElement("button");
      btn.className = "phase-btn" + (pk === activePhase ? " phase-active" : "");
      btn.textContent = label;
      btn.addEventListener("click", function(e) {
        e.preventDefault();
        showScenario(coords[0], coords[1], pk);
      });
      toggle.appendChild(btn);
    });
    return toggle;
  }

  function _injectPhaseToggles(activePhase, phases) {
    // Populate the top-level phase bar (above scenario content)
    var phaseBar = document.getElementById("phase-bar");
    if (phaseBar) {
      phaseBar.innerHTML = "";
      phaseBar.appendChild(_buildPhaseToggle(activePhase, phases));
      phaseBar.style.display = "";
    }
    // Populate the inline toggle (shown during/after playback)
    var inlineSlot = document.getElementById("inline-phase-toggle");
    if (inlineSlot) {
      inlineSlot.innerHTML = "";
      inlineSlot.appendChild(_buildPhaseToggle(activePhase, phases));
    }
  }

  function _showWatchOther(activePhase, phases) {
    var el = document.getElementById("watch-other");
    if (!el) return;
    var otherPhase = null;
    var otherCoords = null;
    for (var pk in phases) {
      if (pk !== activePhase) {
        otherPhase = pk;
        otherCoords = phases[pk];
        break;
      }
    }
    if (!otherPhase || !otherCoords) { el.style.display = "none"; return; }

    var label = otherPhase === "no-skill" ? "baseline" : "skill";
    el.style.display = "";
    el.innerHTML = '<a href="#" class="watch-other-link">Watch the ' + label + ' version &rarr;</a>';
    el.querySelector("a").addEventListener("click", function(e) {
      e.preventDefault();
      showScenario(otherCoords[0], otherCoords[1], otherPhase);
    });
  }

  // ── Navigate to a scenario by model + scenario_id ────────
  function navigateToScenario(model, sid, phase) {
    var xlinks = window.__SCAM_XLINKS__ || {};
    var key = model + "::" + sid;
    var phases = xlinks[key] || {};
    var targetPhase = phase || Object.keys(phases)[0];
    var coords = phases[targetPhase];
    if (coords) {
      showScenario(coords[0], coords[1], targetPhase);
    }
  }

  // ── Collapsible sidebar model groups ─────────────────────
  function initCollapsible() {
    document.querySelectorAll(".sidebar-model-header").forEach(function(header) {
      header.addEventListener("click", function() {
        var group = header.closest(".sidebar-model");
        if (!group) return;
        group.classList.toggle("collapsed");
      });
    });
  }

  window.__showSummary = showSummary;
  window.__showScenario = showScenario;
  window.__navigateToScenario = navigateToScenario;

  document.addEventListener("DOMContentLoaded", function() {
    _origMeta = JSON.parse(JSON.stringify(window.__SCAM_DATA__.metadata || {}));

    document.querySelectorAll(".sidebar-summary").forEach(function(el) {
      el.addEventListener("click", showSummary);
    });

    document.querySelectorAll(".sidebar-item[data-section]").forEach(function(el) {
      el.addEventListener("click", function() {
        var si = parseInt(el.getAttribute("data-section"));
        var sci = parseInt(el.getAttribute("data-scenario"));
        showScenario(si, sci);
      });
    });

    initCollapsible();
    initSidebarResize();
    showSummary();
  });

  // ── Resizable sidebar ────────────────────────────────────
  function initSidebarResize() {
    var handle = document.getElementById("sidebar-resize");
    if (!handle) return;
    var sidebar = handle.closest(".sidebar");
    if (!sidebar) return;
    var content = document.querySelector(".content.with-sidebar");

    var dragging = false;

    handle.addEventListener("mousedown", function(e) {
      e.preventDefault();
      dragging = true;
      handle.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    });

    document.addEventListener("mousemove", function(e) {
      if (!dragging) return;
      var w = Math.min(480, Math.max(180, e.clientX));
      sidebar.style.width = w + "px";
      if (content) content.style.marginLeft = w + "px";
    });

    document.addEventListener("mouseup", function() {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    });
  }

  // ── Skill text modal ──────────────────────────────────────
  window.__showSkillModal = function() {
    var data = window.__SCAM_DATA__ || {};
    var meta = data.metadata || {};
    var text = meta.skill_text || "";
    var name = meta.skill_file || "Skill";
    if (!text) return;

    document.getElementById("skill-modal-title").textContent = name;
    // Render markdown-ish content (headings, bold, lists, paragraphs)
    var html = _renderSkillText(text);
    document.getElementById("skill-modal-body").innerHTML = html;
    document.getElementById("skill-modal-backdrop").style.display = "";
    document.body.style.overflow = "hidden";
  };

  window.__hideSkillModal = function() {
    document.getElementById("skill-modal-backdrop").style.display = "none";
    document.body.style.overflow = "";
  };

  // Escape HTML in skill text
  function _escSkill(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function _renderSkillText(text) {
    // Simple markdown renderer: headings, bold, lists, paragraphs
    var lines = text.split("\\n");
    var out = [];
    var inList = false;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      // Heading
      var hm = line.match(/^(#{1,3})\\s+(.*)/);
      if (hm) {
        if (inList) { out.push("</ul>"); inList = false; }
        var lvl = hm[1].length + 1; // h2-h4 in the modal
        out.push("<h" + lvl + ">" + _escSkill(hm[2]).replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>") + "</h" + lvl + ">");
        continue;
      }
      // List item
      var lm = line.match(/^[-*]\\s+(.*)/);
      if (lm) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + _escSkill(lm[1]).replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>") + "</li>");
        continue;
      }
      // Blank line
      if (line.trim() === "") {
        if (inList) { out.push("</ul>"); inList = false; }
        continue;
      }
      // Regular paragraph
      if (inList) { out.push("</ul>"); inList = false; }
      out.push("<p>" + _escSkill(line).replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>") + "</p>");
    }
    if (inList) out.push("</ul>");
    return out.join("\\n");
  }

  // Close modal on Escape key
  document.addEventListener("keydown", function(e) {
    if (e.key === "Escape") window.__hideSkillModal();
  });
})();
"""


def generate_dashboard_html(data: dict) -> str:
    """Generate a comprehensive single-page dashboard from v2 data.

    The page includes:
    - Summary view with leaderboard and cross-model comparison
    - Sidebar navigation organized by model/phase/scenario
    - Per-scenario animated replay accessible via navigation
    """
    meta = data.get("metadata", {})
    summary = data.get("summary", {})
    sections = data.get("sections", [])

    timestamp = meta.get("timestamp", "")
    if "T" in str(timestamp):
        timestamp = str(timestamp).split("T")[0]

    # Build a lookup: (model, scenario_id) → {phase: (section_idx, scenario_idx)}
    from collections import OrderedDict
    scenario_lookup: dict[tuple[str, str], dict[str, tuple[int, int]]] = {}
    for si, section in enumerate(sections):
        mn = section.get("model", "")
        phase = section.get("phase", "")
        for sci, sc in enumerate(section.get("scenarios", [])):
            sid = sc.get("scenario_id", "")
            key = (mn, sid)
            scenario_lookup.setdefault(key, {})[phase] = (si, sci)

    # Group sections by model
    model_groups: OrderedDict[str, list[tuple[int, dict]]] = OrderedDict()
    for si, section in enumerate(sections):
        model_key = section.get("model", "unknown")
        model_groups.setdefault(model_key, []).append((si, section))

    is_evaluate = meta.get("command") == "evaluate"

    # Build sidebar HTML — grouped by model, collapsible
    sidebar_html = '<div class="sidebar">\n'
    sidebar_html += '  <div class="sidebar-resize" id="sidebar-resize"></div>\n'
    sidebar_html += '  <h2>SCAM Results</h2>\n'
    sidebar_html += '  <div class="sidebar-summary active">&#9776; Summary</div>\n'

    for model_key, model_sections in model_groups.items():
        short = _short_model(model_key)

        if is_evaluate:
            bl_score = next((s.get("mean_score", 0) for _, s in model_sections if s.get("phase") == "no-skill"), 0)
            sk_score = next((s.get("mean_score", 0) for _, s in model_sections if s.get("phase") != "no-skill"), 0)
            bl_cls = _score_color_class(bl_score)
            sk_cls = _score_color_class(sk_score)
            scores_html = (
                f'<span class="section-score {bl_cls}">{bl_score:.0%}</span>'
                f'<span class="header-arrow">&rarr;</span>'
                f'<span class="section-score {sk_cls}">{sk_score:.0%}</span>'
            )
        else:
            best = max((s.get("mean_score", 0) for _, s in model_sections), default=0)
            best_cls = _score_color_class(best)
            scores_html = f'<span class="section-score {best_cls}">{best:.0%}</span>'

        sidebar_html += (
            f'  <div class="sidebar-model collapsed" data-model="{html.escape(model_key)}">\n'
            f'    <div class="sidebar-model-header">'
            f'<span class="sidebar-model-arrow">&#9656;</span> '
            f'{html.escape(short)} '
            f'{scores_html}'
            f'</div>\n'
            f'    <div class="sidebar-model-body">\n'
        )

        if is_evaluate:
            # Deduplicated: one row per scenario showing baseline → skill
            bl_section = next(((si, s) for si, s in model_sections if s.get("phase") == "no-skill"), None)
            sk_section = next(((si, s) for si, s in model_sections if s.get("phase") != "no-skill"), None)
            # Use skill section scenarios as canonical list (same set)
            ref_section = sk_section or bl_section
            if ref_section:
                ref_si, ref_sec = ref_section
                for sci, sc in enumerate(ref_sec.get("scenarios", [])):
                    sid = sc.get("scenario_id", "?")
                    sk_pct = round(sc.get("safety_score", 0) * 100)
                    sk_badge = _score_badge_style(sc.get("safety_score", 0))
                    # Find baseline score for same scenario
                    bl_pct = "?"
                    bl_badge = ""
                    if bl_section:
                        bl_si, bl_sec = bl_section
                        for bl_sci, bl_sc in enumerate(bl_sec.get("scenarios", [])):
                            if bl_sc.get("scenario_id") == sid:
                                bl_pct = str(round(bl_sc.get("safety_score", 0) * 100))
                                bl_badge = _score_badge_style(bl_sc.get("safety_score", 0))
                                break
                    # data-section/data-scenario point to skill section;
                    # xlinks lookup will provide baseline coords
                    sidebar_html += (
                        f'      <div class="sidebar-item" '
                        f'data-section="{ref_si}" data-scenario="{sci}" '
                        f'data-model="{html.escape(model_key)}" data-sid="{html.escape(sid)}">\n'
                        f'        <span class="name">{html.escape(sid)}</span>\n'
                        f'        <span class="score-badge" style="{bl_badge}">{bl_pct}%</span>\n'
                        f'        <span class="score-arrow">&rarr;</span>\n'
                        f'        <span class="score-badge" style="{sk_badge}">{sk_pct}%</span>\n'
                        f'      </div>\n'
                    )
        else:
            # Run mode: one phase, list scenarios directly
            for si, section in model_sections:
                for sci, sc in enumerate(section.get("scenarios", [])):
                    pct = round(sc.get("safety_score", 0) * 100)
                    badge_style = _score_badge_style(sc.get("safety_score", 0))
                    s_id = sc.get("scenario_id", "?")
                    sidebar_html += (
                        f'      <div class="sidebar-item" '
                        f'data-section="{si}" data-scenario="{sci}" '
                        f'data-model="{html.escape(model_key)}" data-sid="{html.escape(s_id)}">\n'
                        f'        <span class="name">{html.escape(s_id)}</span>\n'
                        f'        <span class="score-badge" style="{badge_style}">{pct}%</span>\n'
                        f'      </div>\n'
                    )

        sidebar_html += '    </div>\n  </div>\n'

    sidebar_html += '</div>\n'

    # Serialize the scenario cross-link lookup for JS
    # { "model::scenario_id": { "phase": [sectionIdx, scenarioIdx] } }
    xlink_map: dict[str, dict[str, list[int]]] = {}
    for (mn, sid), phases in scenario_lookup.items():
        key = f"{mn}::{sid}"
        xlink_map[key] = {p: list(v) for p, v in phases.items()}

    # Build summary content
    models_raw = data.get("models", {})
    summary_content = _generate_summary_html(summary, meta, models_raw)

    # Serialize data for JS
    data_json = json.dumps(data, indent=None, default=str)
    xlink_json = json.dumps(xlink_map, indent=None)

    # Build page
    all_css = _CSS + _DASHBOARD_EXTRA_CSS
    all_js = _generate_dashboard_js()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SCAM Dashboard &mdash; {html.escape(timestamp)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{all_css}
</style>
</head>
<body>
<div class="layout">
{sidebar_html}
<div class="content with-sidebar">
<div class="view-summary active">
{summary_content}
</div>
<div class="view-scenario" id="view-scenario">
<div id="phase-bar"></div>
<div id="scenario-content"></div>
</div>
</div>
</div>
<div class="skill-modal-backdrop" id="skill-modal-backdrop" style="display:none;" onclick="window.__hideSkillModal()">
  <div class="skill-modal" onclick="event.stopPropagation()">
    <div class="skill-modal-header">
      <h2 id="skill-modal-title">Skill</h2>
      <button class="skill-modal-close" onclick="window.__hideSkillModal()">&times;</button>
    </div>
    <div class="skill-modal-body" id="skill-modal-body"></div>
  </div>
</div>
<footer class="scam-footer">
  SCAM is an open-source benchmark by <a href="https://1password.com" target="_blank">1Password</a>
  &middot; <a href="https://github.com/1Password/SCAM" target="_blank">GitHub</a>
</footer>
<script>
window.__SCAM_DATA__ = {data_json};
window.__SCAM_XLINKS__ = {xlink_json};
</script>
<script>
{all_js}
</script>
</body>
</html>"""


def export_result(
    result: dict,
    output_dir: Path,
    *,
    model: str | None = None,
    phase: str | None = None,
    scenario_id: str | None = None,
) -> list[Path]:
    """Export a v2 result as a comprehensive HTML dashboard.

    Produces a single ``index.html`` containing:
    - Summary page with leaderboard and cross-model comparison
    - Per-model/phase sections with scenario navigation
    - Per-scenario animated replays

    Args:
        result: V2 unified result dict.
        output_dir: Directory to write files into.
        model: Optional model filter.
        phase: Optional phase filter.
        scenario_id: Optional scenario ID filter.

    Returns:
        List of paths to written files.
    """
    dashboard_data = _build_dashboard_data(
        result,
        model=model,
        phase=phase,
        scenario_id=scenario_id,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    page = generate_dashboard_html(dashboard_data)
    path = output_dir / "index.html"
    path.write_text(page, encoding="utf-8")

    return [path]
