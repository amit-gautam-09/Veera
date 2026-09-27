"""Golden set: 30 canonical pairs + one trigger per kind missing from them (docs/10 §5).

LLM disabled. Every case must yield a grounded, valid message (or a documented skip), and the output is
snapshot-compared so any wording change is reviewed. Regenerate with: UPDATE_GOLDEN=1 pytest tests/golden
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests.conftest import EXPANDED, load_dir
from vera.compose.composer import Composer, check_parts, prepare
from vera.compose.models import ComposedMessage, Skip
from vera.compose.validator import plagiarism_ratio
from vera.store.state import Store

SNAPSHOT = Path(__file__).with_name("snapshots.json")
EXTRA = [
    "trg_001_research_digest_dentists",
    "trg_005_renewal_due_bharat",
    "trg_011_review_theme_late_delivery",
    "trg_014_seasonal_acquisition_dip_powerhouse",
    "trg_018_supply_atorvastatin_recall",
    "trg_017_kids_yoga_trial_followup_karthik",
    "trg_007_bridal_followup_kavya",
    "trg_009_winback_glamour",
]
ALLOWED_SKIPS: dict[str, str] = {}  # test_id -> reason prefix, when restraint is the right answer


def _store() -> Store:
    store = Store()
    for scope, folder, key in [
        ("category", "categories", "slug"),
        ("merchant", "merchants", "merchant_id"),
        ("customer", "customers", "customer_id"),
        ("trigger", "triggers", "id"),
    ]:
        for item in load_dir(folder):
            store.put_context(scope, item[key], 1, item)
    return store


def _cases() -> list[tuple[str, str]]:
    pairs = json.loads((EXPANDED / "test_pairs.json").read_text(encoding="utf-8"))["pairs"]
    return [(p["test_id"], p["trigger_id"]) for p in pairs] + [(f"G{i + 1:02d}", t) for i, t in enumerate(EXTRA)]


STORE = _store()
COMPOSER = Composer(STORE)
CASES = _cases()


def _result(trigger_id: str) -> ComposedMessage | Skip:
    return COMPOSER.fallback(trigger_id)


@pytest.mark.parametrize(("test_id", "trigger_id"), CASES)
def test_case_is_grounded_and_valid(test_id: str, trigger_id: str) -> None:
    msg = _result(trigger_id)
    if isinstance(msg, Skip):
        assert test_id in ALLOWED_SKIPS and msg.reason.startswith(ALLOWED_SKIPS[test_id]), msg.reason
        return
    prep = prepare(STORE, trigger_id)
    assert not isinstance(prep, Skip)
    check = check_parts(STORE, prep, *msg.template_params)
    assert check.ok, check.violations
    assert " ".join(msg.template_params) == msg.body
    assert msg.body.count("?") <= 1 and msg.template_params[2].strip()
    assert "http" not in msg.body and "www." not in msg.body
    assert not re.search(r"\b[a-z]+_[a-z_]+\b", msg.body), "snake_case leaked"
    assert plagiarism_ratio(msg.body) <= 0.6
    trigger = STORE.get("trigger", trigger_id) or {}
    if trigger.get("scope") == "customer" and msg.send_as == "merchant_on_behalf":
        assert msg.customer_id == trigger.get("customer_id")
    if msg.send_as == "vera":
        assert msg.customer_id is None


def test_snapshots_match() -> None:
    current = {}
    for test_id, trigger_id in CASES:
        msg = _result(trigger_id)
        current[test_id] = (
            {"skip": msg.reason}
            if isinstance(msg, Skip)
            else {"trigger_id": trigger_id, "cta": msg.cta, "send_as": msg.send_as, "body": msg.body}
        )
    if os.getenv("UPDATE_GOLDEN") or not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    stored = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    changed = [k for k in current if current[k] != stored.get(k)]
    assert not changed, f"golden output changed for {changed}; review and rerun with UPDATE_GOLDEN=1"


def test_deterministic() -> None:
    first = [(_result(t).model_dump() if not isinstance(_result(t), Skip) else None) for _, t in CASES]
    second = [(_result(t).model_dump() if not isinstance(_result(t), Skip) else None) for _, t in CASES]
    assert first == second
