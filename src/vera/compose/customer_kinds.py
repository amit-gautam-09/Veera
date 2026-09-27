"""Customer-facing handlers (send_as=merchant_on_behalf) with the consent gate and approval re-route (07 §11, ADR-008)."""

from __future__ import annotations

import re
from typing import Any

from vera.api.schemas import Cta
from vera.compose.facts import Ctx, humanize
from vera.compose.merchant_kinds import base_facts
from vera.compose.models import Skip
from vera.compose.numbers import fmt_date, fmt_money
from vera.compose.playbook import KIND_FAMILY, F, Plan, handles

SERVICE_WORDS = {"cleaning", "checkup", "check-up", "whitening", "consult", "spa", "haircut", "trial", "thali"}


def consent_gate(ctx: Ctx) -> str | None:
    """None if the customer may be messaged; otherwise the reason."""
    c = ctx.customer
    if c is None:
        return "customer_missing"
    if c.get("merchant_id") and c.get("merchant_id") != ctx.trigger.get("merchant_id"):
        return "customer_merchant_mismatch"
    consent = c.get("consent") or {}
    if not consent.get("opted_in_at") or not consent.get("scope"):
        return "no_consent"
    if (c.get("preferences") or {}).get("reminder_opt_in") is False:
        return "reminder_opt_out"
    identity = c.get("identity") or {}
    if "phone_redacted" in identity and identity.get("phone_redacted") is None:
        return "no_phone"
    name = ctx.cust_name
    if name is None or name.walk_in:
        return "walk_in"
    return None


def customer_plan(
    ctx: Ctx,
    family: str,
    cta: Cta,
    lines: list[str],
    ask: str,
    facts: list[Any],
    levers: list[str],
    primary: str,
    deliverable: str | None = None,
    notes: list[str] | None = None,
) -> Plan:
    name = ctx.cust_name
    assert name is not None
    opener = f"Hi {name.addressee}," if name.addressee else ctx.tc("Hello,", "Namaste,")
    cust = ctx.customer or {}
    facts = (
        facts
        + base_facts(ctx)
        + [
            F("Customer", name.addressee or name.subject or "customer", "customer", True),
            F("Language preference", (cust.get("identity") or {}).get("language_pref", "n/a"), "customer", True),
            F("Customer state", cust.get("state", "n/a"), "customer"),
        ]
    )
    if name.subject:
        facts.append(F("Service is for", name.subject, "customer"))
    return Plan(
        family=family,
        cta=cta,
        lines=lines,
        ask=ask,
        facts=facts,
        levers=levers,
        primary=primary,
        send_as="merchant_on_behalf",
        customer_id=str(cust.get("customer_id") or ctx.trigger.get("customer_id")),
        language=ctx.cust_lang,
        opener=opener,
        deliverable=deliverable,
        notes=notes or [],
    )


def sender(ctx: Ctx) -> str:
    return f"{ctx.business}, {ctx.locality}"


def matching_offer(ctx: Ctx, *words: str) -> str | None:
    for offer in ctx.active_offers:
        if any(w in offer.lower() for w in words):
            return offer
    return None


def last_visit(ctx: Ctx) -> str | None:
    return fmt_date(((ctx.customer or {}).get("relationship") or {}).get("last_visit"), with_year=True)


