"""Independent grounding audit over every composable trigger (docs/10 §6): zero findings expected."""

from __future__ import annotations

from eval.grounding import audit
from tests.golden.test_golden import COMPOSER, STORE
from vera.compose.models import Skip


def test_every_composed_message_is_grounded() -> None:
    failures = []
    for trigger_id, trigger in STORE.triggers():
        msg = COMPOSER.fallback(trigger_id)
        if isinstance(msg, Skip):
            continue
        merchant = STORE.get("merchant", trigger.get("merchant_id")) or {}
        contexts = [
            trigger,
            merchant,
            STORE.get("category", merchant.get("category_slug")) or {},
            STORE.get("customer", trigger.get("customer_id")) or {},
        ]
        result = audit(msg.body, contexts)
        if not result.clean:
            failures.append((trigger_id, [(f.kind, f.token) for f in result.findings], msg.body))
    assert not failures, failures[:5]


def test_auditor_catches_fabrications() -> None:
    merchant = STORE.get("merchant", "m_001_drmeera_dentist_delhi") or {}
    fake = "Dr. Meera, a new Lancet study shows 47% of Dr. Kapoor's patients switched on 12 Oct; see www.x.com."
    kinds = {f.kind for f in audit(fake, [merchant]).findings}
    assert {"number", "date", "person", "source", "url"} <= kinds
