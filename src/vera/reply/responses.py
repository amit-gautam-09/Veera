"""Deterministic reply texts and action-mode deliverables built only from context (09 §3, §5)."""

from __future__ import annotations

import re

from vera.api.schemas import Cta
from vera.compose.facts import Ctx, humanize
from vera.compose.merchant_kinds import first_sentence, parse_trend, sentences, source_of
from vera.compose.numbers import fmt_date, fmt_int, fmt_money, fmt_time
from vera.domain.language import detect_language
from vera.store.state import Conversation

Reply = tuple[str, Cta]


def _confirm(ctx: Ctx, what_en: str, what_hi: str) -> str:
    return ctx.t(f"Reply CONFIRM and I'll {what_en}.", f"CONFIRM reply karein, main {what_hi}.")


def _frame(ctx: Ctx, intro_en: str, intro_hi: str, draft: str, confirm: str) -> str:
    return f"{ctx.t(intro_en, intro_hi)} {draft} {confirm}".strip()


def _offer(ctx: Ctx) -> str | None:
    return ctx.active_offers[0] if ctx.active_offers else None


def _post_draft(ctx: Ctx, offer: str | None) -> str:
    if offer:
        return f'"{offer} at {ctx.business}, {ctx.locality}. Message us here or walk in to book."'
    return f'"{ctx.business}, {ctx.locality}: open this week. Message us here to book."'


