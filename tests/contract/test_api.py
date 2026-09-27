"""Contract tests: every case in examples/api-call-examples.md plus error paths (docs/05-api-contract.md)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import load_dir, push, push_base_dataset

ACTION_FIELDS = {
    "conversation_id",
    "merchant_id",
    "customer_id",
    "send_as",
    "trigger_id",
    "template_name",
    "template_params",
    "body",
    "cta",
    "suppression_key",
    "rationale",
}
CTAS = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
MEERA = "m_001_drmeera_dentist_delhi"


def _merchant(mid: str = MEERA) -> dict[str, Any]:
    return next(m for m in load_dir("merchants") if m["merchant_id"] == mid)


def test_1_1_healthz_starts_empty(client: TestClient) -> None:
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and isinstance(body["uptime_seconds"], int)
    assert body["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}


def test_1_2_metadata_fields(client: TestClient) -> None:
    body = client.get("/v1/metadata").json()
    for key in ("team_name", "team_members", "model", "approach", "contact_email", "version", "submitted_at"):
        assert key in body
    assert body["team_members"] == ["Amit Gautam"]


def test_1_3_to_1_6_versioning(client: TestClient) -> None:
    cat = load_dir("categories")[0]
    r = push(client, "category", cat["slug"], cat)
    assert r.status_code == 200 and r.json()["accepted"] is True
    assert r.json()["ack_id"] == f"ack_category_{cat['slug']}_v1"
    assert r.json()["stored_at"].endswith("Z")

    merchant = _merchant()
    assert push(client, "merchant", MEERA, merchant).status_code == 200
    same = push(client, "merchant", MEERA, merchant)
    assert same.status_code == 409
    assert same.json() == {"accepted": False, "reason": "stale_version", "current_version": 1}

    bumped = {**merchant, "performance": {**merchant["performance"], "views": 2580}}
    assert push(client, "merchant", MEERA, bumped, version=2).status_code == 200
    assert client.app.state.store.get("merchant", MEERA)["performance"]["views"] == 2580  # type: ignore[attr-defined]

    lower = push(client, "merchant", MEERA, merchant, version=1)
    assert lower.status_code == 409 and lower.json()["current_version"] == 2


def test_1_7_full_warmup_counts(client: TestClient) -> None:
    push_base_dataset(client)
    counts = client.get("/v1/healthz").json()["contexts_loaded"]
    assert counts == {"category": 5, "merchant": 50, "customer": 200, "trigger": 0}


def test_invalid_scope_and_body(client: TestClient) -> None:
    r = client.post("/v1/context", json={"scope": "planet", "context_id": "x", "version": 1, "payload": {}})
    assert r.status_code == 400 and r.json()["reason"] == "invalid_scope"
    r = client.post("/v1/context", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["reason"] == "invalid_body"
    r = client.post("/v1/context", json={"scope": "merchant", "context_id": "x", "version": "1", "payload": {}})
    assert r.status_code == 400 and r.json()["reason"] == "invalid_body"
    r = client.post("/v1/context", json={"scope": "merchant", "context_id": "x", "version": 1, "payload": []})
    assert r.status_code == 400 and r.json()["reason"] == "invalid_body"


def test_payload_cap(client: TestClient) -> None:
    big = {"blob": "x" * 520_000}
    r = push(client, "category", "huge", big)
    assert r.status_code == 400 and r.json()["reason"] == "payload_too_large"


def test_2_1_to_2_3_trigger_push_and_tick(client: TestClient, triggers: dict[str, dict[str, Any]]) -> None:
    push_base_dataset(client)
    trg = triggers["trg_001_research_digest_dentists"]
    r = push(client, "trigger", trg["id"], trg)
    assert r.status_code == 200
    tick = client.post("/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": [trg["id"]]})
    assert tick.status_code == 200
    actions = tick.json()["actions"]
    assert len(actions) == 1
    action = actions[0]
    assert set(action) == ACTION_FIELDS
    assert action["cta"] in CTAS and action["send_as"] in {"vera", "merchant_on_behalf"}
    assert action["body"] and action["rationale"] and action["suppression_key"]
    assert " ".join(action["template_params"]) == action["body"]
    # same trigger again: already sent -> restraint
    again = client.post("/v1/tick", json={"now": "2026-04-26T10:40:00Z", "available_triggers": [trg["id"]]})
    assert again.json() == {"actions": []}
    # nothing listed -> empty
    assert client.post("/v1/tick", json={"now": "2026-04-26T10:45:00Z"}).json() == {"actions": []}


def test_tick_limits_and_unique_conversation_ids(client: TestClient, triggers: dict[str, dict[str, Any]]) -> None:
    push_base_dataset(client)
    for t in triggers.values():
        push(client, "trigger", t["id"], t)
    seen: set[str] = set()
    ids = list(triggers)
    for start in range(0, len(ids), 25):
        r = client.post("/v1/tick", json={"now": "2026-04-26T11:00:00Z", "available_triggers": ids[start : start + 25]})
        actions = r.json()["actions"]
        assert len(actions) <= 20
        merchant_facing = [a["merchant_id"] for a in actions if a["send_as"] == "vera"]
        assert len(merchant_facing) == len(set(merchant_facing))
        for a in actions:
            assert set(a) == ACTION_FIELDS
            assert a["conversation_id"] not in seen
            seen.add(a["conversation_id"])


def test_tick_ignores_unknown_and_malformed(client: TestClient) -> None:
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": ["nope"]})
    assert r.status_code == 200 and r.json() == {"actions": []}
    r = client.post("/v1/tick", content=b"garbage", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["actions"] == []


def test_2_4_to_2_7_reply_shapes(client: TestClient) -> None:
    cases = [
        {"merchant_id": MEERA, "from_role": "merchant", "message": "Yes please send the abstract.", "turn_number": 2},
        {"from_role": "merchant", "message": "Thank you for contacting Dr. Meera's Dental Clinic!", "turn_number": 2},
        {"message": "Not interested. Stop messaging me."},
        {"message": "Btw can you also help me with my GST filing this month?", "received_at": "2026-04-26T10:42:00Z"},
    ]
    for i, extra in enumerate(cases):
        r = client.post("/v1/reply", json={"conversation_id": f"conv_unknown_{i}", **extra})
        assert r.status_code == 200
        body = r.json()
        assert body["action"] in {"send", "wait", "end"}
        assert body["rationale"]
        if body["action"] == "send":
            assert body["body"] and body["cta"] in CTAS
        if body["action"] == "wait":
            assert body["wait_seconds"] >= 60


def test_reply_never_422(client: TestClient) -> None:
    r = client.post("/v1/reply", json={"conversation_id": "c1"})  # no message
    assert r.status_code == 200 and r.json()["action"] == "wait"
    r = client.post("/v1/reply", content=b"[", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["action"] == "wait"


def test_teardown_wipes(client: TestClient) -> None:
    push_base_dataset(client)
    assert client.post("/v1/teardown").json() == {"wiped": True}
    counts = client.get("/v1/healthz").json()["contexts_loaded"]
    assert counts == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