# --- approval re-route (consent failed or no customer context) ----------------------------------------------
def approval_plan(ctx: Ctx, reason: str) -> Plan | Skip:
    if ctx.placeholder:
        return Skip(reason=f"consent:{reason}:thin_payload")
    p, kind = ctx.payload, ctx.kind
    facts: list[Any] = []
    if kind == "recall_due":
        service = humanize(str(p.get("service_due") or "visit"))
        due = fmt_date(p.get("due_date"))
        slots = [str(s.get("label")) for s in p.get("available_slots") or [] if isinstance(s, dict) and s.get("label")]
        what = (
            f"their {service}"
            + (f" (due {due})" if due else "")
            + (f"; open slots: {' or '.join(slots)}" if slots else "")
        )
    elif kind == "chronic_refill_due":
        meds = ", ".join(p.get("molecule_list") or [])
        runs_out = fmt_date(p.get("stock_runs_out_iso"))
        what = f"a refill of {meds}" + (f" before {runs_out}" if runs_out else "")
    elif kind in {"customer_lapsed_hard", "customer_lapsed_soft"}:
        days = p.get("days_since_last_visit")
        what = "a come-back note" + (f" ({days} days since their last visit)" if days else "")
    elif kind == "trial_followup":
        options = [str(s.get("label")) for s in p.get("next_session_options") or [] if isinstance(s, dict)]
        what = "a follow-up after their trial" + (f"; next session {options[0]}" if options else "")
    elif kind == "wedding_package_followup":
        wedding = fmt_date(p.get("wedding_date"), with_year=True)
        what = "their pre-wedding next step" + (f" (wedding on {wedding})" if wedding else "")
    elif kind == "appointment_tomorrow":
        what = "a reminder for tomorrow's appointment"
    else:
        what = humanize(kind)
    lines = [
        ctx.t(f"One of your {ctx.people} is due for {what}.", f"Aapke ek {ctx.people[:-1]} ke liye {what} due hai.")
    ]
    ask = ctx.t(
        "Want me to send them the reminder from your number?", "Kya main aapke number se unhe reminder bhej doon?"
    )
    facts.append(F("Reason customer was not messaged directly", reason))
    return Plan(
        family="approval",
        cta="binary_yes_no",
        lines=lines,
        ask=ask,
        facts=facts + base_facts(ctx),
        levers=["effort externalisation", "specificity"],
        primary=f"{kind} awaiting merchant approval",
        deliverable=f"customer reminder for {what}",
        notes=["merchant-facing; no customer name; only payload facts"],
    )


def gate(ctx: Ctx) -> str | None:
    reason = consent_gate(ctx)
    return reason


# --- reminder family -----------------------------------------------------------------------------------------
@handles("recall_due")
def recall_due(ctx: Ctx) -> Plan | Skip:
    if reason := gate(ctx):
        return approval_plan(ctx, reason)
    p = ctx.payload
    slots = [str(s.get("label")) for s in p.get("available_slots") or [] if isinstance(s, dict) and s.get("label")]
    if not ctx.placeholder and p.get("service_due"):
        service = humanize(str(p["service_due"])).replace("6 month", "6-month")
        due = fmt_date(p.get("due_date"))
        lines = [
            ctx.tc(
                f"{sender(ctx)} here: your {service} is due" + (f" on {due}." if due else "."),
                f"{sender(ctx)} se: aapki {service}" + (f" {due} ko" if due else "") + " due hai.",
            )
        ]
        offer = matching_offer(ctx, *[w for w in service.split() if len(w) > 3]) or matching_offer(ctx, *SERVICE_WORDS)
        if slots:
            lines.append(
                ctx.tc(
                    f"Two slots are open: {slots[0]} or {slots[1]}."
                    if len(slots) > 1
                    else f"A slot is open: {slots[0]}.",
                    f"Aapke liye slots khaali hain: {' ya '.join(slots[:2])}.",
                )
            )
        if offer:
            lines.append(ctx.tc(f"It's {offer}.", f"Charges: {offer}."))
        if slots:
            ask = ctx.tc(
                "Reply 1 or 2, or send a time that suits you."
                if len(slots) > 1
                else "Reply 1 to book it, or send a time that suits you.",
                "1 ya 2 reply karein, ya apna time bata dijiye."
                if len(slots) > 1
                else "1 reply karein, ya apna time bata dijiye.",
            )
            cta: Cta = "multi_choice_slot"
        else:
            ask = ctx.tc("Shall we find you a slot this week?", "Kya hum is hafte aapke liye slot dekh lein?")
            cta = "binary_yes_no"
        facts = [
            F("Service due", service, visible=True),
            F("Due date", due or "n/a", visible=True),
            F("Open slots", "; ".join(slots) or "none", visible=True),
            F("Price (their offer)", offer or "n/a"),
        ]
        return customer_plan(
            ctx,
            "customer_reminder",
            cta,
            lines,
            ask,
            facts,
            ["personalisation", "specificity", "low friction"],
            f"{service} due",
            deliverable="slot confirmation",
            notes=["only the listed slots; no add-ons"],
        )
    return thin_reminder(ctx, "recall")


