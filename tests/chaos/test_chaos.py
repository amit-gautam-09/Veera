"""Chaos: malformed and hostile inputs never produce 5xx or invalid responses (docs/10 §10)."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import load_dir, push, push_base_dataset
from vera.api.schemas import ReplySend, TickAction
from vera.app import create_app
from vera.compose.playbook import KIND_FAMILY
from vera.config import Settings

KINDS = [*KIND_FAMILY, "totally_new_kind"]
WEIRD_MERCHANTS: list[dict[str, Any]] = [
    {"category_slug": "dentists"},  # bare minimum
    {"category_slug": "salons", "identity": None, "performance": None, "offers": None, "signals": None},
    {
        "category_slug": "gyms",
        "identity": {"languages": "hi", "owner_first_name": 42, "name": None},
        "performance": {"views": "many", "calls": None, "ctr": "high", "delta_7d": "x"},
        "offers": [None, "Haircut @ ₹99", {"title": 5}, {"status": "active"}],
        "customer_aggregate": [],
        "review_themes": [{"theme": None}, "bad"],
        "conversation_history": "nope",
        "subscription": {"status": "expired", "days_since_expiry": "7"},
    },
    {
        "category_slug": "pharmacies",
        "identity": {"name": "X" * 3000, "languages": ["en", "hi", "te"]},
        "performance": {"views": -5, "calls": 10**9, "ctr": 7.5, "delta_7d": {"views_pct": "down", "calls_pct": -9}},
    },
]
WEIRD_PAYLOADS: list[Any] = [
    {},
    None,
    [],
    "text",
    {"placeholder": True},
    {"metric": 5, "delta_pct": "big", "window": None},
    {"available_slots": [None, {"label": None}, "Mon"], "service_due": 7, "due_date": "not a date"},
    {"festival": None, "date": "2026-13-45", "match_time_iso": "yesterday", "affected_batches": "AT1"},
    {"top_item_id": "missing", "digest_item_id": None, "trends": "ORS_demand_+40", "molecule_list": "x"},
]


def _assert_valid_tick(resp: Any) -> None:
    assert resp.status_code == 200, resp.text
    for action in resp.json()["actions"]:
        TickAction.model_validate(action)
        assert action["body"].strip() and " ".join(action["template_params"]) == action["body"]


@pytest.mark.parametrize("merchant", WEIRD_MERCHANTS)
def test_weird_merchants_and_payloads_never_break_tick(client: TestClient, merchant: dict[str, Any]) -> None:
    push_base_dataset(client)
    mid = "m_chaos"
    assert push(client, "merchant", mid, {"merchant_id": mid, **merchant}).status_code == 200
    push(
        client,
        "customer",
        "c_chaos",
        {
            "customer_id": "c_chaos",
            "merchant_id": mid,
            "identity": {"name": None},
            "consent": {"scope": "all"},
            "preferences": None,
        },
    )
    ids = []
    for i, kind in enumerate(KINDS):
        for j, payload in enumerate(WEIRD_PAYLOADS):
            tid = f"t_{i}_{j}"
            trig = {
                "id": tid,
                "kind": kind,
                "merchant_id": mid,
                "customer_id": "c_chaos" if j % 2 else None,
                "scope": "customer" if j % 2 else "merchant",
                "payload": payload,
                "urgency": "high",
                "suppression_key": None if j % 3 else tid,
            }
            assert push(client, "trigger", tid, trig).status_code == 200
            ids.append(tid)
    for start in range(0, len(ids), 20):
        _assert_valid_tick(
            client.post("/v1/tick", json={"now": "2026-04-26T10:00:00Z", "available_triggers": ids[start : start + 20]})
        )


def test_weird_replies_never_break(client: TestClient) -> None:
    push_base_dataset(client)
    push(client, "merchant", "m_chaos", {"merchant_id": "m_chaos", **WEIRD_MERCHANTS[2]})
    messages = ["", " ", "😀" * 500, "?" * 100, "1", "haan", "STOP!!!", "a" * 20000, "\u0000​", "नमस्ते क्या हाल है"]
    for i, msg in enumerate(messages):
        for merchant in ("m_chaos", "m_unknown", None):
            r = client.post(
                "/v1/reply",
                json={
                    "conversation_id": f"cx_{i}_{merchant}",
                    "merchant_id": merchant,
                    "message": msg,
                    "turn_number": i,
                    "from_role": "merchant",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["action"] in {"send", "wait", "end"}
            if body["action"] == "send":
                ReplySend.model_validate(body)


def test_context_edge_cases(client: TestClient) -> None:
    cat = load_dir("categories")[0]
    assert push(client, "category", cat["slug"], cat, version=3).status_code == 200
    stale = push(client, "category", cat["slug"], cat, version=2)
    assert stale.status_code == 409 and stale.json()["current_version"] == 3
    for body in (
        {"scope": "merchant", "context_id": "", "version": 1, "payload": {}},
        {"scope": "merchant", "context_id": "x", "version": -1, "payload": {}},
        {"scope": "merchant", "context_id": "x", "version": 1.5, "payload": {}},
        {"scope": "merchant", "context_id": "x", "version": True, "payload": {}},
        {"scope": None, "context_id": "x", "version": 1, "payload": {}},
        [],
        "x",
        5,
    ):
        r = client.post("/v1/context", json=body)
        assert r.status_code == 400 and r.json()["accepted"] is False
    assert client.get("/v1/healthz").json()["contexts_loaded"]["merchant"] == 0


def test_concurrent_pushes_to_same_key_keep_the_max_version(settings: Settings) -> None:
    app = create_app(settings)
    merchant = copy.deepcopy(load_dir("merchants")[0])

    async def go() -> list[int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:

            async def one(v: int) -> int:
                r = await ac.post(
                    "/v1/context",
                    json={"scope": "merchant", "context_id": "m_x", "version": v, "payload": {**merchant, "v": v}},
                )
                return r.status_code

            return await asyncio.gather(*(one(v) for v in [*range(1, 26), *range(25, 0, -1)]))

    codes = asyncio.run(go())
    assert set(codes) <= {200, 409} and codes.count(200) >= 1
    store = app.state.store
    assert store.version("merchant", "m_x") == 25 and store.get("merchant", "m_x")["v"] == 25


WEIRD_CUSTOMERS: list[dict[str, Any]] = [
    {"identity": "Priya", "consent": "yes", "preferences": "evening", "relationship": "long"},
    {
        "identity": {"name": ["x"], "language_pref": 5, "phone_redacted": "<p>"},
        "consent": {"opted_in_at": 1, "scope": "all"},
        "preferences": {"reminder_opt_in": "no"},
        "relationship": {"last_visit": 20260401, "visits_total": "3"},
        "state": 9,
    },
    {"identity": {"name": "Mr.", "phone_redacted": "<p>"}, "consent": {"opted_in_at": "2025-01-01", "scope": ["x"]}},
]


@pytest.mark.parametrize("customer", WEIRD_CUSTOMERS)
def test_weird_customers_never_break_tick(client: TestClient, customer: dict[str, Any]) -> None:
    push_base_dataset(client)
    mid = "m_001_drmeera_dentist_delhi"
    push(client, "customer", "c_weird", {"customer_id": "c_weird", "merchant_id": mid, **customer})
    ids = []
    for i, kind in enumerate(k for k, fam in KIND_FAMILY.items() if fam.startswith("customer")):
        for j, payload in enumerate(WEIRD_PAYLOADS):
            tid = f"tc_{i}_{j}"
            push(
                client,
                "trigger",
                tid,
                {
                    "id": tid,
                    "kind": kind,
                    "scope": "customer",
                    "merchant_id": mid,
                    "customer_id": "c_weird",
                    "payload": payload,
                    "suppression_key": tid,
                },
            )
            ids.append(tid)
    for start in range(0, len(ids), 20):
        _assert_valid_tick(
            client.post("/v1/tick", json={"now": "2026-04-26T10:00:00Z", "available_triggers": ids[start : start + 20]})
        )