# --- deliverables per kind / family ---------------------------------------------------------------------
def deliver(ctx: Ctx, conv: Conversation) -> Reply:
    kind, p = ctx.kind, ctx.payload
    if kind == "research_digest":
        item = ctx.digest_item(p.get("top_item_id")) or ctx.pick_digest(["research", "tech", "trend"])
        if item:
            gist = " ".join(sentences(item.get("summary"))[:2])
            draft = f'"{item.get("title")}. Ask us at your next visit whether this applies to you."'
            return _frame(
                ctx,
                f"Here's the gist ({source_of(item)}): {gist} Draft note for your {ctx.people}:",
                f"Yeh raha gist ({source_of(item)}): {gist} Aapke {ctx.people} ke liye draft note:",
                draft,
                _confirm(ctx, "format it for WhatsApp", "ise WhatsApp ke liye format kar doongi"),
            ), "binary_confirm_cancel"
    if kind == "regulation_change":
        item = ctx.digest_item(p.get("top_item_id")) or ctx.pick_digest(["compliance"])
        if item:
            deadline = fmt_date(p.get("deadline_iso") or item.get("date"), with_year=True) or "the deadline"
            steps = (
                f"1) {str(item.get('actionable') or 'Check your setup').rstrip('.')}. 2) Note the result in your SOP. "
                f"3) Re-check before {deadline}."
            )
            return _frame(
                ctx,
                "Here's the checklist:",
                "Yeh raha checklist:",
                steps,
                _confirm(
                    ctx, "turn it into a 1-page note you can print", "ise print karne layak 1-page note bana doongi"
                ),
            ), "binary_confirm_cancel"
    if kind == "cde_opportunity":
        item = ctx.digest_item(p.get("digest_item_id")) or ctx.pick_digest(["cde"])
        if item:
            when = ", ".join(x for x in (fmt_date(item.get("date")), fmt_time(item.get("date"))) if x)
            return ctx.t(
                f"Done, noted {item.get('title')} on {when}. I'll remind you here the day before.",
                f"Ho gaya, {item.get('title')} ({when}) note kar liya. Ek din pehle yahan reminder bhej doongi.",
            ), "none"
    if kind == "supply_alert" and p.get("molecule"):
        batches = " and ".join(str(b) for b in p.get("affected_batches") or [])
        draft = (
            f'"Namaste, {ctx.business} here. {p["molecule"]} batches {batches} are under a voluntary recall for '
            'sub-potency. There is no safety risk, but please bring the strip back and we will replace it."'
        )
        steps = ctx.t(
            "Counter steps: 1) pull the batches, 2) check your repeat-Rx list for them, 3) send this note.",
            "Counter steps: 1) batches hata dijiye, 2) repeat-Rx list check kijiye, 3) yeh note bhejiye.",
        )
        return _frame(
            ctx,
            "Here's the customer note:",
            "Yeh raha customer note:",
            f"{draft} {steps}",
            _confirm(ctx, "prepare it for your affected customers", "ise affected customers ke liye ready kar doongi"),
        ), "binary_confirm_cancel"
    if kind == "category_seasonal":
        item = next(
            (c for c in ctx.category.get("patient_content_library") or [] if "summer" in str(c.get("id", ""))), None
        )
        trends = [t for t in (parse_trend(str(x)) for x in p.get("trends") or []) if t]
        body = first_sentence(item.get("body")) if item else ", ".join(trends[:3])
        offer = next((o for o in ctx.active_offers if "deliver" in o.lower()), None)
        draft = f'"{body}' + (f" {offer}." if offer else "") + '"'
        return _frame(
            ctx,
            "Here's a short customer note:",
            "Yeh raha customer note:",
            draft,
            _confirm(ctx, "send it to your customers", "ise customers ko bhej doongi"),
        ), "binary_confirm_cancel"
    if kind in {"renewal_due", "winback_eligible"} and ctx.subscription.get("plan"):
        plan_name = p.get("plan") or ctx.subscription.get("plan")
        amount = f" for {fmt_money(p['renewal_amount'])}" if p.get("renewal_amount") else ""
        return ctx.t(
            f"Noted. I'm raising the {plan_name} renewal request{amount}; you'll see the payment request here shortly.",
            f"Theek hai. {plan_name} renewal request{amount} raise kar rahi hoon; payment request yahan "
            "jaldi aa jayega.",
        ), "none"
    if kind == "gbp_unverified":
        path = str(p.get("verification_path") or "")
        steps = ctx.t(
            "Steps: 1) I request the code from Google, 2) it arrives by "
            + ("postcard or phone call" if "postcard" in path else "phone")
            + ", 3) you send me the code here.",
            "Steps: 1) main Google se code request karti hoon, 2) code "
            + ("postcard ya phone call" if "postcard" in path else "phone")
            + " se aayega, 3) aap code yahan bhej dijiye.",
        )
        return f"{steps} {_confirm(ctx, 'start the request', 'request shuru kar doongi')}", "binary_confirm_cancel"
    if kind == "review_theme_emerged":
        theme = humanize(str(p.get("theme") or "your service"))
        replies = (
            f"1) \"Thanks for telling us, and sorry about the {theme}. We're looking into it and hope to "
            'serve you better next time." 2) "Thank you for the honest review. We have noted the '
            f'{theme} and would love another chance."'
        )
        return _frame(
            ctx,
            "Here are two short replies:",
            "Yeh rahe do short replies:",
            replies,
            _confirm(ctx, "post them", "inhe post kar doongi"),
        ), "binary_confirm_cancel"
    if kind == "competitor_opened":
        pos = ctx.top_theme("pos")
        line = f'"{pos["common_quote"]}": ' if pos and pos.get("common_quote") else ""
        draft = f'"{ctx.business}, {ctx.locality}. {line}that is what our {ctx.people} tell us."'
        return _frame(
            ctx,
            "Draft line for your Google description:",
            "Aapke Google description ke liye draft line:",
            draft,
            _confirm(ctx, "update it", "ise update kar doongi"),
        ), "binary_confirm_cancel"
    if kind == "milestone_reached":
        draft = (
            f'"Thank you for choosing {ctx.business}. If you enjoyed your visit, a quick Google review helps us a lot."'
        )
        return _frame(
            ctx,
            "Here's the review request:",
            "Yeh raha review request:",
            draft,
            _confirm(ctx, "send it to your regulars", "ise aapke regulars ko bhej doongi"),
        ), "binary_confirm_cancel"
    if kind == "active_planning_intent":
        return ctx.t(
            "Done. I'll turn the confirmed draft into a Google post and a WhatsApp message and share both "
            "here for a final look.",
            "Ho gaya. Confirmed draft se ek Google post aur WhatsApp message bana ke yahan final check ke "
            "liye bhej doongi.",
        ), "none"
    if conv.family == "approval":
        return ctx.t(
            f"Done, sending the reminder to your {ctx.people[:-1]} from your number now.",
            "Ho gaya, aapke number se reminder abhi bhej rahi hoon.",
        ), "none"
    return _generic_posts(ctx, conv)