def thin_reminder(ctx: Ctx, flavour: str) -> Plan | Skip:
    """Placeholder customer triggers (S-CUST-THIN + S-MISMATCH)."""
    visit, visits = last_visit(ctx), ((ctx.customer or {}).get("relationship") or {}).get("visits_total")
    since = ctx.tc(f" since your last visit on {visit}" if visit else "", f" (aakhri visit {visit})" if visit else "")
    offer = ctx.active_offers[0] if ctx.active_offers else None
    reason = {
        "dentists": ctx.tc(
            "it's a good time for your routine dental check-up", "aapke routine dental check-up ka time ho gaya hai"
        ),
        "salons": ctx.tc("it's about time for your next salon visit", "aapki agli salon visit ka time aa gaya hai"),
        "gyms": ctx.tc("we'd love to see you back for a session", "hum aapko phir se session mein dekhna chahenge"),
        "pharmacies": ctx.tc(
            "it may be time to restock your regular items", "aapke regular items restock karne ka time ho sakta hai"
        ),
        "restaurants": ctx.tc("your usual is waiting for you", "aapka favourite order aapka intezaar kar raha hai"),
    }.get(ctx.slug, ctx.tc("it's a good time to visit again", "phir se aane ka achha time hai"))
    lines = [ctx.tc(f"{sender(ctx)} here: {reason}{since}.", f"{sender(ctx)} se: {reason}{since}.")]
    if isinstance(visits, int) and visits > 1:
        lines.append(ctx.tc(f"Thanks for the {visits} visits so far.", f"Ab tak ki {visits} visits ke liye shukriya."))
    if offer:
        lines.append(ctx.tc(f"Our current offer: {offer}.", f"Abhi ka offer: {offer}."))
    ask = ctx.tc("Shall we hold a slot for you this week?", "Kya hum is hafte aapke liye ek slot rakh dein?")
    facts = [
        F("Last visit", visit or "n/a", "customer"),
        F("Visits", visits or "n/a", "customer"),
        F("Their offer", offer or "none"),
    ]
    mismatch = KIND_FAMILY.get(ctx.kind) == "customer_reminder" and ctx.slug != "dentists" and flavour == "recall"
    notes = [f"placeholder {ctx.kind}: no times, slots or services invented"]
    if mismatch or (flavour == "refill" and ctx.slug != "pharmacies"):
        notes.append(f"{ctx.kind} reinterpreted for {ctx.slug} as a routine next-visit reminder")
    return customer_plan(
        ctx,
        "customer_reminder",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["personalisation", "low friction"],
        f"thin {ctx.kind}",
        deliverable="slot booking",
        notes=notes,
    )


@handles("appointment_tomorrow")
def appointment_tomorrow(ctx: Ctx) -> Plan | Skip:
    if reason := gate(ctx):
        return approval_plan(ctx, reason)
    p = ctx.payload
    what = {
        "restaurants": ctx.tc("your table booking", "aapki table booking"),
        "pharmacies": ctx.tc("your order pickup", "aapka order pickup"),
    }.get(ctx.slug, ctx.tc("your appointment", "aapki appointment"))
    detail = ""
    if not ctx.placeholder:
        time_ = p.get("time") or p.get("slot_label") or p.get("appointment_time")
        service = p.get("service")
        detail = " ".join(str(x) for x in (service, time_) if x)
    lines = [
        ctx.tc(
            f"a quick reminder of {what} tomorrow at {sender(ctx)}" + (f" ({detail})." if detail else "."),
            f"kal {sender(ctx)} par {what} ka reminder" + (f" ({detail})." if detail else "."),
        )
    ]
    ask = ctx.tc(
        "Reply CONFIRM, or tell us if you need a different time.",
        "CONFIRM reply karein, ya batayein agar time badalna ho.",
    )
    return customer_plan(
        ctx,
        "customer_reminder",
        "binary_confirm_cancel",
        lines,
        ask,
        [F("Appointment", f"tomorrow{', ' + detail if detail else ''}", visible=True)],
        ["low friction", "clarity"],
        "appointment tomorrow",
        deliverable="appointment confirmation",
        notes=["no time or service unless the payload gives it"],
    )


