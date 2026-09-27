"""Offline deliverables: bot.compose and conversation_handlers.respond use the live pipeline (brief §7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import EXPANDED, ROOT

REQUIRED = {"body", "cta", "send_as", "suppression_key", "rationale"}


def _read(folder: str, name: str) -> dict:
    return json.loads((EXPANDED / folder / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("VERA_BOT_CACHE", str(tmp_path / "cache.db"))


def test_bot_compose_matches_contract() -> None:
    import importlib
    import sys

    sys.path.insert(0, str(ROOT))
    bot = importlib.import_module("bot")
    trigger = _read("triggers", "trg_003_recall_due_priya")
    merchant = _read("merchants", trigger["merchant_id"])
    out = bot.compose(
        _read("categories", merchant["category_slug"]), merchant, trigger, _read("customers", trigger["customer_id"])
    )
    assert set(out) >= REQUIRED and out["send_as"] == "merchant_on_behalf" and "Priya" in out["body"]
    again = bot.compose(
        _read("categories", merchant["category_slug"]), merchant, trigger, _read("customers", trigger["customer_id"])
    )
    assert again == out


def test_submission_file_has_30_valid_lines() -> None:
    lines = (ROOT / "submission.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 30
    ids = [json.loads(line)["test_id"] for line in lines]
    assert ids == [f"T{i:02d}" for i in range(1, 31)]
    for line in lines:
        row = json.loads(line)
        assert set(row) >= REQUIRED and row["body"] and "http" not in row["body"]


def test_conversation_handler_delivers_on_accept() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from conversation_handlers import respond

    trigger = _read("triggers", "trg_002_compliance_dci_radiograph")
    merchant = _read("merchants", trigger["merchant_id"])
    state = {
        "conversation_id": "c1",
        "merchant": merchant,
        "category": _read("categories", "dentists"),
        "trigger": trigger,
        "turns": [{"role": "vera", "body": "Dr. Meera, ... Want a 1-page checklist?"}],
    }
    out = respond(state, "Yes please")
    assert out["action"] == "send" and "checklist" in out["body"].lower()
