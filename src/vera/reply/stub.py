"""M2 placeholder reply handler: records the turn and backs off. Replaced in M6."""

from __future__ import annotations

from typing import Any

from vera.api.schemas import ReplyRequest
from vera.store.state import Conversation, Store, Turn


class StubReplyHandler:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def handle(self, request: ReplyRequest) -> dict[str, Any]:
        conv = self.store.conversations.get(request.conversation_id) or Conversation(
            conversation_id=request.conversation_id,
            merchant_id=request.merchant_id,
            customer_id=request.customer_id,
            created_from="lazy",
        )
        conv.turns.append(
            Turn(turn_number=request.turn_number, role=request.from_role, body=request.message, ts=request.received_at)
        )
        self.store.save_conversation(conv)
        return {"action": "wait", "wait_seconds": 3600, "rationale": "reply engine not built yet (M2 stub)"}