def _generic_posts(ctx: Ctx, conv: Conversation) -> Reply:
    """Default deliverable: Google post drafts from the merchant's offers (or topics they asked for)."""
    topics = _requested_topics(ctx)
    offer = _offer(ctx)
    items: list[str] = [o for o in (ctx.catalog(t) for t in topics) if o] or ([offer] if offer else [])
    if not items:
        items = [o for o in (ctx.catalog("@"),) if o]
    items = list(dict.fromkeys(items))
    drafts = " ".join(f"{i + 1}) {_post_draft(ctx, o)}" for i, o in enumerate(items[:3])) or _post_draft(ctx, None)
    theirs = [o for o in items if o in ctx.active_offers]
    note = (
        ""
        if len(theirs) == len(items)
        else ctx.t(" (catalog offers shown as suggestions)", " (catalog offers suggestion ke taur par)")
    )
    return _frame(
        ctx,
        f"Here are the draft Google posts{note}:",
        f"Yeh rahe draft Google posts{note}:",
        drafts,
        _confirm(ctx, "schedule them", "inhe schedule kar doongi"),
    ), "binary_confirm_cancel"


def _requested_topics(ctx: Ctx) -> list[str]:
    last_merchant = next((h.get("body") for h in reversed(ctx.history) if h.get("from") == "merchant"), "") or ""
    words = re.findall(r"[a-z]{5,}", str(last_merchant).lower())
    return [w.rstrip("s") for w in words if w not in {"please", "focus", "would", "could", "about", "there", "their"}]


# --- intent replies --------------------------------------------------------------------------------------
def restatable(ctx: Ctx, conv: Conversation) -> str:
    """The open ask, only if it is in the language we are replying in (no mixed-language replies)."""
    ask = (conv.last_proposal or "").strip()
    wanted = "hinglish" if ctx.lang == "hinglish" else "english"
    return ask if ask and detect_language(ask) == wanted else ""


def pending(ctx: Ctx) -> str:
    return ctx.t("what I suggested above", "jo maine upar suggest kiya")


def auto_reply_note(ctx: Ctx, conv: Conversation) -> Reply:
    ask = restatable(ctx, conv)
    if ask:
        return ctx.t(
            f"This looks like an automatic reply, so a note for the owner: {ask}",
            f"Yeh automatic reply lag raha hai, isliye owner ke liye: {ask}",
        ), "binary_yes_no"
    return ctx.t(
        f"This looks like an automatic reply. When the owner of {ctx.business} is free, just reply YES and "
        "I'll share what I found.",
        f"Yeh automatic reply lag raha hai. {ctx.business} ke owner free hon toh bas YES reply karein, main "
        "details bhej doongi.",
    ), "binary_yes_no"


def apology(ctx: Ctx) -> Reply:
    return ctx.t(
        "Sorry for the noise. Reply STOP and I won't message again, or tell me what would actually help.",
        "Sorry, maaf kijiye. STOP reply karein toh main aur message nahi karungi, ya bataiye kya kaam ka hoga.",
    ), "binary_yes_no"


OFF_TOPIC_LINES = [
    (
        r"gst|tax|itr|accounting|\bca\b",
        "GST and tax filing are best handled by your CA; that's outside what I can do.",
        "GST aur tax filing ke liye aapke CA sahi rahenge; yeh mere kaam ke bahar hai.",
    ),
    (
        r"loan|bank|credit",
        "Loans and banking are outside what I can help with.",
        "Loan aur banking mere kaam ke bahar hai.",
    ),
]


def off_topic(ctx: Ctx, conv: Conversation, inbound: str) -> Reply:
    low = inbound.lower()
    en, hi = next(
        ((e, h) for pat, e, h in OFF_TOPIC_LINES if re.search(pat, low)),
        ("That one is outside what I can help with.", "Yeh mere kaam ke bahar hai."),
    )
    back = restatable(ctx, conv)
    tail = (
        ctx.t(f"Coming back to our thread: {back}", f"Wapas apni baat par: {back}")
        if back
        else ctx.t(
            f"Coming back to our thread: want me to go ahead with {pending(ctx)}?",
            f"Wapas apni baat par: kya main {pending(ctx)} uske saath aage badhoon?",
        )
        if conv.last_proposal
        else ctx.t(
            f"Happy to keep helping with {ctx.business}'s Google profile and offers; want a quick idea for this week?",
            f"{ctx.business} ke Google profile aur offers mein madad karti rahungi; is hafte ke liye ek quick idea bhejoon?",
        )
    )
    return f"{ctx.t(en, hi)} {tail}", "binary_yes_no"


def soft_no(ctx: Ctx) -> Reply:
    return ctx.t(
        "No problem. Want just a 2-line summary instead, so you can decide later?",
        "Koi baat nahi. Kya main bas 2 line ka summary bhej doon, aap baad mein decide kar lijiye?",
    ), "binary_yes_no"


