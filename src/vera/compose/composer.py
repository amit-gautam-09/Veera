"""Compose pipeline: resolve → decide → fact sheet → LLM → validate → repair → assemble (06 §1, TRD §4.7–4.10)."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vera.compose.facts import Ctx, FactSheet, build_fact_sheet, humanize
from vera.compose.models import ComposedMessage, Skip
from vera.compose.playbook import Plan, decide
from vera.compose.prompts import COMPOSER_SCHEMA, COMPOSER_SYSTEM, COMPOSER_VERSION, build_user_prompt
from vera.compose.validator import Check, validate
from vera.domain.ids import canonical_json, sha256
from vera.domain.salutation import owner_name
from vera.llm.gateway import LLMGateway, LLMUnavailable
from vera.observability.log import log_event, log_exception
from vera.store.state import Store

PROMPT_VERSION = COMPOSER_VERSION
PRECOMPUTE_BUDGET_S = 25.0
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# violations a sentence drop cannot fix (whole-message properties)
GLOBAL_CODES = {"V12", "V13", "V14", "V15", "V16"}


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
    return Prepared(ctx, plan, build_fact_sheet(ctx, plan.facts))


def input_hash(prep: Prepared, model: str) -> str:
    """Content-addressed: identical contexts give the same key across restarts and versions (ADR-004)."""
    ctx = prep.ctx
    return sha256(
        canonical_json(
            {
                "prompt": PROMPT_VERSION,
                "model": model,
                "trigger": ctx.trigger,
                "merchant": ctx.merchant,
                "category": ctx.category,
                "customer": ctx.customer,
            }
        )
    )


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
    extra = [n for n in plan.notes if "reinterpreted" in n or "advise against" in n or "no lapse" in n]
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


def drop_to_pass(store: Store, prep: Prepared, opener: str, middle: str, ask: str, check: Check) -> str | None:
    """Remove the fewest middle sentences (one, then two) so the message passes; None if impossible."""
    if any(v.split(":", 1)[0] in GLOBAL_CODES for v in check.violations):
        return None
    sentences = [s for s in _SENTENCE.split(middle.strip()) if s]
    for drop in (1, 2):
        if len(sentences) <= drop:
            break
        for i in range(len(sentences) - drop + 1):
            candidate = " ".join(sentences[:i] + sentences[i + drop :])
            if check_parts(store, prep, opener, candidate, ask).ok:
                return candidate
    return None


STARTERS = {
    "here's", "here", "your", "you're", "you", "a", "one", "the", "that", "quick", "since", "it's", "is", "ek",
    "aapka", "aapke", "aapki", "aap", "pichhle", "kal", "plan", "urgent", "seasonal", "summer", "yeh", "abhi",
    "we", "our", "thanks", "i'll", "calls", "views", "heads-up", "aaj", "agla", "wahi",
}  # fmt: skip


def smooth(opener: str, text: str) -> str:
    """After 'Hi Priya,' continue in lower case when the next word is a common starter."""
    first = text.split(" ", 1)[0].strip(".,:;").lower() if text else ""
    if opener.rstrip().endswith(",") and first in STARTERS and text[:1].isupper():
        return text[0].lower() + text[1:]
    return text


def assemble(prep: Prepared, opener: str, middle: str, ask: str, path: str) -> ComposedMessage:
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
        rationale=rationale(prep),
        template_name=prep.plan.template_name,
        template_params=[opener.strip(), " ".join(middle.split()), ask.strip()],
        family=prep.plan.family,
        kind=prep.ctx.kind,
        path=path,  # type: ignore[arg-type]
        prompt_version=PROMPT_VERSION,
        promised_deliverable=prep.plan.deliverable,
    )


def fallback_message(store: Store, prep: Prepared) -> ComposedMessage | Skip:
    """Deterministic message from the plan's own grounded wording; sentences dropped if a check fails."""
    plan = prep.plan
    opener, middle, ask = plan.opener, plan.middle, plan.ask
    check = check_parts(store, prep, opener, middle, ask)
    if not check.ok:
        log_event("fallback.violations", trigger_id=prep.ctx.trigger_id, violations=check.violations)
        repaired = drop_to_pass(store, prep, opener, middle, ask, check)
        if not repaired:
            return Skip(reason=f"validation:{','.join(check.violations)}")
        middle = repaired
    return assemble(prep, opener, middle, ask, "fallback")


def prior_bodies(store: Store, merchant_id: str | None) -> list[str]:
    return [
        c.turns[0].body
        for c in store.conversations.values()
        if c.merchant_id == merchant_id and c.turns and c.created_from == "tick"
    ]


def user_prompt(store: Store, prep: Prepared, violations: list[str] | None = None) -> str:
    plan, ctx = prep.plan, prep.ctx
    audience = (
        "the merchant's own customer (message sent from the business's number)"
        if plan.send_as == "merchant_on_behalf"
        else "the merchant (owner), from Vera"
    )
    return build_user_prompt(
        category=ctx.category,
        audience=audience,
        language=plan.language,
        family=plan.family,
        opener=plan.opener,
        primary=plan.primary,
        levers=plan.levers,
        cta=plan.cta,
        notes=plan.notes,
        facts_block=prep.sheet.render(),
        reference=f"{plan.opener} {plan.middle} {plan.ask}".strip(),
        taboos=prep.sheet.taboos,
        prior_bodies=prior_bodies(store, ctx.trigger.get("merchant_id")),
        violations=violations,
    )


