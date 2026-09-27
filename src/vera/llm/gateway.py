"""LLM gateway: one Anthropic implementation behind a small protocol (ADR-002, TRD §4.12)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Protocol, cast

import anthropic
from anthropic.types import Message

from vera.observability.log import log_event

MAX_TOKENS = 700
MIN_TIMEOUT_S = 0.5


class LLMUnavailable(Exception):
    """Timeout, rate limit, server/connection error, or unusable output: the caller falls back."""


class LLMGateway(Protocol):
    model: str

    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any], timeout_s: float
    ) -> dict[str, Any]: ...


class AnthropicGateway:
    def __init__(self, api_key: str, model: str, max_concurrency: int, effort: str | None = None) -> None:
        self.model = model
        self.effort = effort
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        self._sem = asyncio.Semaphore(max_concurrency)

    async def complete_json(self, system: str, user: str, schema: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        if timeout_s < MIN_TIMEOUT_S:
            raise LLMUnavailable("no time left")
        started = time.monotonic()
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            output_config["effort"] = self.effort
        try:
            async with self._sem:
                remaining = timeout_s - (time.monotonic() - started)
                if remaining < MIN_TIMEOUT_S:
                    raise LLMUnavailable("deadline passed while queued")
                params: dict[str, Any] = {
                    "model": self.model,
                    "max_tokens": MAX_TOKENS,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                    "thinking": {"type": "disabled"},
                    "output_config": output_config,
                    "timeout": remaining,
                }
                response = cast(Message, await self._client.messages.create(**params))
        except anthropic.BadRequestError as exc:
            log_event("llm.bad_request", model=self.model, error=str(exc)[:300])
            raise LLMUnavailable("bad request") from exc
        except anthropic.RateLimitError as exc:
            log_event("llm.rate_limited", model=self.model)
            raise LLMUnavailable("rate limited") from exc
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            log_event("llm.timeout", model=self.model, elapsed_ms=int((time.monotonic() - started) * 1000))
            raise LLMUnavailable("timeout") from exc
        except anthropic.APIStatusError as exc:
            log_event("llm.status_error", model=self.model, status=exc.status_code)
            raise LLMUnavailable(f"status {exc.status_code}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(response, "usage", None)
        log_event(
            "llm.call",
            model=self.model,
            latency_ms=latency_ms,
            tokens_in=getattr(usage, "input_tokens", None),
            tokens_out=getattr(usage, "output_tokens", None),
            stop_reason=response.stop_reason,
        )
        if response.stop_reason in {"refusal", "max_tokens"}:
            raise LLMUnavailable(f"stop_reason {response.stop_reason}")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable("unparseable output") from exc
        if not isinstance(data, dict):
            raise LLMUnavailable("output is not an object")
        return data