def answer_question(ctx: Ctx, conv: Conversation, inbound: str) -> Reply:
    low = inbound.lower()
    deliverable = pending(ctx)
    if re.search(r"price|cost|charge|fee|kitna|kitne|rate|₹", low) and ctx.active_offers:
        offers = "; ".join(ctx.active_offers[:3])
        return ctx.t(
            f"Your current offers on the profile: {offers}. Want me to go ahead with {deliverable}?",
            f"Aapke profile par abhi ke offers: {offers}. Kya main {deliverable} ke saath aage badhoon?",
        ), "binary_yes_no"
    if re.search(r"\bhow\b|kaise|process|steps|time", low):
        return ctx.t(
            f"It's quick: I draft it, you approve it here, and I publish it. Want me to start on {deliverable}?",
            f"Simple hai: main draft karti hoon, aap yahan approve karte hain, main publish kar deti hoon. "
            f"Kya main {deliverable} shuru kar doon?",
        ), "binary_yes_no"
    views, calls = ctx.perf.get("views"), ctx.perf.get("calls")
    seen = (
        ctx.t(
            f"what I can see is {fmt_int(views)} profile views and {calls} calls in the last 30 days",
            f"mere paas pichhle 30 din ke {fmt_int(views)} profile views aur {calls} calls ka data hai",
        )
        if isinstance(views, int) and isinstance(calls, int)
        else ctx.t("I only have your own profile data", "mere paas sirf aapke profile ka data hai")
    )
    return ctx.t(
        f"I don't have that detail; {seen}. Want me to go ahead with {deliverable}?",
        f"Yeh detail mere paas nahi hai; {seen}. Kya main {deliverable} ke saath aage badhoon?",
    ), "binary_yes_no"


def use_their_answer(ctx: Ctx, conv: Conversation, inbound: str) -> Reply:
    """Curious-ask answers become a post draft; other statements move the thread to the deliverable."""
    if conv.kind == "curious_ask_due":
        answer = re.sub(r"[\"“”]", "", inbound).strip().rstrip(".")
        draft = f'"{answer[:1].upper() + answer[1:]} at {ctx.business}, {ctx.locality}. Message us here to book."'
        return _frame(
            ctx,
            "Here's a draft Google post built on that:",
            "Uske hisaab se draft Google post:",
            draft,
            _confirm(ctx, "publish it", "ise publish kar doongi"),
        ), "binary_confirm_cancel"
    return deliver(ctx, conv)


def clarify(ctx: Ctx, conv: Conversation) -> Reply:
    ask = restatable(ctx, conv)
    if ask:
        return ctx.t(f"Just checking: {ask}", f"Ek baar confirm kar doon: {ask}"), "binary_yes_no"
    return ctx.t(
        f"Happy to help with {ctx.business}. Want a quick idea to get more calls this week?",
        f"{ctx.business} ke liye madad ke liye taiyaar hoon. Kya is hafte zyada calls ke liye ek quick idea bhejoon?",
    ), "binary_yes_no"


def done_close(ctx: Ctx) -> Reply:
    return ctx.t(
        "Done. It's queued, and I'll confirm here once it's live.",
        "Ho gaya. Queue mein daal diya hai, live hote hi yahan bata doongi.",
    ), "none"


def slot_confirm(ctx: Ctx, label: str | None, inbound: str) -> Reply:
    if label:
        return ctx.tc(
            f"Done, you're booked for {label} at {ctx.business}. Reply here if anything changes.",
            f"Ho gaya, aapki booking {label} ke liye {ctx.business} mein pakki hai. Kuch badle toh yahan bata dijiye.",
        ), "none"
    return ctx.tc(
        f"Noted. {ctx.business} will confirm your requested time shortly.",
        f"Noted. {ctx.business} aapka requested time jaldi confirm kar dega.",
    ), "none"


def reopen_answer(ctx: Ctx) -> Reply:
    return ctx.t(
        "Happy to help. What would you like me to look at first: your Google profile, offers or reviews?",
        "Zaroor. Pehle kya dekhoon: Google profile, offers ya reviews?",
    ), "open_ended"


def offered_slots(ctx: Ctx) -> list[str]:
    p = ctx.payload
    slots = p.get("available_slots") or p.get("next_session_options") or []
    return [str(s.get("label")) for s in slots if isinstance(s, dict) and s.get("label")]