class Composer:
    """Tick-facing composer: cache → single-flight LLM task → validate/repair → deterministic fallback."""

    def __init__(
        self, store: Store, gateway: LLMGateway | None = None, repair_min_s: float = 3.0, llm_timeout_s: float = 6.0
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.repair_min_s = repair_min_s
        self.llm_timeout_s = llm_timeout_s
        self._inflight: dict[str, asyncio.Task[ComposedMessage | None]] = {}

    @property
    def model(self) -> str:
        return self.gateway.model if self.gateway else "fallback"

    # --- public interface (app.Composer protocol) ---------------------------------------------------
    def fallback(self, trigger_id: str) -> ComposedMessage | Skip:
        prep = prepare(self.store, trigger_id)
        return prep if isinstance(prep, Skip) else fallback_message(self.store, prep)

    async def compose(self, trigger_id: str, deadline: float) -> ComposedMessage | Skip:
        prep = prepare(self.store, trigger_id)
        if isinstance(prep, Skip):
            return prep
        key = input_hash(prep, self.model)
        cached = self._from_cache(prep, key)
        if cached is not None:
            return cached
        if self.gateway is not None:
            task = self._task(prep, key, deadline)
            done, _ = await asyncio.wait({task}, timeout=max(0.0, deadline - time.monotonic()))
            if task in done and not task.cancelled() and task.exception() is None and task.result() is not None:
                result = task.result()
                assert result is not None
                if check_parts(self.store, prep, *result.template_params).ok:  # re-check repetition at send time
                    return result
        return fallback_message(self.store, prep)

    def on_context(self, scope: str, context_id: str) -> None:
        """Precompute on trigger push; re-precompute unsent triggers when a context they depend on changes."""
        if self.gateway is None:
            return
        for trigger_id in self._dependents(scope, context_id):
            prep = prepare(self.store, trigger_id)
            if isinstance(prep, Skip):
                continue
            key = input_hash(prep, self.model)
            if self._from_cache(prep, key) is None:
                self._task(prep, key, time.monotonic() + PRECOMPUTE_BUDGET_S)

    # --- internals ---------------------------------------------------------------------------------------
    def _dependents(self, scope: str, context_id: str) -> list[str]:
        if scope == "trigger":
            return [context_id]
        out = []
        for trigger_id, trigger in self.store.triggers():
            if trigger.get("suppression_key") and self.store.is_suppressed(str(trigger["suppression_key"])):
                continue
            merchant = self.store.get("merchant", trigger.get("merchant_id")) or {}
            if (
                (scope == "merchant" and trigger.get("merchant_id") == context_id)
                or (scope == "customer" and trigger.get("customer_id") == context_id)
                or (scope == "category" and merchant.get("category_slug") == context_id)
            ):
                out.append(trigger_id)
        return out

    def _from_cache(self, prep: Prepared, key: str) -> ComposedMessage | None:
        raw = self.store.cache_get(key)
        if raw is None:
            return None
        msg = ComposedMessage.model_validate(raw)
        msg.path = "cache"
        return msg if check_parts(self.store, prep, *msg.template_params).ok else None

    def _task(self, prep: Prepared, key: str, deadline: float) -> asyncio.Task[ComposedMessage | None]:
        task = self._inflight.get(key)
        if task is None or (task.done() and (task.cancelled() or task.exception() or task.result() is None)):
            task = asyncio.get_running_loop().create_task(self._llm_compose(prep, key, deadline))
            self._inflight[key] = task
            task.add_done_callback(self._forget(key))
        return task

    def _forget(self, key: str) -> Callable[[asyncio.Task[ComposedMessage | None]], None]:
        def callback(_task: asyncio.Task[ComposedMessage | None]) -> None:
            self._inflight.pop(key, None)

        return callback

    async def _call(self, prep: Prepared, deadline: float, violations: list[str] | None = None) -> dict[str, Any]:
        assert self.gateway is not None
        timeout = min(self.llm_timeout_s, deadline - time.monotonic())
        return await self.gateway.complete_json(
            COMPOSER_SYSTEM, user_prompt(self.store, prep, violations), COMPOSER_SCHEMA, timeout
        )

    async def _llm_compose(self, prep: Prepared, key: str, deadline: float) -> ComposedMessage | None:
        trigger_id = prep.ctx.trigger_id
        try:
            data = await self._call(prep, deadline)
            parts = self._parts(prep, data)
            check = check_parts(self.store, prep, *parts)
            path = "llm"
            if not check.ok:
                repaired_middle = drop_to_pass(self.store, prep, parts[0], parts[1], parts[2], check)
                if repaired_middle:
                    parts, path = (parts[0], repaired_middle, parts[2]), "repaired"
                elif deadline - time.monotonic() >= self.repair_min_s:
                    data = await self._call(prep, deadline, check.violations)
                    parts = self._parts(prep, data)
                    if not check_parts(self.store, prep, *parts).ok:
                        log_event("compose.llm_rejected", trigger_id=trigger_id, violations=check.violations)
                        return None
                    path = "repaired"
                else:
                    log_event("compose.llm_rejected", trigger_id=trigger_id, violations=check.violations)
                    return None
            msg = assemble(prep, *parts, path)
            msg.input_hash = key
            self.store.cache_put(key, msg.model_dump(), PROMPT_VERSION)
            log_event("compose.llm_ok", trigger_id=trigger_id, path=path)
            return msg
        except LLMUnavailable as exc:
            log_event("compose.llm_unavailable", trigger_id=trigger_id, reason=str(exc))
            return None
        except Exception:  # noqa: BLE001 - background task: log, fall back
            log_exception("compose.llm_error", trigger_id=trigger_id)
            return None

    @staticmethod
    def _parts(prep: Prepared, data: dict[str, Any]) -> tuple[str, str, str]:
        opener = " ".join(str(data.get("opener") or prep.plan.opener).split())
        middle = " ".join(str(data.get("middle") or "").split())
        ask = " ".join(str(data.get("ask") or "").split())
        return opener, middle, ask