@handles("chronic_refill_due")
def chronic_refill_due(ctx: Ctx) -> Plan | Skip:
    if reason := gate(ctx):
        return approval_plan(ctx, reason)
    p = ctx.payload
    if ctx.slug != "pharmacies" or ctx.placeholder or not p.get("molecule_list"):
        return thin_reminder(ctx, "refill")
    meds = ", ".join(str(m) for m in p["molecule_list"])
    runs_out = fmt_date(p.get("stock_runs_out_iso"))
    name = ctx.cust_name
    who = f"{name.subject} ji" if name and name.subject else ctx.tc("your", "aapki")
    lines = [
        ctx.tc(
            f"{sender(ctx)} here: {who}'s {meds} will run out" + (f" on {runs_out}." if runs_out else " soon."),
            f"{sender(ctx)} se: {who} ki {meds}" + (f" {runs_out} ko" if runs_out else " jald") + " khatam hongi.",
        )
    ]
    lines.append(ctx.tc("The same medicines are ready to go.", "Wahi medicines ready hain."))
    senior = matching_offer(ctx, "senior")
    delivery = matching_offer(ctx, "deliver")
    if senior and name and name.senior:
        lines.append(ctx.tc(f"{senior} applies.", f"{senior} lagu hoga."))
    if delivery:
        lines.append(ctx.tc(f"{delivery} applies too.", f"{delivery} bhi milega."))
    saved = p.get("delivery_address_saved")
    ask = ctx.tc(
        "Reply CONFIRM and we'll deliver to your saved address."
        if saved
        else "Reply CONFIRM and we'll keep them ready.",
        "CONFIRM reply karein, hum saved address par deliver kar denge."
        if saved
        else "CONFIRM reply karein, hum ready rakhenge.",
    )
    facts = [
        F("Medicines", meds, visible=True),
        F("Runs out", runs_out or "n/a", visible=True),
        F("Address saved", "yes" if saved else "no", visible=True),
        F("Senior offer", senior or "n/a"),
        F("Delivery offer", delivery or "n/a"),
    ]
    return customer_plan(
        ctx,
        "customer_reminder",
        "binary_confirm_cancel",
        lines,
        ask,
        facts,
        ["specificity", "convenience", "single confirm"],
        f"refill before {runs_out}",
        deliverable="dispatch confirmation",
        notes=["no invented totals, times or phone numbers"],
    )


# --- winback family ------------------------------------------------------------------------------------------
@handles("customer_lapsed_soft", "customer_lapsed_hard")
def customer_lapsed(ctx: Ctx) -> Plan | Skip:
    if reason := gate(ctx):
        return approval_plan(ctx, reason)
    cust, p = ctx.customer or {}, ctx.payload
    state = cust.get("state")
    offer = ctx.active_offers[0] if ctx.active_offers else None
    if state in {"active", "new"}:  # kind contradicts state: value-first, no lapse framing
        library = [c for c in ctx.category.get("patient_content_library") or [] if isinstance(c, dict)]
        item = next((c for c in library if "?" not in str(c.get("title"))), library[0] if library else None)
        if not item:
            return thin_reminder(ctx, "winback")
        title = str(item.get("title") or "").replace("?", "")
        lines = [
            ctx.tc(
                f'{sender(ctx)} here with a quick, useful read: "{title}".',
                f'{sender(ctx)} se ek kaam ki baat: "{title}".',
            )
        ]
        ask = ctx.tc("Want us to send you the short version?", "Kya hum aapko iska short version bhej dein?")
        return customer_plan(
            ctx,
            "customer_winback",
            "binary_yes_no",
            lines,
            ask,
            [F("Content", item.get("title"), "category"), F("Content body", item.get("body", ""), "category")],
            ["value-first", "reciprocity"],
            "value-first content",
            deliverable=f"content: {item.get('title')}",
            notes=["customer is active: no lapse framing"],
        )
    days = None if ctx.placeholder else p.get("days_since_last_visit")
    focus = None if ctx.placeholder else p.get("previous_focus")
    visit = last_visit(ctx)
    gap = ctx.tc(
        f"it's been {days} days since your last session with us"
        if days
        else (f"we haven't seen you since {visit}" if visit else "it's been a while since your last visit"),
        f"aapki aakhri visit ko {days} din ho gaye"
        if days
        else (f"{visit} ke baad aap nahi aaye" if visit else "kaafi time ho gaya"),
    )
    lines = [
        ctx.tc(f"{sender(ctx)} here: {gap}, and that's completely fine.", f"{sender(ctx)} se: {gap}, koi baat nahi.")
    ]
    if focus and offer:
        lines.append(
            ctx.tc(
                f"Since you were working on {humanize(str(focus))}, our {offer} could be an easy way back in.",
                f"Aap {humanize(str(focus))} par kaam kar rahe the, toh {offer} se aasaani se shuru kar sakte hain.",
            )
        )
    elif offer:
        lines.append(ctx.tc(f"If it helps, {offer} is on right now.", f"Abhi {offer} chal raha hai."))
    ask = ctx.tc(
        "Want us to keep a spot for you this week, no commitment?",
        "Kya hum is hafte aapke liye ek spot rakh dein, bina kisi commitment ke?",
    )
    facts = [
        F("Days since last visit", days or "n/a", visible=True),
        F("Previous focus", humanize(str(focus)) if focus else "n/a"),
        F("Last visit", visit or "n/a", "customer"),
        F("Offer (theirs)", offer or "none"),
    ]
    return customer_plan(
        ctx,
        "customer_winback",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["no-guilt warmth", "relevance", "zero commitment"],
        "lapsed customer",
        deliverable="spot booking",
        notes=["no guilt, no shame, no invented classes or dates"],
    )


