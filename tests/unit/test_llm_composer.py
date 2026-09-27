"""LLM path with a fake gateway: success, repair, rejection, timeout, cache, precompute (docs/06, ADR-004/005)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from tests.golden.test_golden import _store
from vera.compose.composer import Composer, input_hash, prepare
from vera.compose.models import ComposedMessage, Skip
from vera.llm.gateway import LLMUnavailable

TRIGGER = "trg_004_perf_dip_bharat"  # Bharat Dental, calls -50%, baseline 12, unverified


class FakeGateway:
    model = "fake-model"

    def __init__(self, outputs: list[Any], delay: float = 0.0) -> None:
        self.outputs, self.delay, self.calls = list(outputs), delay, 0

    async def complete_json(self, system: str, user: str, schema: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        out = self.outputs.pop(0) if self.outputs else self.outputs_last
        if isinstance(out, Exception):
            raise out
        return out

    @property
    def outputs_last(self) -> dict[str, Any]:
        return GOOD


GOOD = {
    "opener": "Dr. Bharat,",
    "middle": "Is hafte aapke calls 50% kam hue hain, baseline 12 ke against. Ek wajah ho sakti hai ki Google profile "
    "abhi verified nahi hai.",
    "ask": "Kya main aaj verification shuru kar doon?",
}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_llm_success_is_cached_and_deterministic() -> None:
    store, gw = _store(), FakeGateway([GOOD])
    composer = Composer(store, gw)
    first = run(composer.compose(TRIGGER, time.monotonic() + 5))
    assert isinstance(first, ComposedMessage) and first.path == "llm"
    assert first.body.startswith("Dr. Bharat,") and first.template_params[2] == GOOD["ask"]
    second = run(composer.compose(TRIGGER, time.monotonic() + 5))
    assert isinstance(second, ComposedMessage) and second.path == "cache" and second.body == first.body
    assert gw.calls == 1


def test_fabricated_sentence_is_dropped() -> None:
    bad = dict(GOOD, middle=GOOD["middle"] + " Aapke 31 competitors ne yeh kar liya hai.")
    store = _store()
    msg = run(Composer(store, FakeGateway([bad])).compose(TRIGGER, time.monotonic() + 5))
    assert isinstance(msg, ComposedMessage) and msg.path == "repaired" and "31" not in msg.body


def test_unfixable_output_gets_one_repair_call_then_fallback() -> None:
    english = {"opener": "Dr. Bharat,", "middle": "Your calls fell 50% this week.", "ask": "Want me to fix it?"}
    gw = FakeGateway([english, english])
    msg = run(Composer(_store(), gw, repair_min_s=0.5).compose(TRIGGER, time.monotonic() + 5))
    assert isinstance(msg, ComposedMessage) and msg.path == "fallback" and gw.calls == 2


@pytest.mark.parametrize("error", [LLMUnavailable("rate limited"), RuntimeError("boom")])
def test_llm_failure_falls_back(error: Exception) -> None:
    msg = run(Composer(_store(), FakeGateway([error])).compose(TRIGGER, time.monotonic() + 5))
    assert isinstance(msg, ComposedMessage) and msg.path == "fallback"


def test_slow_llm_respects_deadline_and_fills_cache_later() -> None:
    store, gw = _store(), FakeGateway([GOOD], delay=0.6)
    composer = Composer(store, gw)

    async def scenario() -> tuple[ComposedMessage | Skip, float, ComposedMessage | Skip]:
        started = time.monotonic()
        first = await composer.compose(TRIGGER, time.monotonic() + 0.2)
        elapsed = time.monotonic() - started
        await asyncio.sleep(0.8)  # background task finishes and caches
        later = await composer.compose(TRIGGER, time.monotonic() + 0.2)
        return first, elapsed, later

    first, elapsed, later = run(scenario())
    assert isinstance(first, ComposedMessage) and first.path == "fallback" and elapsed < 0.5
    assert isinstance(later, ComposedMessage) and later.path == "cache"


def test_precompute_on_trigger_push() -> None:
    store, gw = _store(), FakeGateway([GOOD])
    composer = Composer(store, gw)

    async def scenario() -> ComposedMessage | Skip:
        composer.on_context("trigger", TRIGGER)
        await asyncio.sleep(0.05)
        return await composer.compose(TRIGGER, time.monotonic() + 1)

    msg = run(scenario())
    assert isinstance(msg, ComposedMessage) and msg.path == "cache" and gw.calls == 1


def test_input_hash_changes_with_context_content() -> None:
    store = _store()
    prep = prepare(store, TRIGGER)
    assert not isinstance(prep, Skip)
    before = input_hash(prep, "m")
    merchant = dict(store.get("merchant", "m_002_bharat_dentist_mumbai") or {})
    merchant["performance"] = dict(merchant["performance"], views=1234)
    store.put_context("merchant", "m_002_bharat_dentist_mumbai", 2, merchant)
    prep2 = prepare(store, TRIGGER)
    assert not isinstance(prep2, Skip) and input_hash(prep2, "m") != before
