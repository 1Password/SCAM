"""Anthropic (Claude) model implementation."""

from __future__ import annotations

import json

import anthropic
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from scam.models.base import (
    BaseModel,
    ChatResponse,
    ToolCall,
)
from scam.utils.config import get_api_key

# Retryable errors — rate limits need many attempts with long backoff
_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    anthropic.APITimeoutError,
)


def _openai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI-format tool definitions to Anthropic format.

    OpenAI:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Anthropic:
        {"name": ..., "description": ..., "input_schema": ...}
    """
    result = []
    for tool in tools:
        func = tool.get("function", {})
        result.append({
            "name": func["name"],
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _openai_messages_to_anthropic(
    messages: list[dict],
) -> tuple[str, list[dict]]:
    """Convert OpenAI-format message list to Anthropic format.

    Returns (system_prompt, anthropic_messages).

    Key differences handled:
    - System message extracted as a separate string.
    - Tool-call assistant messages → assistant with ``tool_use`` content blocks.
    - Tool-result messages → user message with ``tool_result`` content blocks.
    - Adjacent tool-result messages are merged into a single user turn.
    """
    system = ""
    anthropic_msgs: list[dict] = []

    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role", "")

        if role == "system":
            system = msg.get("content", "")
            i += 1
            continue

        if role == "user":
            anthropic_msgs.append({"role": "user", "content": msg["content"]})
            i += 1
            continue

        if role == "assistant":
            # Build content blocks for the assistant message.
            content_blocks: list[dict] = []

            # The assistant may have text alongside tool calls.
            text = msg.get("content")
            if text:
                content_blocks.append({"type": "text", "text": text})

            # Convert tool_calls to tool_use blocks.
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": func["name"],
                    "input": args,
                })

            # If there are no content blocks at all, use an empty text block
            # (Anthropic requires at least one content block).
            if not content_blocks:
                content_blocks.append({"type": "text", "text": ""})

            anthropic_msgs.append({"role": "assistant", "content": content_blocks})
            i += 1
            continue

        if role == "tool":
            # Collect consecutive tool-result messages into a single user
            # message with tool_result content blocks (Anthropic requirement).
            tool_results: list[dict] = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tmsg = messages[i]
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tmsg["tool_call_id"],
                    "content": tmsg.get("content", ""),
                })
                i += 1
            anthropic_msgs.append({"role": "user", "content": tool_results})
            continue

        # Unknown role — skip
        i += 1

    return system, anthropic_msgs


class AnthropicModel(BaseModel):
    """Anthropic Claude model via the Messages API."""

    def __init__(self, model_name: str):
        super().__init__(model_name)
        api_key = get_api_key("anthropic")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    @retry(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=4, max=120),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResponse:
        """Multi-turn chat with tool-calling support.

        Converts OpenAI-format messages and tools to the Anthropic
        Messages API format, then converts the response back to the
        shared :class:`ChatResponse` type.
        """
        system, anthropic_messages = _openai_messages_to_anthropic(messages)

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": 4096,
            "messages": anthropic_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _openai_tools_to_anthropic(tools)

        response = await self.client.messages.create(**kwargs)

        # Extract token usage from the response
        usage = getattr(response, "usage", None)
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0

        # Parse the response — Anthropic returns a list of content blocks.
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in (response.content or []):
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        text = "\n".join(text_parts) if text_parts else None

        return ChatResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
