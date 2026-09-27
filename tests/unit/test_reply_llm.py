"""Reply rewrite layer with a fake gateway: accepted, rejected on fabrication, skipped for fixed wording."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.golden.test_golden import _store
from vera.api.schemas import ReplyRequest
from vera.llm.gateway import LLMUnavailable
from vera.reply.engine import ReplyEngine

MEERA = "m_001_drmeera_dentist_delhi"


class Fake:
    model = "fake"

    def __init__(self, out: Any) -> None:
        self.out, self.calls = out, 0

    async def complete_json(self, system: str, user: str, schema: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.calls += 1
        if isinstance(self.out, Exception):
            raise self.out
        return {"body": self.out}


def _reply(engine: ReplyEngine, message: str, conv: str = "conv_x") -> dict[str, Any]:
    req = ReplyRequest(conversation_id=conv, merchant_id=MEERA, message=message, turn_number=2)
    return asyncio.run(engine.handle(req))


QUESTION = "What's my competitor's rating these days?"


def test_grounded_rewrite_is_used() -> None:
    body = "I don't have your competitor's rating. What I can see: 2,410 profile views and 18 calls in 30 days. Want me to go ahead with what I suggested above?"
    out = _reply(ReplyEngine(_store(), Fake(body)), QUESTION)
    assert out["action"] == "send" and out["body"] == body and "reply model" in out["rationale"]


def test_fabricated_rewrite_is_rejected() -> None:
    out = _reply(
        ReplyEngine(_store(), Fake("Your competitor has 4.9 stars and 312 reviews. Want to fight back?")), QUESTION
    )
    assert out["action"] == "send" and "312" not in out["body"] and "reply model" not in out["rationale"]


def test_unavailable_llm_keeps_deterministic_reply() -> None:
    out = _reply(ReplyEngine(_store(), Fake(LLMUnavailable("timeout"))), QUESTION)
    assert out["action"] == "send" and "reply model" not in out["rationale"]


def test_fixed_wording_intents_skip_the_llm() -> None:
    fake = Fake("anything")
    engine = ReplyEngine(_store(), fake)
    _reply(engine, "Thank you for contacting us! Our team will respond shortly.")
    _reply(engine, "Stop messaging me.", conv="conv_y")
    assert fake.calls == 0
