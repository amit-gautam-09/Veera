"""LLM gateways behind one small protocol (ADR-002, TRD §4.12).

- AnthropicGateway: Claude via the official SDK (structured output, thinking disabled).
- OpenAICompatibleGateway: any OpenAI-compatible endpoint via the official `openai` SDK. Used for Google Gemini's
  free tier (base URL https://generativelanguage.googleapis.com/v1beta/openai/), also fits Cerebras / Mistral.
Both: no SDK retries, a concurrency cap, and every failure mapped to LLMUnavailable so the caller falls back to
deterministic wording at once. `timeout_s` is the caller's whole budget, queue wait included; the HTTP call itself
is capped at `call_timeout_s` so one hung request cannot hold a concurrency slot for the whole budget.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, Protocol, cast

import anthropic
from anthropic.types import Message

from vera.observability.log import log_event

if TYPE_CHECKING:
    from vera.config import Settings

MAX_TOKENS = 700
MIN_TIMEOUT_S = 0.5
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class LLMUnavailable(Exception):
    """Timeout, rate limit, server/connection error, or unusable output: the caller falls back."""


class LLMGateway(Protocol):
    model: str

    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any], timeout_s: float
    ) -> dict[str, Any]: ...


def _parse_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable("unparseable output") from exc
    if not isinstance(data, dict):
        raise LLMUnavailable("output is not an object")
    return data


class AnthropicGateway:
    def __init__(
        self, api_key: str, model: str, max_concurrency: int, effort: str | None = None, call_timeout_s: float = 6.0
    ) -> None:
        self.model = model
        self.call_timeout_s = call_timeout_s
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
                    "timeout": min(remaining, self.call_timeout_s),
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
        usage = getattr(response, "usage", None)
        log_event(
            "llm.call",
            model=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            tokens_in=getattr(usage, "input_tokens", None),
            tokens_out=getattr(usage, "output_tokens", None),
            stop_reason=response.stop_reason,
        )
        if response.stop_reason in {"refusal", "max_tokens"}:
            raise LLMUnavailable(f"stop_reason {response.stop_reason}")
        return _parse_object(next((b.text for b in response.content if b.type == "text"), ""))


class OpenAICompatibleGateway:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        max_concurrency: int,
        reasoning_effort: str | None = None,
        call_timeout_s: float = 6.0,
    ) -> None:
        import openai  # imported lazily: only needed when this provider is configured

        self._openai = openai
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.call_timeout_s = call_timeout_s
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self._sem = asyncio.Semaphore(max_concurrency)

    async def complete_json(self, system: str, user: str, schema: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        if timeout_s < MIN_TIMEOUT_S:
            raise LLMUnavailable("no time left")
        oa, started = self._openai, time.monotonic()
        try:
            async with self._sem:
                remaining = timeout_s - (time.monotonic() - started)
                if remaining < MIN_TIMEOUT_S:
                    raise LLMUnavailable("deadline passed while queued")
                params: dict[str, Any] = {
                    "model": self.model,
                    "max_tokens": MAX_TOKENS,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "vera_output", "strict": True, "schema": schema},
                    },
                    "timeout": min(remaining, self.call_timeout_s),
                }
                if self.reasoning_effort:
                    params["reasoning_effort"] = self.reasoning_effort
                response = await self._client.chat.completions.create(**params)
        except oa.BadRequestError as exc:
            log_event("llm.bad_request", model=self.model, error=str(exc)[:300])
            raise LLMUnavailable("bad request") from exc
        except oa.RateLimitError as exc:
            log_event("llm.rate_limited", model=self.model)
            raise LLMUnavailable("rate limited") from exc
        except (oa.APITimeoutError, oa.APIConnectionError) as exc:
            log_event("llm.timeout", model=self.model, elapsed_ms=int((time.monotonic() - started) * 1000))
            raise LLMUnavailable("timeout") from exc
        except oa.APIStatusError as exc:
            log_event("llm.status_error", model=self.model, status=exc.status_code)
            raise LLMUnavailable(f"status {exc.status_code}") from exc
        choice = response.choices[0] if response.choices else None
        usage = getattr(response, "usage", None)
        log_event(
            "llm.call",
            model=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            tokens_in=getattr(usage, "prompt_tokens", None),
            tokens_out=getattr(usage, "completion_tokens", None),
            stop_reason=getattr(choice, "finish_reason", None),
        )
        if choice is None or choice.finish_reason in {"length", "content_filter"}:
            raise LLMUnavailable(f"finish_reason {getattr(choice, 'finish_reason', None)}")
        return _parse_object(choice.message.content or "")


def make_gateway(settings: Settings) -> LLMGateway | None:
    """The configured gateway, or None (deterministic mode) when disabled or no key is set."""
    if not settings.llm_active:
        return None
    if settings.llm_provider == "anthropic":
        assert settings.anthropic_api_key
        return AnthropicGateway(
            settings.anthropic_api_key,
            settings.composer_model,
            settings.llm_max_concurrency,
            settings.llm_effort,
            settings.llm_timeout_s,
        )
    assert settings.llm_api_key
    base_url = settings.llm_base_url or GEMINI_BASE_URL
    return OpenAICompatibleGateway(
        settings.llm_api_key,
        settings.composer_model,
        base_url,
        settings.llm_max_concurrency,
        settings.llm_effort,
        settings.llm_timeout_s,
    )
