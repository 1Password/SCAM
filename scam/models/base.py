"""Abstract model interface for SCAM benchmark."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    """A tool call returned by the model in agentic mode."""

    id: str
    name: str
    arguments: dict
    # Gemini 3 thought-signature: opaque token that must be round-tripped
    # to avoid 400 INVALID_ARGUMENT errors.  Stored as base64 string for
    # JSON safety; the Gemini adapter converts back to bytes when needed.
    thought_signature: str | None = None


@dataclass
class ChatResponse:
    """Response from a multi-turn chat call.

    Either ``text`` or ``tool_calls`` will be populated, not both.
    Token counts are populated from the provider's ``usage`` response
    when available, enabling actual cost calculation.
    """

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0

    def to_message(self) -> dict:
        """Convert this response to an OpenAI-format assistant message.

        Used to append the assistant turn to the conversation history
        when the model made tool calls.
        """
        if self.tool_calls:
            tc_dicts = []
            for tc in self.tool_calls:
                tc_dict: dict = {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                # Preserve Gemini thought-signature for round-tripping.
                if tc.thought_signature is not None:
                    tc_dict["thought_signature"] = tc.thought_signature
                tc_dicts.append(tc_dict)
            return {
                "role": "assistant",
                "content": self.text,
                "tool_calls": tc_dicts,
            }
        return {"role": "assistant", "content": self.text or ""}


class BaseModel(ABC):
    """Abstract base class for model implementations.

    The primary interface is :meth:`chat` — multi-turn conversation with
    optional tool calling.  This is what the agentic evaluation engine
    uses and what new model adapters must implement.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResponse:
        """Multi-turn chat with optional tool calling.

        This is the core model interface for SCAM.  All agentic
        evaluation flows through this method.

        Args:
            messages: OpenAI-format message history.
            tools: Optional list of OpenAI-format tool definitions.

        Returns:
            A :class:`ChatResponse` with either text or tool calls.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model_name!r})"
