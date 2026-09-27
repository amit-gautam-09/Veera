"""Optional deliverable: `respond(state, merchant_message)` for multi-turn handling (challenge brief §7.4).

`state` is a plain dict:
  {"conversation_id": str, "merchant": {...}, "category": {...}, "trigger": {...} | None,
   "customer": {...} | None, "turns": [{"role": "vera" | "merchant" | "customer", "body": str}, ...],
   "from_role": "merchant" | "customer"}
Returns the same shape as POST /v1/reply: {"action": "send"|"wait"|"end", ...}. Uses the live reply engine.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from vera.api.schemas import ReplyRequest  # noqa: E402
from vera.reply.engine import ReplyEngine  # noqa: E402
from vera.store.state import Conversation, Store, Turn  # noqa: E402


def respond(state: dict[str, Any], merchant_message: str) -> dict[str, Any]:
    store = Store()
    merchant, category = state.get("merchant") or {}, state.get("category") or {}
    trigger, customer = state.get("trigger"), state.get("customer")
    store.put_context("category", str(category.get("slug", "unknown")), 1, category)
    store.put_context("merchant", str(merchant.get("merchant_id", "unknown")), 1, merchant)
    if customer:
        store.put_context("customer", str(customer.get("customer_id")), 1, customer)
    if trigger:
        store.put_context("trigger", str(trigger.get("id")), 1, trigger)
    turns = [Turn(role=str(t.get("role")), body=str(t.get("body", ""))) for t in state.get("turns") or []]
    last_vera = next((t.body for t in reversed(turns) if t.role == "vera"), None)
    conv_id = str(state.get("conversation_id") or "conv_offline")
    store.save_conversation(
        Conversation(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id"),
            customer_id=(customer or {}).get("customer_id"),
            trigger_id=(trigger or {}).get("id"),
            kind=(trigger or {}).get("kind", "conversation"),
            status="awaiting_reply",
            turns=turns,
            send_as="merchant_on_behalf" if state.get("from_role") == "customer" else "vera",
            last_proposal=re.split(r"(?<=[.!?])\s+", last_vera.strip())[-1] if last_vera else None,
            created_from="tick" if trigger else "lazy",
        )
    )
    request = ReplyRequest(
        conversation_id=conv_id,
        merchant_id=merchant.get("merchant_id"),
        customer_id=(customer or {}).get("customer_id"),
        from_role=str(state.get("from_role") or "merchant"),
        message=merchant_message,
        turn_number=len(turns) + 1,
    )
    return asyncio.run(ReplyEngine(store).handle(request))
