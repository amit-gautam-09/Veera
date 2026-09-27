"""Planner and store invariants P1–P8 (docs/10 §4)."""

from __future__ import annotations

import asyncio
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.golden.test_golden import _store
from vera.api.schemas import TickAction, TickRequest
from vera.compose.composer import Composer
from vera.planner.tick import MAX_ACTIONS, plan_tick
from vera.store.state import Store

ALL_TRIGGERS = [tid for tid, _ in _store().triggers()]
MERCHANTS = sorted({t["merchant_id"] for _, t in _store().triggers()})
SETTINGS = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])

tick_lists = st.lists(
    st.lists(st.sampled_from(ALL_TRIGGERS) | st.text(min_size=1, max_size=8), min_size=0, max_size=40),
    min_size=1,
    max_size=6,
)


def _run(store: Store, ticks: list[list[str]]) -> list[list[TickAction]]:
    composer = Composer(store)

    async def go() -> list[list[TickAction]]:
        out = []
        for i, ids in enumerate(ticks):
            req = TickRequest(now=f"2026-04-26T10:{i * 5:02d}:00Z", available_triggers=ids)
            out.append(await plan_tick(store, req, composer.compose, composer.fallback, 7.0))
        return out

    return asyncio.run(go())


@SETTINGS
@given(ticks=tick_lists, opted_out=st.sets(st.sampled_from(MERCHANTS), max_size=8))
def test_tick_invariants(ticks: list[list[str]], opted_out: set[str]) -> None:
    store = _store()
    for mid in opted_out:
        flags = store.merchant_flags(mid)
        flags.opted_out = True
        store.save_flags(flags)
    results = _run(store, ticks)
    conv_ids: set[str] = set()
    keys: set[str] = set()
    for actions in results:
        assert len(actions) <= MAX_ACTIONS  # P1
        vera_merchants = [a.merchant_id for a in actions if a.send_as == "vera"]
        assert len(vera_merchants) == len(set(vera_merchants))  # P5
        for a in actions:
            assert a.conversation_id not in conv_ids  # P2
            conv_ids.add(a.conversation_id)
            assert a.suppression_key not in keys  # P3
            keys.add(a.suppression_key)
            assert a.merchant_id not in opted_out  # P4 (merchant)
            if a.send_as == "merchant_on_behalf":  # P4 (consent)
                customer = store.get("customer", a.customer_id) or {}
                assert customer.get("consent", {}).get("opted_in_at") and customer["consent"].get("scope")
                assert customer.get("preferences", {}).get("reminder_opt_in") is not False
            TickAction.model_validate(a.model_dump())  # P6 shape
            assert a.body.strip() and a.rationale.strip() and " ".join(a.template_params) == a.body


@SETTINGS
@given(ticks=tick_lists)
def test_determinism_on_fresh_store(ticks: list[list[str]]) -> None:
    first = [[a.model_dump() for a in acts] for acts in _run(_store(), ticks)]
    second = [[a.model_dump() for a in acts] for acts in _run(_store(), ticks)]
    assert first == second  # P8


pushes = st.lists(
    st.tuples(
        st.sampled_from(["category", "merchant", "customer", "trigger"]),
        st.sampled_from(["a", "b", "c"]),
        st.integers(min_value=0, max_value=6),
        st.integers(),
    ),
    max_size=40,
)


@SETTINGS
@given(seq=pushes)
def test_context_store_versioning(seq: list[tuple[str, str, int, int]]) -> None:
    store = Store()
    best: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
    for scope, cid, version, marker in seq:
        payload = {"marker": marker}
        before = store.get(scope, cid)
        result = store.put_context(scope, cid, version, payload)
        current = best.get((scope, cid))
        if current is None or version > current[0]:
            assert result.accepted
            best[(scope, cid)] = (version, payload)
        else:  # P7: same-or-lower version is rejected and leaves state untouched
            assert not result.accepted and result.current_version == current[0]
            assert store.get(scope, cid) == before
    for (scope, cid), (version, payload) in best.items():
        assert store.version(scope, cid) == version and store.get(scope, cid) == payload
    counts = store.counts()
    for scope in ("category", "merchant", "customer", "trigger"):
        assert counts[scope] == sum(1 for s, _ in best if s == scope)
