"""OpenAI model implementation."""

from __future__ import annotations

import json

import openai
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
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.InternalServerError,
    openai.APITimeoutError,
)


class OpenAIModel(BaseModel):
    """OpenAI model via the Chat Completions API.

    Supports local endpoints (Ollama, vLLM) via optional base_url and api_key.
    """

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        super().__init__(model_name)
        if base_url is not None:
            # Local endpoint: use provided key or placeholder (Ollama often needs no key)
            key = api_key if api_key is not None else "ollama"
            self.client = openai.AsyncOpenAI(api_key=key, base_url=base_url.rstrip("/") + "/")
        else:
            self.client = openai.AsyncOpenAI(api_key=get_api_key("openai"))

    # Models that require max_completion_tokens instead of the legacy max_tokens.
    _NEW_TOKEN_PARAM_PREFIXES = ("gpt-5", "o1", "o3", "o4")

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

        Uses the OpenAI Chat Completions API with the ``tools`` parameter.
        Returns a :class:`ChatResponse` containing either text or tool calls.
        """
        if any(self.model_name.startswith(p) for p in self._NEW_TOKEN_PARAM_PREFIXES):
            token_kwarg = {"max_completion_tokens": 4096}
        else:
            token_kwarg = {"max_tokens": 4096}

        kwargs: dict = {
            "model": self.model_name,
            "messages": messages,
            **token_kwarg,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self.client.chat.completions.create(**kwargs)
        if not response.choices:
            return ChatResponse(text="", tool_calls=[], input_tokens=0, output_tokens=0)
        choice = response.choices[0]
        message = choice.message

        # Extract token usage from the response
        usage = getattr(response, "usage", None)
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        # Parse tool calls if present
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )
            return ChatResponse(
                text=message.content,  # May be None or contain text alongside tool calls
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        return ChatResponse(
            text=message.content or "",
            tool_calls=[],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
