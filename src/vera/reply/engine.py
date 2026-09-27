"""Reply engine: classify → policy (state machine) → compose → validate → record (09, TRD §4.11)."""

from __future__ import annotations

import re
import time
from typing import Any

from vera.api.schemas import Cta, ReplyRequest
from vera.compose.composer import prepare, resolve
from vera.compose.facts import Ctx, build_fact_sheet
from vera.compose.models import Skip
from vera.compose.numbers import numbers_in_text
from vera.compose.prompts import REPLY_SCHEMA, REPLY_SYSTEM, build_reply_prompt
from vera.compose.validator import validate_reply
from vera.domain.ids import sha256, text_hash, utc_now_iso
from vera.domain.language import Language, detect_language, hindi_word_count
from vera.llm.gateway import LLMGateway, LLMUnavailable
from vera.observability.log import log_event
from vera.reply import responses as r
from vera.reply.classifier import Classification, classify, wait_seconds
from vera.store.state import Conversation, MerchantFlags, Store, Turn

AUTO_REPLY_WAIT_S = 86400
RESTART = re.compile(r"\b(hi vera|hello vera|start|resume|restart)\b", re.IGNORECASE)
MAX_INBOUND_HASHES = 30
FIXED_WORDING = {"auto_reply", "hostile", "opt_out", "slot_selection", "defer"}  # exact phrasing matters here


def _send(body: str, cta: Cta, rationale: str) -> dict[str, Any]:
    return {"action": "send", "body": body, "cta": cta, "rationale": rationale}


def _wait(seconds: int, rationale: str) -> dict[str, Any]:
    return {"action": "wait", "wait_seconds": int(seconds), "rationale": rationale}


def _end(rationale: str) -> dict[str, Any]:
    return {"action": "end", "rationale": rationale}


