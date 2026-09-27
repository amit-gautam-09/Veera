"""Adaptation to mid-test context injection (docs/10 §9): new digest items, perf updates, new customers."""

from __future__ import annotations

import copy
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import load_dir, push, push_base_dataset
from tests.replay.test_replay import tick
from vera.domain.language import hindi_word_count

MEERA = "m_001_drmeera_dentist_delhi"
NEW_ITEM = {
    "id": "d_2026W18_ida_sterilisation_NEW",
    "kind": "research",
    "title": "Autoclave cycle validation cuts cross-infection incidents 41% in solo practices",
    "source": "IDA Bulletin May 2026, p.7",
    "trial_n": 640,
    "summary": "A 640-clinic audit found weekly spore-test validation reduced reported cross-infection incidents by 41%.",
    "actionable": "Add a weekly spore test to your sterilisation log",
}


def _category_v2() -> dict[str, Any]:
    cat = copy.deepcopy(next(c for c in load_dir("categories") if c["slug"] == "dentists"))
    cat["digest"] = [NEW_ITEM, *cat["digest"]]
    return cat


def test_new_digest_item_is_used_after_version_bump(client: TestClient, triggers: dict[str, Any]) -> None:
    push_base_dataset(client)
    push(client, "trigger", "trg_002_compliance_dci_radiograph", triggers["trg_002_compliance_dci_radiograph"])
    [first] = tick(client, "trg_002_compliance_dci_radiograph")
    assert push(client, "category", "dentists", _category_v2(), version=2).status_code == 200
    new_trigger = {
        "id": "trg_new_research_m001",
        "scope": "merchant",
        "kind": "research_digest",
        "source": "external",
        "merchant_id": MEERA,
        "customer_id": None,
        "payload": {"category": "dentists", "top_item_id": NEW_ITEM["id"]},
        "urgency": 2,
        "suppression_key": "research:dentists:2026-W18",
        "expires_at": "2026-05-10T00:00:00Z",
    }
    push(client, "trigger", new_trigger["id"], new_trigger)
    [second] = tick(client, new_trigger["id"], now="2026-04-26T11:00:00Z")
    assert "IDA Bulletin May 2026" in second["body"] and second["body"] != first["body"]


def test_perf_update_reaches_the_next_message(client: TestClient, triggers: dict[str, Any]) -> None:
    push_base_dataset(client)
    push(client, "trigger", "trg_021_unverified_gbp_sunrise", triggers["trg_021_unverified_gbp_sunrise"])
    merchant = copy.deepcopy(
        next(m for m in load_dir("merchants") if m["merchant_id"] == "m_010_sunrisepharm_pharmacy_lucknow")
    )
    merchant["performance"]["views"] = 999
    assert push(client, "merchant", merchant["merchant_id"], merchant, version=2).status_code == 200
    [action] = tick(client, "trg_021_unverified_gbp_sunrise")
    assert "999" in action["body"] and "720" not in action["body"]


def test_injected_customer_gets_a_customer_facing_message(client: TestClient) -> None:
    push_base_dataset(client)
    customer = {
        "customer_id": "c_new_meher_for_m001",
        "merchant_id": MEERA,
        "identity": {"name": "Meher", "phone_redacted": "<phone>", "language_pref": "hi-en mix"},
        "relationship": {
            "first_visit": "2025-10-02",
            "last_visit": "2026-04-02",
            "visits_total": 3,
            "services_received": ["cleaning"],
        },
        "state": "active",
        "preferences": {"preferred_slots": "weekday_evening", "reminder_opt_in": True},
        "consent": {"opted_in_at": "2025-10-02", "scope": ["recall_reminders"]},
    }
    assert push(client, "customer", customer["customer_id"], customer).status_code == 200
    trig = {
        "id": "trg_new_recall_meher",
        "scope": "customer",
        "kind": "recall_due",
        "source": "internal",
        "merchant_id": MEERA,
        "customer_id": customer["customer_id"],
        "payload": {
            "service_due": "6_month_cleaning",
            "last_service_date": "2026-04-02",
            "due_date": "2026-10-02",
            "available_slots": [{"iso": "2026-09-30T18:00:00+05:30", "label": "Wed 30 Sep, 6pm"}],
        },
        "urgency": 3,
        "suppression_key": "recall:c_new_meher:6mo",
        "expires_at": "2026-10-30T00:00:00Z",
    }
    push(client, "trigger", trig["id"], trig)
    [action] = tick(client, trig["id"])
    assert action["send_as"] == "merchant_on_behalf" and action["customer_id"] == customer["customer_id"]
    assert "Meher" in action["body"] and "Wed 30 Sep, 6pm" in action["body"] and hindi_word_count(action["body"]) >= 2