# --- follow-up family ----------------------------------------------------------------------------------------
@handles("trial_followup")
def trial_followup(ctx: Ctx) -> Plan | Skip:
    if reason := gate(ctx):
        return approval_plan(ctx, reason)
    p = ctx.payload
    options = [
        str(s.get("label")) for s in p.get("next_session_options") or [] if isinstance(s, dict) and s.get("label")
    ]
    if ctx.placeholder or not p.get("trial_date"):
        return thin_reminder(ctx, "trial")
    name = ctx.cust_name
    services = ((ctx.customer or {}).get("relationship") or {}).get("services_received") or []
    trial = humanize(str(services[-1])) if services else "trial"
    for_whom = f"{name.subject}'s " if name and name.subject else "your "
    lines = [
        ctx.tc(
            f"{sender(ctx)} here: thanks for coming to {for_whom}{trial} on {fmt_date(p['trial_date'])}.",
            f"{sender(ctx)} se: {fmt_date(p['trial_date'])} ko {trial} ke liye aane ka shukriya.",
        )
    ]
    if options:
        lines.append(ctx.tc(f"The next session is {options[0]}.", f"Agla session {options[0]} ko hai."))
        ask = ctx.tc(
            "Reply 1 to book it, or tell us a time that suits you.",
            "1 reply karein booking ke liye, ya apna time batayein.",
        )
        cta: Cta = "multi_choice_slot"
    else:
        ask = ctx.tc("Shall we book the next session?", "Kya hum agla session book kar dein?")
        cta = "binary_yes_no"
    facts = [
        F("Trial date", fmt_date(p["trial_date"]), visible=True),
        F("Next session", "; ".join(options) or "n/a", visible=True),
    ]
    return customer_plan(
        ctx,
        "customer_followup",
        cta,
        lines,
        ask,
        facts,
        ["continuity", "specificity", "low friction"],
        "trial follow-up",
        deliverable="next-session booking",
    )


@handles("wedding_package_followup")
def wedding_package_followup(ctx: Ctx) -> Plan | Skip:
    if reason := gate(ctx):
        return approval_plan(ctx, reason)
    p = ctx.payload
    wedding = fmt_date(
        p.get("wedding_date") or ((ctx.customer or {}).get("preferences") or {}).get("wedding_date"), with_year=True
    )
    if not wedding or ctx.slug not in {"salons", "dentists", "gyms"}:
        return Skip(reason="no_hook:no_wedding_date")
    trial = fmt_date(p.get("trial_completed"))
    raw_step = str(p.get("next_step_window_open") or "next_prep_step")
    m = re.match(r"^(.*)_(\d+)day$", raw_step)
    step = f"{m.group(2)}-day {humanize(m.group(1)).replace('skin prep', 'skin-prep')}" if m else humanize(raw_step)
    lines = [
        ctx.tc(
            f"{sender(ctx)} here"
            + (f": since your bridal trial on {trial}," if trial else ",")
            + f" the next step before your wedding on {wedding} is the {step}, and its window is open now.",
            f"{sender(ctx)} se"
            + (f": {trial} ke bridal trial ke baad," if trial else ",")
            + f" {wedding} ki shaadi se pehle agla step {step} hai, jiska time ab shuru ho gaya hai.",
        )
    ]
    pref = ((ctx.customer or {}).get("preferences") or {}).get("preferred_slots")
    day = "Saturday" if pref and "sat" in str(pref).lower() else None
    ask = ctx.tc(
        f"Shall we hold a {day + ' ' if day else ''}consultation to plan it?",
        f"Kya hum plan karne ke liye {day + ' ko ' if day else ''}ek consultation rakh dein?",
    )
    facts = [
        F("Wedding date", wedding, visible=True),
        F("Trial completed", trial or "n/a", visible=True),
        F("Next step", step, visible=True),
        F("Preferred slot", pref or "n/a", "customer"),
    ]
    return customer_plan(
        ctx,
        "customer_followup",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["timing window", "continuity"],
        f"wedding on {wedding}",
        deliverable="consultation booking",
        notes=["no programme price unless it is an active offer"],
    )


def money(value: Any) -> str:
    return fmt_money(value)
