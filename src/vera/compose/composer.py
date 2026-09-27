"""Compose pipeline: resolve → decide → fact sheet → (LLM, M4) → validate → assemble (06 §1)."""

from __future__ import annotations

from dataclasses import dataclass

from vera.compose.facts import Ctx, FactSheet, build_fact_sheet, humanize
from vera.compose.models import ComposedMessage, Skip
from vera.compose.playbook import Plan, decide
from vera.compose.validator import Check, offending_sentences, validate
from vera.domain.salutation import owner_name
from vera.observability.log import log_event
from vera.store.state import Store

PROMPT_VERSION = "composer_v1"


@dataclass
class Prepared:
    ctx: Ctx
    plan: Plan
    sheet: FactSheet


def resolve(store: Store, trigger_id: str) -> Ctx | Skip:
    trigger = store.get("trigger", trigger_id)
    if trigger is None:
        return Skip(reason="unknown_trigger")
    merchant = store.get("merchant", trigger.get("merchant_id"))
    if merchant is None:
        return Skip(reason="missing_merchant")
    category = store.get("category", merchant.get("category_slug"))
    if category is None:
        return Skip(reason="missing_category")
    customer = store.get("customer", trigger.get("customer_id")) if trigger.get("customer_id") else None
    return Ctx(trigger_id=trigger_id, trigger=trigger, merchant=merchant, category=category, customer=customer)


def prepare(store: Store, trigger_id: str) -> Prepared | Skip:
    ctx = resolve(store, trigger_id)
    if isinstance(ctx, Skip):
        return ctx
    plan = decide(ctx)
    if isinstance(plan, Skip):
        return plan
    sheet = build_fact_sheet(ctx, plan.facts)
    return Prepared(ctx, plan, sheet)


def salutation_name(prep: Prepared) -> str | None:
    if prep.plan.send_as == "merchant_on_behalf":
        name = prep.ctx.cust_name
        return name.addressee if name else None
    return owner_name(prep.ctx.merchant)


def suppression_key(ctx: Ctx) -> str:
    key = ctx.trigger.get("suppression_key")
    if key:
        return str(key)
    return f"{ctx.kind}:{ctx.trigger.get('merchant_id')}:{ctx.trigger.get('customer_id') or '-'}:{ctx.trigger_id}"


def rationale(prep: Prepared) -> str:
    ctx, plan = prep.ctx, prep.plan
    payload = "placeholder payload" if ctx.placeholder else "payload"
    extra = [n for n in plan.notes if "reinterpreted" in n or "merchant-facing" in n or "no lapse" in n]
    parts = [
        f"Why now: {humanize(ctx.kind)} ({payload}).",
        f"Primary signal: {plan.primary}.",
        f"Levers: {', '.join(plan.levers)}.",
        f"CTA {plan.cta}; language {plan.language}.",
    ]
    if plan.family == "approval":
        parts.append("Customer not messaged directly (consent/context), so asking the merchant first.")
    parts += [e.rstrip(".") + "." for e in extra[:1]]
    return " ".join(parts)


def check_parts(store: Store, prep: Prepared, opener: str, middle: str, ask: str) -> Check:
    flags = store.flags.get(prep.ctx.trigger.get("merchant_id") or "")
    return validate(
        opener,
        middle,
        ask,
        prep.sheet,
        language=prep.plan.language,
        salutation_name=salutation_name(prep),
        prior_body_hashes=flags.sent_body_hashes if flags else None,
    )


def drop_offending(middle: str, check: Check) -> str:
    for sentence in offending_sentences(middle, check):
        middle = middle.replace(sentence, "").strip()
    return " ".join(middle.split())


STARTERS = {
    "here's",
    "here",
    "your",
    "you're",
    "you",
    "a",
    "one",
    "the",
    "that",
    "quick",
    "since",
    "it's",
    "is",
    "ek",
    "aapka",
    "aapke",
    "aapki",
    "aap",
    "pichhle",
    "kal",
    "plan",
    "urgent",
    "seasonal",
    "summer",
    "yeh",
    "abhi",
    "we",
    "our",
    "thanks",
    "i'll",
    "calls",
    "views",
    "heads-up",
    "aaj",
    "agla",
    "wahi",
}


def smooth(opener: str, text: str) -> str:
    """After 'Hi Priya,' continue in lower case when the next word is a common starter."""
    first = text.split(" ", 1)[0].strip(".,:;").lower() if text else ""
    if opener.rstrip().endswith(",") and first in STARTERS and text[:1].isupper():
        return text[0].lower() + text[1:]
    return text


def assemble(prep: Prepared, opener: str, middle: str, ask: str, path: str, why: str | None = None) -> ComposedMessage:
    if middle:
        middle = smooth(opener, middle)
    else:
        ask = smooth(opener, ask)
    body = " ".join(f"{opener} {middle} {ask}".split())
    return ComposedMessage(
        body=body,
        cta=prep.plan.cta,
        send_as=prep.plan.send_as,
        customer_id=prep.plan.customer_id,
        suppression_key=suppression_key(prep.ctx),
        rationale=why or rationale(prep),
        template_name=prep.plan.template_name,
        template_params=[opener.strip(), " ".join(middle.split()), ask.strip()],
        family=prep.plan.family,
        kind=prep.ctx.kind,
        path=path,  # type: ignore[arg-type]
        prompt_version=PROMPT_VERSION,
        promised_deliverable=prep.plan.deliverable,
    )


def fallback_message(store: Store, prep: Prepared) -> ComposedMessage | Skip:
    """Deterministic message from the plan's own grounded wording; dropped sentences if a check fails."""
    plan = prep.plan
    opener, middle, ask = plan.opener, plan.middle, plan.ask
    check = check_parts(store, prep, opener, middle, ask)
    if not check.ok:
        log_event("fallback.violations", trigger_id=prep.ctx.trigger_id, violations=check.violations)
        middle = drop_offending(middle, check)
        check = check_parts(store, prep, opener, middle, ask)
        if not check.ok or not middle:
            return Skip(reason=f"validation:{','.join(check.violations) or 'empty'}")
    return assemble(prep, opener, middle, ask, "fallback")


class Composer:
    """Tick-facing composer. M3: deterministic fallback only; M4 adds the LLM path and precompute."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def fallback(self, trigger_id: str) -> ComposedMessage | Skip:
        prep = prepare(self.store, trigger_id)
        return prep if isinstance(prep, Skip) else fallback_message(self.store, prep)

    async def compose(self, trigger_id: str, deadline: float) -> ComposedMessage | Skip:
        return self.fallback(trigger_id)

    def on_context(self, scope: str, context_id: str) -> None:
        return None
