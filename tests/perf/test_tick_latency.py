"""Tick latency with a fake LLM of known delay (NFR-1, NFR-2; docs/10 §7)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from tests.golden.test_golden import _store
from vera.api.schemas import TickRequest
from vera.compose.composer import Composer
from vera.planner.tick import plan_tick

COLD_BUDGET_S = 8.0
WARM_BUDGET_S = 0.5


class SlowGateway:
    model = "slow-fake"

    def __init__(self, delay: float, concurrency: int = 10) -> None:
        self.delay, self.sem = delay, asyncio.Semaphore(concurrency)

    async def complete_json(self, system: str, user: str, schema: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        async with self.sem:
            await asyncio.sleep(min(self.delay, timeout_s))
            if self.delay > timeout_s:
                raise TimeoutError
            return {"opener": "x", "middle": "", "ask": ""}  # invalid on purpose -> fallback, keeps test offline


def _twenty_merchant_triggers() -> list[str]:
    store = _store()
    seen, ids = set(), []
    for tid, trg in store.triggers():
        if trg.get("scope") == "merchant" and trg["merchant_id"] not in seen:
            seen.add(trg["merchant_id"])
            ids.append(tid)
    return ids[:20]


def _tick(composer: Composer, store: Any, ids: list[str], deadline_s: float) -> tuple[int, float]:
    async def go() -> tuple[int, float]:
        started = time.monotonic()
        actions = await plan_tick(
            store,
            TickRequest(now="2026-04-26T10:00:00Z", available_triggers=ids),
            composer.compose,
            composer.fallback,
            deadline_s,
        )
        return len(actions), time.monotonic() - started

    return asyncio.run(go())


def test_cold_tick_with_slow_llm_meets_budget() -> None:
    store, ids = _store(), _twenty_merchant_triggers()
    composer = Composer(store, SlowGateway(delay=20.0))
    count, elapsed = _tick(composer, store, ids, deadline_s=2.0)
    assert elapsed < COLD_BUDGET_S and elapsed < 3.0
    assert 15 <= count <= 20  # every composable trigger still gets a (fallback) action


def test_warm_tick_is_fast() -> None:
    store, ids = _store(), _twenty_merchant_triggers()

    composer = Composer(store, None)  # fallback path only: pure CPU
    count, elapsed = _tick(composer, store, ids, deadline_s=7.0)
    assert count >= 15 and elapsed < WARM_BUDGET_S
