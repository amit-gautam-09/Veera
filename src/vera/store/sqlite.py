"""SQLite write-through persistence with a restore window (ADR-003, docs/03-backend-schema.md §4)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contexts (
  scope TEXT NOT NULL CHECK (scope IN ('category','merchant','customer','trigger')),
  context_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  stored_at TEXT NOT NULL,
  PRIMARY KEY (scope, context_id)
);
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  merchant_id TEXT,
  state_json TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_merchant ON conversations(merchant_id);
CREATE TABLE IF NOT EXISTS suppressions (
  suppression_key TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  entry_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS merchant_flags (
  merchant_id TEXT PRIMARY KEY,
  flags_json TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS compose_cache (
  input_hash TEXT PRIMARY KEY,
  output_json TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  endpoint TEXT NOT NULL,
  trigger_id TEXT,
  conversation_id TEXT,
  record_json TEXT NOT NULL
);
"""

WIPE_TABLES = ("contexts", "conversations", "suppressions", "merchant_flags", "compose_cache", "audit_log")


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(DDL)
        self._set_meta("schema_version", SCHEMA_VERSION)
        self.conn.commit()

    # --- lifecycle -------------------------------------------------------------------------
    def last_write_at(self) -> float | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key='last_write_at'").fetchone()
        return float(row[0]) if row else None

    def should_restore(self, window_s: int, now: float | None = None) -> bool:
        last = self.last_write_at()
        return last is not None and ((now or time.time()) - last) <= window_s

    def wipe(self) -> None:
        with self.conn:
            for table in WIPE_TABLES:
                self.conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
            self.conn.execute("DELETE FROM meta WHERE key='last_write_at'")

    def load_all(self) -> dict[str, list[Any]]:
        cur = self.conn.execute
        return {
            "contexts": cur("SELECT scope, context_id, version, payload_json, stored_at FROM contexts").fetchall(),
            "conversations": [json.loads(r[0]) for r in cur("SELECT state_json FROM conversations")],
            "suppressions": [json.loads(r[0]) for r in cur("SELECT entry_json FROM suppressions")],
            "merchant_flags": [json.loads(r[0]) for r in cur("SELECT flags_json FROM merchant_flags")],
            "compose_cache": cur("SELECT input_hash, output_json FROM compose_cache").fetchall(),
        }

    # --- writes (each commits and stamps last_write_at) ----------------------------------------
    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def _write(self, sql: str, params: tuple[Any, ...]) -> None:
        with self.conn:
            self.conn.execute(sql, params)
            self._set_meta("last_write_at", repr(time.time()))

    def put_context(self, scope: str, context_id: str, version: int, payload: dict[str, Any], stored_at: str) -> None:
        self._write(
            "INSERT INTO contexts(scope, context_id, version, payload_json, stored_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(scope, context_id) DO UPDATE SET version=excluded.version, "
            "payload_json=excluded.payload_json, stored_at=excluded.stored_at",
            (scope, context_id, version, json.dumps(payload, ensure_ascii=False), stored_at),
        )

    def put_conversation(self, conversation_id: str, merchant_id: str | None, state: dict[str, Any]) -> None:
        self._write(
            "INSERT INTO conversations(conversation_id, merchant_id, state_json, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(conversation_id) DO UPDATE SET state_json=excluded.state_json, "
            "updated_at=excluded.updated_at",
            (conversation_id, merchant_id, json.dumps(state, ensure_ascii=False), time.time()),
        )

    def put_suppression(self, key: str, merchant_id: str, entry: dict[str, Any]) -> None:
        self._write(
            "INSERT OR REPLACE INTO suppressions(suppression_key, merchant_id, entry_json) VALUES(?,?,?)",
            (key, merchant_id, json.dumps(entry, ensure_ascii=False)),
        )

    def put_flags(self, merchant_id: str, flags: dict[str, Any]) -> None:
        self._write(
            "INSERT OR REPLACE INTO merchant_flags(merchant_id, flags_json, updated_at) VALUES(?,?,?)",
            (merchant_id, json.dumps(flags, ensure_ascii=False), time.time()),
        )

    def put_cache(self, input_hash: str, output: dict[str, Any], prompt_version: str) -> None:
        self._write(
            "INSERT OR REPLACE INTO compose_cache(input_hash, output_json, prompt_version, created_at) VALUES(?,?,?,?)",
            (input_hash, json.dumps(output, ensure_ascii=False), prompt_version, time.time()),
        )

    def audit(self, endpoint: str, trigger_id: str | None, conversation_id: str | None, record: dict[str, Any]) -> None:
        self._write(
            "INSERT INTO audit_log(ts, endpoint, trigger_id, conversation_id, record_json) VALUES(?,?,?,?,?)",
            (time.time(), endpoint, trigger_id, conversation_id, json.dumps(record, ensure_ascii=False, default=str)),
        )

    def close(self) -> None:
        self.conn.close()
