"""Tick planner: resolve → guards → rank → cap → compose under a deadline → commit (TRD §4.4)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from vera.api.schemas import TickAction, TickRequest
from vera.compose.models import ComposedMessage, Skip
from vera.domain.ids import conversation_id, text_hash, utc_now_iso
from vera.observability.log import log_event, log_exception
from vera.store.state import Conversation, Store, Turn

MAX_ACTIONS = 20
UNANSWERED_LIMIT = 3

# compose(trigger_id, deadline_monotonic) -> message or skip; the fallback(trigger_id) is synchronous.
ComposeFn = Callable[[str, float], Awaitable[ComposedMessage | Skip]]
FallbackFn = Callable[[str], ComposedMessage | Skip]


def _guard(store: Store, trigger_id: str, trigger: dict[str, Any]) -> str | None:
    merchant_id = trigger.get("merchant_id")
    merchant = store.get("merchant", merchant_id)
    if merchant is None:
        return "missing_merchant"
    if store.get("category", merchant.get("category_slug")) is None:
        return "missing_category"
    key = trigger.get("suppression_key")
    if key and store.is_suppressed(key):
        return "suppressed"
    flags = store.flags.get(merchant_id or "")
    if flags and flags.opted_out:
        return "opted_out"
    if flags and flags.unanswered_proactive >= UNANSWERED_LIMIT:
        return "unanswered_3"
    return None


def _rank_key(item: tuple[int, str, dict[str, Any]]) -> tuple[int, str, int]:
    order, _, trigger = item
    raw = trigger.get("urgency")
    urgency = raw if isinstance(raw, int) else 1
    return (-urgency, str(trigger.get("expires_at") or "9999"), order)


def select_candidates(store: Store, request: TickRequest) -> list[tuple[str, dict[str, Any]]]:
    seen: set[str] = set()
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for order, trigger_id in enumerate(request.available_triggers):
        if trigger_id in seen:
            continue
        seen.add(trigger_id)
        trigger = store.get("trigger", trigger_id)
        if trigger is None:
            log_event("tick.skip", trigger_id=trigger_id, reason="unknown_trigger")
            continue
        reason = _guard(store, trigger_id, trigger)
        if reason:
            log_event("tick.skip", trigger_id=trigger_id, reason=reason)
            continue
        candidates.append((order, trigger_id, trigger))
    candidates.sort(key=_rank_key)
    return [(tid, trg) for _, tid, trg in candidates]


async def _compose_all(
    trigger_ids: list[str], compose: ComposeFn, fallback: FallbackFn, deadline: float
) -> dict[str, ComposedMessage | Skip]:
    tasks = {tid: asyncio.ensure_future(compose(tid, deadline)) for tid in trigger_ids}
    if tasks:
        await asyncio.wait(tasks.values(), timeout=max(0.0, deadline - time.monotonic()))
    results: dict[str, ComposedMessage | Skip] = {}
    for tid, task in tasks.items():
        if task.done() and not task.cancelled() and task.exception() is None:
            results[tid] = task.result()
            continue
        if not task.done():
            task.cancel()
            log_event("compose.deadline", trigger_id=tid)
        elif task.exception() is not None:
            log_event("compose.error", trigger_id=tid, error=repr(task.exception()))
        try:
            results[tid] = fallback(tid)
        except Exception:  # noqa: BLE001 - a broken fallback must not sink the whole tick
            log_exception("compose.fallback_error", trigger_id=tid)
            results[tid] = Skip(reason="fallback_error")
    return results


def _commit(
    store: Store, request: TickRequest, trigger_id: str, trigger: dict[str, Any], msg: ComposedMessage
) -> TickAction:
    merchant_id = trigger["merchant_id"]
    conv_id = conversation_id(
        merchant_id, msg.customer_id, msg.kind, trigger_id, store.version("trigger", trigger_id), request.now
    )
    base, n = conv_id, 2
    while conv_id in store.conversations:
        conv_id, n = f"{base}_{n}", n + 1
    action = TickAction(
        conversation_id=conv_id,
        merchant_id=merchant_id,
        customer_id=msg.customer_id,
        send_as=msg.send_as,
        trigger_id=trigger_id,
        template_name=msg.template_name,
        template_params=msg.template_params,
        body=msg.body,
        cta=msg.cta,
        suppression_key=msg.suppression_key,
        rationale=msg.rationale,
    )
    now = utc_now_iso()
    store.save_conversation(
        Conversation(
            conversation_id=conv_id,
            merchant_id=merchant_id,
            customer_id=msg.customer_id,
            trigger_id=trigger_id,
            kind=msg.kind,
            family=msg.family,
            send_as=msg.send_as,
            status="awaiting_reply",
            turns=[Turn(turn_number=1, role="vera", body=msg.body, ts=request.now or now)],
            promised_deliverable=msg.promised_deliverable,
            last_proposal=msg.template_params[2] if len(msg.template_params) > 2 else None,
        )
    )
    store.record_suppression(
        {
            "suppression_key": msg.suppression_key,
            "merchant_id": merchant_id,
            "customer_id": msg.customer_id,
            "trigger_id": trigger_id,
            "conversation_id": conv_id,
            "sent_at": now,
        }
    )
    flags = store.merchant_flags(merchant_id)
    flags.sent_body_hashes.append(text_hash(msg.body))
    if msg.send_as == "vera":
        flags.unanswered_proactive += 1
    store.save_flags(flags)
    store.audit(
        "tick",
        {
            "trigger_id": trigger_id,
            "conversation_id": conv_id,
            "path": msg.path,
            "input_hash": msg.input_hash,
            "body": msg.body,
        },
    )
    return action


async def plan_tick(
    store: Store, request: TickRequest, compose: ComposeFn, fallback: FallbackFn, deadline_s: float
) -> list[TickAction]:
    deadline = time.monotonic() + deadline_s
    candidates, claimed = [], set()
    for trigger_id, trigger in select_candidates(store, request):
        if trigger.get("scope", "merchant") != "customer":  # don't spend LLM calls on capped triggers
            if trigger["merchant_id"] in claimed:
                log_event("tick.defer", trigger_id=trigger_id, reason="merchant_cap")
                continue
            claimed.add(trigger["merchant_id"])
        candidates.append((trigger_id, trigger))
    candidates = candidates[: MAX_ACTIONS * 2]  # headroom for skips after composing
    results = await _compose_all([tid for tid, _ in candidates], compose, fallback, deadline)
    actions: list[TickAction] = []
    merchants_contacted: set[str] = set()
    customers_contacted: set[str] = set()
    for trigger_id, trigger in candidates:
        if len(actions) >= MAX_ACTIONS:
            break
        msg = results.get(trigger_id)
        if not isinstance(msg, ComposedMessage):
            log_event("tick.skip", trigger_id=trigger_id, reason=msg.reason if msg else "no_result")
            continue
        merchant_id = trigger["merchant_id"]
        if msg.send_as == "vera" and merchant_id in merchants_contacted:
            log_event("tick.defer", trigger_id=trigger_id, reason="merchant_cap")
            continue
        if msg.customer_id and msg.customer_id in customers_contacted:
            log_event("tick.defer", trigger_id=trigger_id, reason="customer_cap")
            continue
        if store.is_suppressed(msg.suppression_key):
            log_event("tick.skip", trigger_id=trigger_id, reason="suppressed")
            continue
        actions.append(_commit(store, request, trigger_id, trigger, msg))
        if msg.send_as == "vera":
            merchants_contacted.add(merchant_id)
        if msg.customer_id:
            customers_contacted.add(msg.customer_id)
    log_event("tick.done", listed=len(request.available_triggers), candidates=len(candidates), actions=len(actions))
    return actions
