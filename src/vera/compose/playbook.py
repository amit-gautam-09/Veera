"""Decision step: kind → family, signal, CTA, levers, recipient, and grounded fallback wording (07)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from vera.api.schemas import Cta, SendAs
from vera.compose.facts import Ctx, Fact
from vera.compose.models import Skip
from vera.domain.language import Language

TEMPLATES = {
    "knowledge": "vera_knowledge_v1",
    "performance": "vera_performance_v1",
    "account": "vera_account_v1",
    "moment": "vera_moment_v1",
    "reputation": "vera_reputation_v1",
    "conversation": "vera_conversation_v1",
    "customer_reminder": "merchant_reminder_v1",
    "customer_winback": "merchant_winback_v1",
    "customer_followup": "merchant_followup_v1",
    "approval": "vera_customer_approval_v1",
    "generic": "vera_generic_v1",
}

KIND_FAMILY = {
    "research_digest": "knowledge",
    "regulation_change": "knowledge",
    "cde_opportunity": "knowledge",
    "supply_alert": "knowledge",
    "category_seasonal": "knowledge",
    "perf_dip": "performance",
    "perf_spike": "performance",
    "seasonal_perf_dip": "performance",
    "milestone_reached": "performance",
    "renewal_due": "account",
    "winback_eligible": "account",
    "dormant_with_vera": "account",
    "gbp_unverified": "account",
    "festival_upcoming": "moment",
    "ipl_match_today": "moment",
    "competitor_opened": "moment",
    "review_theme_emerged": "reputation",
    "curious_ask_due": "conversation",
    "active_planning_intent": "conversation",
    "recall_due": "customer_reminder",
    "appointment_tomorrow": "customer_reminder",
    "chronic_refill_due": "customer_reminder",
    "customer_lapsed_soft": "customer_winback",
    "customer_lapsed_hard": "customer_winback",
    "trial_followup": "customer_followup",
    "wedding_package_followup": "customer_followup",
}
CUSTOMER_FAMILIES = {"customer_reminder", "customer_winback", "customer_followup"}


@dataclass
class Plan:
    family: str
    cta: Cta
    lines: list[str]
    ask: str
    facts: list[Fact]
    levers: list[str]
    primary: str
    send_as: SendAs = "vera"
    customer_id: str | None = None
    language: Language = "english"
    opener: str = ""
    notes: list[str] = field(default_factory=list)
    deliverable: str | None = None

    @property
    def template_name(self) -> str:
        return TEMPLATES[self.family]

    @property
    def middle(self) -> str:
        return " ".join(line.strip() for line in self.lines if line and line.strip())


Handler = Callable[[Ctx], "Plan | Skip"]
HANDLERS: dict[str, Handler] = {}


def handles(*kinds: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        for kind in kinds:
            HANDLERS[kind] = fn
        return fn

    return register


def F(label: str, render: object, source: str = "trigger", visible: bool = False) -> Fact:  # noqa: N802
    return Fact(label=label, render=str(render), source=source, visible=visible)


def decide(ctx: Ctx) -> Plan | Skip:
    """Run the handler for the trigger kind (or the generic handler) and fill defaults."""
    from vera.compose import customer_kinds, merchant_kinds  # noqa: F401 - registers handlers

    handler = HANDLERS.get(ctx.kind) or HANDLERS["__generic__"]
    plan = handler(ctx)
    if isinstance(plan, Skip):
        return plan
    if not plan.opener:
        plan.opener = ctx.opener()
    if plan.send_as == "vera":
        plan.language = ctx.lang
    return plan