class ReplyEngine:
    def __init__(
        self, store: Store, gateway: LLMGateway | None = None, deadline_s: float = 5.0, llm_timeout_s: float = 4.5
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.deadline_s = deadline_s
        self.llm_timeout_s = llm_timeout_s

    # --- state -------------------------------------------------------------------------------------------
    def _conversation(self, req: ReplyRequest) -> Conversation:
        conv = self.store.conversations.get(req.conversation_id)
        if conv is not None:
            return conv
        conv = Conversation(
            conversation_id=req.conversation_id,
            merchant_id=req.merchant_id,
            customer_id=req.customer_id,
            kind="conversation",
            family="generic",
            send_as="merchant_on_behalf" if req.from_role == "customer" else "vera",
            status="awaiting_reply",
            created_from="lazy",
        )
        merchant = self.store.get("merchant", req.merchant_id) or {}
        ctx = self._lazy_ctx(conv, merchant)
        conv.last_proposal = ctx.last_vera_proposal() if ctx else None
        log_event("reply.lazy_conversation", conversation_id=conv.conversation_id, merchant_id=req.merchant_id)
        return conv

    def _lazy_ctx(self, conv: Conversation, merchant: dict[str, Any]) -> Ctx | None:
        if not merchant:
            return None
        category = self.store.get("category", merchant.get("category_slug")) or {}
        trigger: dict[str, Any] = {
            "id": conv.conversation_id,
            "kind": conv.kind or "conversation",
            "merchant_id": merchant.get("merchant_id"),
            "payload": {},
        }
        customer = self.store.get("customer", conv.customer_id) if conv.customer_id else None
        return Ctx(
            trigger_id=conv.conversation_id, trigger=trigger, merchant=merchant, category=category, customer=customer
        )

    def _ctx(self, conv: Conversation) -> Ctx | None:
        if conv.trigger_id:
            ctx = resolve(self.store, conv.trigger_id)
            if not isinstance(ctx, Skip):
                return ctx
        return self._lazy_ctx(conv, self.store.get("merchant", conv.merchant_id) or {})

    @staticmethod
    def _language(conv: Conversation, ctx: Ctx | None, message: str) -> Language:
        detected = detect_language(message)
        if detected == "hinglish":
            return "hinglish"
        if len(message.split()) >= 4 and hindi_word_count(message) == 0:
            return "english"
        if conv.last_inbound_language in {"hinglish", "english"}:
            return conv.last_inbound_language  # type: ignore[return-value]
        if ctx is None:
            return "english"
        return ctx.cust_lang if conv.send_as == "merchant_on_behalf" else ctx.lang

    # --- entry point -------------------------------------------------------------------------------------
    async def handle(self, req: ReplyRequest) -> dict[str, Any]:
        deadline = time.monotonic() + self.deadline_s
        conv = self._conversation(req)
        digest = sha256(f"{req.turn_number}|{req.message}")[:16]
        for turn in conv.turns:
            if turn.request_digest == digest and turn.response is not None:
                return turn.response  # idempotent replay
        merchant_id = conv.merchant_id or req.merchant_id or ""
        flags = self.store.merchant_flags(merchant_id) if merchant_id else MerchantFlags(merchant_id="")
        ctx = self._ctx(conv)
        language = self._language(conv, ctx, req.message)
        if ctx is not None:
            ctx.lang_override = language
        inbound_hash = text_hash(req.message)
        cls = classify(
            req.message,
            from_role=req.from_role,
            last_bot_was_proposal=bool(conv.last_proposal),
            seen_before=inbound_hash in flags.auto_reply_counts or inbound_hash in flags.inbound_hashes,
            offered_slots=r.offered_slots(ctx) if ctx else None,
        )
        response = self._policy(conv, ctx, flags, cls, req)
        response = self._checked(conv, ctx, flags, cls, response, req.message)
        response = await self._llm_rewrite(conv, ctx, flags, cls, response, req, deadline)
        self._record(conv, flags, req, cls, digest, inbound_hash, language, response)
        log_event("reply.done", conversation_id=conv.conversation_id, intent=cls.intent, action=response["action"])
        return response

    # --- policy (09 §3) ----------------------------------------------------------------------------------
    def _policy(
        self, conv: Conversation, ctx: Ctx | None, flags: MerchantFlags, cls: Classification, req: ReplyRequest
    ) -> dict[str, Any]:
        intent, why = cls.intent, f"Detected {cls.intent} ({cls.evidence})"
        if intent == "auto_reply":
            count = sum(flags.auto_reply_counts.values()) + 1
            if count == 1 and ctx is not None and conv.status != "ended":
                body, cta = r.auto_reply_note(ctx, conv)
                return _send(body, cta, f"{why}: first canned reply for this merchant, one note for the owner.")
            if count == 2:
                return _wait(
                    AUTO_REPLY_WAIT_S,
                    f"{why}: second canned reply from this merchant; owner not at the phone, backing off 24h.",
                )
            return _end(f"{why}: canned reply {count} times with no real response; closing without further sends.")
        if intent == "opt_out":
            return _end(f"{why}: merchant asked to stop; closing and suppressing proactive sends.")
        if intent == "hostile":
            if conv.hostile_count == 0 and conv.status != "ended" and ctx is not None:
                body, cta = r.apology(ctx)
                return _send(body, cta, f"{why}: one apology with an opt-out path, no pitch.")
            return _end(f"{why}: repeated frustration; closing and suppressing proactive sends.")
        if ctx is None:
            return _wait(3600, f"{why}: no merchant context for this conversation; backing off.")
        if conv.status == "ended" and flags.opted_out and not RESTART.search(req.message):
            if intent == "off_topic":
                body, _ = r.off_topic(ctx, Conversation(conversation_id="-"), req.message)
                return _send(
                    body.split(". ")[0].rstrip(".") + ".", "none", f"{why}: after opt-out; decline only, no pitch."
                )
            body, cta = r.reopen_answer(ctx)
            return _send(body, cta, f"{why}: merchant wrote again after the opt-out; answering without a pitch.")
        if intent == "slot_selection":
            slots = r.offered_slots(ctx)
            label = slots[cls.slot_index] if cls.slot_index is not None and cls.slot_index < len(slots) else None
            body, cta = r.slot_confirm(ctx, label, req.message)
            return _send(
                body,
                cta,
                f"{why}: confirming "
                + (f"the offered slot {label}." if label else "that the business will confirm the requested time."),
            )
        if intent == "accept":
            if conv.status == "action_mode":
                body, cta = r.done_close(ctx)
                return _send(body, cta, f"{why}: confirmation after the deliverable; closing the loop.")
            body, cta = r.deliver(ctx, conv)
            return _send(
                body,
                cta,
                f"{why}: switching to action mode and delivering it now, confirm-style CTA, no qualifying questions.",
            )
        if intent == "defer":
            return _wait(wait_seconds(req.message), f"{why}: merchant asked for time.")
        if intent == "soft_no":
            if conv.soft_no_count == 0:
                body, cta = r.soft_no(ctx)
                return _send(body, cta, f"{why}: one lighter alternative, once.")
            return _end(f"{why}: second no; exiting gracefully.")
        if intent == "off_topic":
            body, cta = r.off_topic(ctx, conv, req.message)
            return _send(body, cta, f"{why}: declined politely in one line and returned to the open thread.")
        if intent == "question":
            body, cta = r.answer_question(ctx, conv, req.message)
            return _send(body, cta, f"{why}: answered only from context, then one next step.")
        if intent == "engaged_info":
            body, cta = r.use_their_answer(ctx, conv, req.message)
            return _send(body, cta, f"{why}: used the merchant's input to deliver the next step.")
        body, cta = r.clarify(ctx, conv)
        return _send(body, cta, f"{why}: restating the single open question.")

    # --- validation --------------------------------------------------------------------------------------
    def _checked(
        self,
        conv: Conversation,
        ctx: Ctx | None,
        flags: MerchantFlags,
        cls: Classification,
        response: dict[str, Any],
        inbound: str,
    ) -> dict[str, Any]:
        if response["action"] != "send" or ctx is None:
            return response
        sheet = build_fact_sheet(ctx, [])
        extra = set(numbers_in_text(inbound))
        action_mode = cls.intent in {"accept", "engaged_info"}
        check = validate_reply(
            response["body"],
            sheet,
            language=ctx.lang,
            extra_numbers=extra,
            action_mode=action_mode,
            prior_body_hashes=flags.sent_body_hashes,
        )
        if check.ok:
            return response
        log_event("reply.validation", conversation_id=conv.conversation_id, violations=check.violations)
        body, cta = r.reopen_answer(ctx) if "V13" in ",".join(check.violations) else r.clarify(ctx, conv)
        if validate_reply(
            body, sheet, language=ctx.lang, extra_numbers=extra, prior_body_hashes=flags.sent_body_hashes
        ).ok:
            return _send(body, cta, response["rationale"] + " (safe variant after validation)")
        return _wait(3600, response["rationale"] + " (no safe wording available; backing off)")

    # --- optional LLM phrasing (reply_v1) -----------------------------------------------------------------
    async def _llm_rewrite(
        self,
        conv: Conversation,
        ctx: Ctx | None,
        flags: MerchantFlags,
        cls: Classification,
        response: dict[str, Any],
        req: ReplyRequest,
        deadline: float,
    ) -> dict[str, Any]:
        if self.gateway is None or ctx is None or response["action"] != "send" or cls.intent in FIXED_WORDING:
            return response
        prep = prepare(self.store, conv.trigger_id) if conv.trigger_id else None
        facts = prep.sheet.render() if prep is not None and not isinstance(prep, Skip) else ""
        turns = [f"{t.role}: {t.body}" for t in conv.turns] + [f"{req.from_role}: {req.message}"]
        sheet = build_fact_sheet(ctx, [])
        prompt = build_reply_prompt(
            language=ctx.lang,
            intent=cls.intent,
            turns=turns,
            facts_block=facts,
            reference=response["body"],
            taboos=sheet.taboos,
        )
        try:
            data = await self.gateway.complete_json(
                REPLY_SYSTEM, prompt, REPLY_SCHEMA, min(self.llm_timeout_s, deadline - time.monotonic())
            )
        except LLMUnavailable as exc:
            log_event("reply.llm_unavailable", conversation_id=conv.conversation_id, reason=str(exc))
            return response
        body = " ".join(str(data.get("body") or "").split())
        check = validate_reply(
            body,
            sheet,
            language=ctx.lang,
            extra_numbers=set(numbers_in_text(req.message)),
            action_mode=cls.intent in {"accept", "engaged_info"},
            prior_body_hashes=flags.sent_body_hashes,
        )
        if not body or not check.ok:
            log_event("reply.llm_rejected", conversation_id=conv.conversation_id, violations=check.violations)
            return response
        return {**response, "body": body, "rationale": response["rationale"] + " Phrased by the reply model."}

    # --- bookkeeping -------------------------------------------------------------------------------------
    def _record(
        self,
        conv: Conversation,
        flags: MerchantFlags,
        req: ReplyRequest,
        cls: Classification,
        digest: str,
        inbound_hash: str,
        language: Language,
        response: dict[str, Any],
    ) -> None:
        now = req.received_at or utc_now_iso()
        conv.turns.append(
            Turn(
                turn_number=req.turn_number,
                role=req.from_role,
                body=req.message,
                ts=now,
                intent=cls.intent,
                action=response["action"],
                request_digest=digest,
                response=response,
            )
        )
        conv.last_inbound_language = language
        if cls.intent == "auto_reply":
            flags.auto_reply_counts[inbound_hash] = flags.auto_reply_counts.get(inbound_hash, 0) + 1
        else:  # a genuine reply resets the merchant's auto-reply ladder and unanswered counter
            flags.unanswered_proactive = 0
            flags.auto_reply_counts.clear()
        if cls.intent == "soft_no":
            conv.soft_no_count += 1
        if cls.intent == "hostile":
            conv.hostile_count += 1
        if response["action"] == "end":
            conv.status = "ended"
            if cls.intent in {"opt_out", "hostile"}:
                flags.opted_out, flags.opted_out_at = True, now
        elif response["action"] == "wait":
            conv.status = "waiting"
        else:
            body = response["body"]
            conv.turns.append(Turn(turn_number=None, role="vera", body=body, ts=now))
            flags.sent_body_hashes.append(text_hash(body))
            if RESTART.search(req.message) and flags.opted_out:
                flags.opted_out = False
            if response["cta"] == "none":  # a closing line: the loop is done unless we still owe a confirmation
                closing = (
                    cls.intent in {"accept", "engaged_info"}
                    or conv.status == "ended"
                    or (cls.intent == "slot_selection" and cls.slot_index is not None)
                )
                conv.status = "ended" if closing else "awaiting_reply"
                conv.last_proposal = None
            else:
                conv.status = "action_mode" if cls.intent in {"accept", "engaged_info"} else "awaiting_reply"
                conv.last_proposal = re.split(r"(?<=[.!?])\s+", body.strip())[-1]
        flags.inbound_hashes = (flags.inbound_hashes + [inbound_hash])[-MAX_INBOUND_HASHES:]
        self.store.save_conversation(conv)
        if flags.merchant_id:
            self.store.save_flags(flags)
