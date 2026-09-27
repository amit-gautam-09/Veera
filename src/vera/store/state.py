"""In-memory state with write-through to SQLite (docs/02-TRD.md §4.2–4.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from vera.domain.ids import utc_now_iso
from vera.store.sqlite import Database

SCOPES = ("category", "merchant", "customer", "trigger")
ConversationStatus = Literal["open", "awaiting_reply", "action_mode", "waiting", "ended"]


@dataclass
class StoredContext:
    version: int
    payload: dict[str, Any]
    stored_at: str


class Turn(BaseModel):
    turn_number: int | None = None
    role: str  # vera | merchant | customer
    body: str
    ts: str | None = None
    intent: str | None = None
    action: str | None = None
    request_digest: str | None = None
    response: dict[str, Any] | None = None


class Conversation(BaseModel):
    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    trigger_id: str | None = None
    kind: str | None = None
    family: str | None = None
    send_as: str = "vera"
    status: ConversationStatus = "open"
    turns: list[Turn] = Field(default_factory=list)
    promised_deliverable: str | None = None
    last_proposal: str | None = None
    soft_no_count: int = 0
    hostile_count: int = 0
    last_inbound_language: str | None = None
    created_from: Literal["tick", "lazy"] = "tick"
    created_at: str = Field(default_factory=utc_now_iso)


class MerchantFlags(BaseModel):
    merchant_id: str
    opted_out: bool = False
    opted_out_at: str | None = None
    auto_reply_counts: dict[str, int] = Field(default_factory=dict)
    unanswered_proactive: int = 0
    inbound_hashes: list[str] = Field(default_factory=list)  # recent inbound texts, for repeat detection
    sent_body_hashes: list[str] = Field(default_factory=list)


class PutResult(BaseModel):
    accepted: bool
    current_version: int | None = None
    stored_at: str | None = None


class Store:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db
        self.contexts: dict[tuple[str, str], StoredContext] = {}
        self.conversations: dict[str, Conversation] = {}
        self.suppressions: dict[str, dict[str, Any]] = {}
        self.flags: dict[str, MerchantFlags] = {}
        self.compose_cache: dict[str, dict[str, Any]] = {}

    # --- lifecycle ---------------------------------------------------------------------------
    def restore(self, window_s: int) -> bool:
        """Reload from SQLite if the last write is recent; otherwise wipe. Returns True if restored."""
        if self.db is None:
            return False
        if not self.db.should_restore(window_s):
            self.db.wipe()
            return False
        data = self.db.load_all()
        for scope, cid, version, payload_json, stored_at in data["contexts"]:
            self.contexts[(scope, cid)] = StoredContext(version, json.loads(payload_json), stored_at)
        for raw in data["conversations"]:
            conv = Conversation.model_validate(raw)
            self.conversations[conv.conversation_id] = conv
        for raw in data["suppressions"]:
            self.suppressions[raw["suppression_key"]] = raw
        for raw in data["merchant_flags"]:
            flags = MerchantFlags.model_validate(raw)
            self.flags[flags.merchant_id] = flags
        for input_hash, output_json in data["compose_cache"]:
            self.compose_cache[input_hash] = json.loads(output_json)
        return True

    def wipe(self) -> None:
        self.contexts.clear()
        self.conversations.clear()
        self.suppressions.clear()
        self.flags.clear()
        self.compose_cache.clear()
        if self.db is not None:
            self.db.wipe()

    # --- contexts ----------------------------------------------------------------------------
    def put_context(self, scope: str, context_id: str, version: int, payload: dict[str, Any]) -> PutResult:
        current = self.contexts.get((scope, context_id))
        if current is not None and current.version >= version:
            return PutResult(accepted=False, current_version=current.version)
        stored_at = utc_now_iso()
        if self.db is not None:  # persist first: a failed write leaves memory unchanged
            self.db.put_context(scope, context_id, version, payload, stored_at)
        self.contexts[(scope, context_id)] = StoredContext(version, payload, stored_at)
        return PutResult(accepted=True, stored_at=stored_at)

    def get(self, scope: str, context_id: str | None) -> dict[str, Any] | None:
        if not context_id:
            return None
        entry = self.contexts.get((scope, context_id))
        return entry.payload if entry else None

    def version(self, scope: str, context_id: str | None) -> int:
        entry = self.contexts.get((scope, context_id or ""))
        return entry.version if entry else 0

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(SCOPES, 0)
        for scope, _ in self.contexts:
            counts[scope] = counts.get(scope, 0) + 1
        return counts

    def triggers(self) -> list[tuple[str, dict[str, Any]]]:
        return [(cid, e.payload) for (scope, cid), e in self.contexts.items() if scope == "trigger"]

    # --- conversations, suppressions, flags ------------------------------------------------------
    def save_conversation(self, conv: Conversation) -> None:
        self.conversations[conv.conversation_id] = conv
        if self.db is not None:
            self.db.put_conversation(conv.conversation_id, conv.merchant_id, conv.model_dump())

    def merchant_flags(self, merchant_id: str) -> MerchantFlags:
        if merchant_id not in self.flags:
            self.flags[merchant_id] = MerchantFlags(merchant_id=merchant_id)
        return self.flags[merchant_id]

    def save_flags(self, flags: MerchantFlags) -> None:
        self.flags[flags.merchant_id] = flags
        if self.db is not None:
            self.db.put_flags(flags.merchant_id, flags.model_dump())

    def is_suppressed(self, key: str) -> bool:
        return key in self.suppressions

    def record_suppression(self, entry: dict[str, Any]) -> None:
        self.suppressions[entry["suppression_key"]] = entry
        if self.db is not None:
            self.db.put_suppression(entry["suppression_key"], entry["merchant_id"], entry)

    def cache_get(self, input_hash: str) -> dict[str, Any] | None:
        return self.compose_cache.get(input_hash)

    def cache_put(self, input_hash: str, output: dict[str, Any], prompt_version: str) -> None:
        self.compose_cache[input_hash] = output
        if self.db is not None:
            self.db.put_cache(input_hash, output, prompt_version)

    def audit(self, endpoint: str, record: dict[str, Any]) -> None:
        if self.db is not None:
            self.db.audit(endpoint, record.get("trigger_id"), record.get("conversation_id"), record)
