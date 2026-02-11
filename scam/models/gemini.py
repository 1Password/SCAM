"""Google Gemini model implementation."""

from __future__ import annotations

import base64
import json
from uuid import uuid4

from google import genai
from google.genai import types
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)

from scam.models.base import (
    BaseModel,
    ChatResponse,
    ToolCall,
)
from scam.utils.config import get_api_key


def _is_retryable(exc: BaseException) -> bool:
    """Check if an exception from the google-genai SDK is retryable.

    Catches rate-limit (429), server (500/503), and transient connection
    errors without importing ``google.api_core`` (which may not be a
    direct dependency).
    """
    name = type(exc).__name__
    msg = str(exc).lower()

    # google.api_core.exceptions hierarchy
    if name in (
        "ResourceExhausted",
        "TooManyRequests",
        "ServiceUnavailable",
        "InternalServerError",
        "DeadlineExceeded",
        "Aborted",
    ):
        return True

    # Catch generic HTTP errors by status code in the message
    if "429" in msg or "503" in msg or "500" in msg:
        return True

    # Connection-level transient errors
    if any(k in msg for k in ("connection", "timeout", "temporarily")):
        return True

    return False


# ---------------------------------------------------------------------------
# Format conversion helpers
# ---------------------------------------------------------------------------


# JSON Schema keys that Gemini's function-declaration endpoint does not
# accept.  These are valid in OpenAPI / JSON Schema but cause 400
# INVALID_ARGUMENT errors when sent to the Gemini API.
_UNSUPPORTED_SCHEMA_KEYS = frozenset({
    "additionalProperties",
    "default",
    "$schema",
    "examples",
    "title",
})


def _strip_unsupported_schema(schema: dict) -> dict:
    """Recursively remove JSON Schema keys that Gemini does not support."""
    cleaned: dict = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_SCHEMA_KEYS:
            continue
        if isinstance(value, dict):
            cleaned[key] = _strip_unsupported_schema(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _strip_unsupported_schema(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned


def _openai_tools_to_gemini(tools: list[dict]) -> types.Tool:
    """Convert OpenAI-format tool definitions to a Gemini ``Tool``.

    OpenAI:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Gemini:
        types.Tool(function_declarations=[{"name": ..., "description": ..., "parameters": ...}])

    Strips JSON Schema keys that Gemini does not support (e.g.
    ``additionalProperties``).
    """
    declarations: list[dict] = []
    for tool in tools:
        func = tool.get("function", {})
        params = func.get("parameters", {"type": "object", "properties": {}})
        declarations.append({
            "name": func["name"],
            "description": func.get("description", ""),
            "parameters": _strip_unsupported_schema(params),
        })
    return types.Tool(function_declarations=declarations)


def _openai_messages_to_gemini(
    messages: list[dict],
) -> tuple[str, list[types.Content]]:
    """Convert OpenAI-format message list to Gemini format.

    Returns ``(system_instruction, gemini_contents)``.

    Key differences handled:

    - ``system`` message → extracted as ``system_instruction``.
    - ``user`` messages → ``Content(role="user", ...)``.
    - ``assistant`` messages → ``Content(role="model", ...)`` with text
      and/or ``FunctionCall`` parts.
    - ``tool`` messages → ``Content(role="user", ...)`` with
      ``FunctionResponse`` parts.  Adjacent tool-result messages are
      merged into a single Content.
    """
    system = ""
    contents: list[types.Content] = []

    # Build a mapping from tool_call_id → function name so that tool-
    # result messages (which only carry tool_call_id) can be converted
    # to Gemini FunctionResponse objects (which require the name).
    tc_id_to_name: dict[str, str] = {}
    for msg in messages:
        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            tc_id_to_name[tc["id"]] = func.get("name", "unknown")

    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role", "")

        if role == "system":
            system = msg.get("content", "")
            i += 1
            continue

        if role == "user":
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=msg["content"])],
                )
            )
            i += 1
            continue

        if role == "assistant":
            parts: list[types.Part] = []

            # The assistant may have text alongside tool calls.
            text = msg.get("content")
            if text:
                parts.append(types.Part(text=text))

            # Convert tool_calls to FunctionCall parts, preserving
            # Gemini thought-signatures for round-tripping.
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                part_kwargs: dict = {
                    "function_call": types.FunctionCall(
                        name=func["name"],
                        args=args,
                    ),
                }
                # Restore thought_signature (base64 → bytes) if present.
                sig_b64 = tc.get("thought_signature")
                if sig_b64:
                    part_kwargs["thought_signature"] = base64.b64decode(sig_b64)

                parts.append(types.Part(**part_kwargs))

            # Gemini requires at least one part per Content.
            if not parts:
                parts.append(types.Part(text=""))

            contents.append(types.Content(role="model", parts=parts))
            i += 1
            continue

        if role == "tool":
            # Collect consecutive tool-result messages into a single
            # user Content with FunctionResponse parts.
            fn_parts: list[types.Part] = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tmsg = messages[i]
                tc_id = tmsg.get("tool_call_id", "")
                fn_name = tc_id_to_name.get(tc_id, "unknown")

                # Try to parse the content as JSON so Gemini gets
                # structured data; fall back to a string wrapper.
                # FunctionResponse.response must be a dict.
                raw_content = tmsg.get("content", "")
                try:
                    parsed = json.loads(raw_content)
                    response_data = parsed if isinstance(parsed, dict) else {"result": parsed}
                except (json.JSONDecodeError, TypeError):
                    response_data = {"result": raw_content}

                fn_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fn_name,
                            response=response_data,
                        )
                    )
                )
                i += 1
            contents.append(types.Content(role="user", parts=fn_parts))
            continue

        # Unknown role — skip
        i += 1

    return system, contents


class GeminiModel(BaseModel):
    """Google Gemini model via the google-genai SDK."""

    def __init__(self, model_name: str):
        super().__init__(model_name)
        api_key = get_api_key("google")
        self.client = genai.Client(api_key=api_key)

    @retry(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=4, max=120),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResponse:
        """Multi-turn chat with tool-calling support.

        Converts OpenAI-format messages and tools to the Gemini
        ``generate_content`` format, then converts the response back to
        the shared :class:`ChatResponse` type.
        """
        system, gemini_contents = _openai_messages_to_gemini(messages)

        config = types.GenerateContentConfig(
            system_instruction=system if system else None,
            max_output_tokens=4096,
        )
        if tools:
            config.tools = [_openai_tools_to_gemini(tools)]

        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=gemini_contents,
            config=config,
        )

        # Extract token usage
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        # Parse the response — Gemini returns a list of parts in the
        # first candidate's content.
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        candidate = response.candidates[0] if response.candidates else None
        parts = (
            candidate.content.parts
            if candidate and candidate.content and candidate.content.parts
            else []
        )

        for part in parts:
            if part.function_call:
                fc = part.function_call
                # Gemini 3 returns thought_signature (bytes) on function
                # call parts.  These MUST be round-tripped or the next
                # API call will 400.  Base64-encode for JSON safety.
                sig_bytes = getattr(part, "thought_signature", None)
                sig_b64: str | None = None
                if sig_bytes:
                    sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

                tool_calls.append(
                    ToolCall(
                        # Gemini doesn't provide tool-call IDs like
                        # OpenAI — generate a unique one.
                        id=f"call_{uuid4().hex[:24]}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                        thought_signature=sig_b64,
                    )
                )
            elif part.text:
                text_parts.append(part.text)

        text = "\n".join(text_parts) if text_parts else None

        return ChatResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
