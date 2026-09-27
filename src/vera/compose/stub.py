"""M2 placeholder composer: schema-valid, content-free. Replaced by the real pipeline in M3."""

from __future__ import annotations

from vera.compose.models import ComposedMessage, Skip
from vera.store.state import Store


class StubComposer:
    def __init__(self, store: Store) -> None:
        self.store = store

    def fallback(self, trigger_id: str) -> ComposedMessage | Skip:
        trigger = self.store.get("trigger", trigger_id)
        if trigger is None:
            return Skip(reason="unknown_trigger")
        merchant = self.store.get("merchant", trigger.get("merchant_id")) or {}
        name = (merchant.get("identity") or {}).get("owner_first_name") or "there"
        kind = str(trigger.get("kind") or "update")
        opener, middle, ask = f"Hi {name},", f"a new {kind.replace('_', ' ')} update is ready.", "Want to see it?"
        return ComposedMessage(
            body=f"{opener} {middle} {ask}",
            cta="binary_yes_no",
            send_as="vera",
            customer_id=None,
            suppression_key=trigger.get("suppression_key") or f"{kind}:{trigger.get('merchant_id')}:-:{trigger_id}",
            rationale=f"Stub message for {kind}",
            template_name="vera_generic_v1",
            template_params=[opener, middle, ask],
            family="generic",
            kind=kind,
            path="stub",
        )

    def on_context(self, scope: str, context_id: str) -> None:
        return None

    async def compose(self, trigger_id: str, deadline: float) -> ComposedMessage | Skip:
        return self.fallback(trigger_id)
