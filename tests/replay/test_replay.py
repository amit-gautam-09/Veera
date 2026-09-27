"""Replay suite R1–R14 through the HTTP app, LLM off (docs/10 §8, docs/09)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import push, push_base_dataset
from vera.domain.language import hindi_word_count

MEERA = "m_001_drmeera_dentist_delhi"
QUALIFYING = ("would you", "do you", "can you tell", "what if", "how about")
ACTION_WORDS = ("done", "sending", "draft", "here", "confirm", "proceed", "next")


def reply(
    client: TestClient,
    conv: str,
    message: str,
    turn: int = 2,
    merchant: str = MEERA,
    role: str = "merchant",
    customer: str | None = None,
) -> dict[str, Any]:
    r = client.post(
        "/v1/reply",
        json={
            "conversation_id": conv,
            "merchant_id": merchant,
            "customer_id": customer,
            "from_role": role,
            "message": message,
            "turn_number": turn,
            "received_at": "2026-04-26T10:42:00Z",
        },
    )
    assert r.status_code == 200
    return r.json()


def tick(client: TestClient, *trigger_ids: str, now: str = "2026-04-26T10:35:00Z") -> list[dict[str, Any]]:
    return client.post("/v1/tick", json={"now": now, "available_triggers": list(trigger_ids)}).json()["actions"]


def setup(client: TestClient, triggers: dict[str, dict[str, Any]], *ids: str) -> None:
    push_base_dataset(client)
    for tid in ids:
        assert push(client, "trigger", tid, triggers[tid]).status_code == 200


def test_r1_auto_reply_hell_across_conversation_ids(client: TestClient) -> None:
    push_base_dataset(client)
    canned = "Thank you for contacting us! Our team will respond shortly."
    actions = [reply(client, f"conv_auto_{i}", canned, turn=i + 1)["action"] for i in range(1, 5)]
    assert actions == ["send", "wait", "end", "end"]
    second = reply(client, "conv_auto_x", canned, turn=9)
    assert second["action"] == "end"


def test_r1_first_auto_reply_note_is_owner_directed(client: TestClient) -> None:
    push_base_dataset(client)
    body = reply(client, "conv_a", "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.")
    assert body["action"] == "send" and "automatic reply" in body["body"].lower() and body["cta"] == "binary_yes_no"


def test_r2_intent_transition_delivers(client: TestClient) -> None:
    push_base_dataset(client)
    out = reply(client, "conv_intent_1", "Ok lets do it. Whats next?")
    assert out["action"] == "send", out
    low = out["body"].lower()
    assert any(w in low for w in ACTION_WORDS) and not any(q in low for q in QUALIFYING), out["body"]
    assert out["cta"] == "binary_confirm_cancel"
    done = reply(client, "conv_intent_1", "CONFIRM", turn=4)
    assert done["action"] == "send" and done["cta"] == "none"


def test_r2_intent_after_tick_delivers_promised_thing(client: TestClient, triggers: dict[str, Any]) -> None:
    setup(client, triggers, "trg_002_compliance_dci_radiograph")
    [action] = tick(client, "trg_002_compliance_dci_radiograph")
    out = reply(client, action["conversation_id"], "Yes please, go ahead")
    assert out["action"] == "send" and "checklist" in out["body"].lower()
    assert not any(q in out["body"].lower() for q in QUALIFYING)


def test_r3_hostile_stop_ends_and_suppresses(client: TestClient, triggers: dict[str, Any]) -> None:
    setup(client, triggers, "trg_001_research_digest_dentists")
    out = reply(client, "conv_hostile", "Stop messaging me. This is useless spam.")
    assert out["action"] == "end"
    assert tick(client, "trg_001_research_digest_dentists") == []


def test_r4_abuse_without_stop_gets_one_apology(client: TestClient) -> None:
    push_base_dataset(client)
    out = reply(client, "conv_h2", "This is useless.")
    assert out["action"] == "send" and "sorry" in out["body"].lower() and "₹" not in out["body"]
    again = reply(client, "conv_h2", "Useless bot, total waste of time.", turn=4)
    assert again["action"] == "end"


def test_r5_off_topic_gst(client: TestClient, triggers: dict[str, Any]) -> None:
    setup(client, triggers, "trg_022_cde_webinar_dentists")
    [action] = tick(client, "trg_022_cde_webinar_dentists")
    out = reply(client, action["conversation_id"], "Btw can you also help me with my GST filing this month?")
    assert out["action"] == "send" and "CA" in out["body"] and out["body"].count("?") <= 1


def test_r6_defer(client: TestClient) -> None:
    push_base_dataset(client)
    out = reply(client, "conv_d", "busy right now, call later")
    assert out["action"] == "wait" and 1800 <= out["wait_seconds"] <= 86400
    assert reply(client, "conv_d2", "kal baat karte hain", turn=2)["wait_seconds"] == 86400


def test_r7_language_switch(client: TestClient, triggers: dict[str, Any]) -> None:
    setup(client, triggers, "trg_024_perf_spike_zen")  # Chennai studio: English-primary thread
    [action] = tick(client, "trg_024_perf_spike_zen")
    out = reply(client, action["conversation_id"], "haan theek hai, bhej do", merchant="m_008_zenyoga_gym_chennai")
    assert out["action"] == "send" and hindi_word_count(out["body"]) >= 2, out["body"]


def _priya(client: TestClient, triggers: dict[str, Any]) -> str:
    setup(client, triggers, "trg_003_recall_due_priya")
    [action] = tick(client, "trg_003_recall_due_priya")
    assert action["send_as"] == "merchant_on_behalf" and action["cta"] == "multi_choice_slot"
    return str(action["conversation_id"])


def test_r8_customer_slot_selection(client: TestClient, triggers: dict[str, Any]) -> None:
    conv = _priya(client, triggers)
    out = reply(client, conv, "2", role="customer", customer="c_001_priya_for_m001")
    assert out["action"] == "send" and "Thu 6 Nov, 5pm" in out["body"]
    out2 = reply(client, "conv_priya_b", "Wed works", role="customer", customer="c_001_priya_for_m001")
    assert out2["action"] in {"send", "wait"}


def test_r8_weekday_matches_offered_slot(client: TestClient, triggers: dict[str, Any]) -> None:
    conv = _priya(client, triggers)
    out = reply(client, conv, "Wed works", role="customer", customer="c_001_priya_for_m001")
    assert "Wed 5 Nov, 6pm" in out["body"]


def test_r9_unknown_slot_is_not_invented(client: TestClient, triggers: dict[str, Any]) -> None:
    conv = _priya(client, triggers)
    out = reply(client, conv, "Friday 8pm?", role="customer", customer="c_001_priya_for_m001")
    assert out["action"] == "send" and "confirm" in out["body"].lower() and "8pm" not in out["body"]


def test_r10_three_unanswered_proactive_sends(client: TestClient, triggers: dict[str, Any]) -> None:
    ids = [
        "trg_002_compliance_dci_radiograph",
        "trg_022_cde_webinar_dentists",
        "trg_023_competitor_opened_dentist",
        "trg_001_research_digest_dentists",
    ]
    setup(client, triggers, *ids)
    sent = [len(tick(client, tid, now=f"2026-04-26T1{i}:00:00Z")) for i, tid in enumerate(ids)]
    assert sent == [1, 1, 1, 0]


def test_r11_reply_after_opt_out(client: TestClient, triggers: dict[str, Any]) -> None:
    setup(client, triggers, "trg_001_research_digest_dentists")
    assert reply(client, "conv_o", "Not interested. Stop messaging me.")["action"] == "end"
    out = reply(client, "conv_o", "can you help with my GST filing?", turn=4)
    assert out["action"] == "send" and out["cta"] == "none" and "?" not in out["body"]
    assert tick(client, "trg_001_research_digest_dentists") == []


def test_r12_idempotent_replay(client: TestClient) -> None:
    push_base_dataset(client)
    canned = "Thank you for contacting us! Our team will respond shortly."
    first = reply(client, "conv_r", canned, turn=2)
    assert reply(client, "conv_r", canned, turn=2) == first
    assert reply(client, "conv_r2", canned, turn=2)["action"] == "wait"  # counter advanced once, not twice


def test_r13_unknown_conversation(client: TestClient) -> None:
    push_base_dataset(client)
    out = reply(client, "conv_never_issued", "hello?", merchant="m_003_studio11_salon_hyderabad")
    assert out["action"] in {"send", "wait", "end"}


def test_r14_question_we_cannot_answer(client: TestClient) -> None:
    push_base_dataset(client)
    out = reply(client, "conv_q", "What's my competitor's rating?")
    assert out["action"] == "send" and ("don't have" in out["body"] or "nahi hai" in out["body"])


def test_repeated_intent_is_not_an_auto_reply(client: TestClient) -> None:
    push_base_dataset(client)
    first = reply(client, "conv_i1", "Ok lets do it. Whats next?")
    second = reply(client, "conv_i2", "Ok lets do it. Whats next?")
    assert first["action"] == second["action"] == "send" and "automatic" not in second["body"].lower()
