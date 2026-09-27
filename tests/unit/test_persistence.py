"""Write-through persistence and the restore window (ADR-003)."""

from __future__ import annotations

import time
from pathlib import Path

from vera.store.sqlite import Database
from vera.store.state import Conversation, Store

WINDOW_S = 7200


def _store(path: Path) -> Store:
    store = Store(Database(path))
    store.restore(WINDOW_S)
    return store


def test_restore_within_window(tmp_path: Path) -> None:
    db_path = tmp_path / "vera.db"
    store = _store(db_path)
    store.put_context("merchant", "m_1", 3, {"merchant_id": "m_1", "category_slug": "gyms"})
    store.save_conversation(Conversation(conversation_id="conv_1", merchant_id="m_1"))
    store.record_suppression(
        {"suppression_key": "k1", "merchant_id": "m_1", "trigger_id": "t", "conversation_id": "conv_1"}
    )
    flags = store.merchant_flags("m_1")
    flags.opted_out = True
    store.save_flags(flags)
    assert store.db is not None
    store.db.close()

    reopened = _store(db_path)
    assert reopened.version("merchant", "m_1") == 3
    assert "conv_1" in reopened.conversations
    assert reopened.is_suppressed("k1")
    assert reopened.flags["m_1"].opted_out
    assert reopened.counts()["merchant"] == 1


def test_wipe_outside_window(tmp_path: Path) -> None:
    db_path = tmp_path / "vera.db"
    store = _store(db_path)
    store.put_context("category", "gyms", 1, {"slug": "gyms"})
    assert store.db is not None
    stale = time.time() - WINDOW_S - 60
    with store.db.conn:
        store.db.conn.execute("UPDATE meta SET value=? WHERE key='last_write_at'", (repr(stale),))
    store.db.close()

    reopened = _store(db_path)
    assert reopened.counts() == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    assert reopened.db is not None and reopened.db.last_write_at() is None


def test_stale_version_leaves_state_untouched(tmp_path: Path) -> None:
    store = _store(tmp_path / "vera.db")
    assert store.put_context("trigger", "t1", 2, {"id": "t1", "kind": "x"}).accepted
    result = store.put_context("trigger", "t1", 2, {"id": "t1", "kind": "changed"})
    assert not result.accepted and result.current_version == 2
    assert store.get("trigger", "t1") == {"id": "t1", "kind": "x"}


def test_teardown_wipes_disk(tmp_path: Path) -> None:
    db_path = tmp_path / "vera.db"
    store = _store(db_path)
    store.put_context("category", "gyms", 1, {"slug": "gyms"})
    store.wipe()
    assert store.db is not None
    store.db.close()
    assert _store(db_path).counts()["category"] == 0
