"""Merchant-facing handlers (send_as=vera), one per trigger kind in 07 §5–§10 plus the generic handler."""

from __future__ import annotations

import re
from typing import Any

from vera.api.schemas import Cta
from vera.compose.facts import Ctx, humanize, signal_label
from vera.compose.models import Skip
from vera.compose.numbers import fmt_date, fmt_int, fmt_money, fmt_pct, fmt_time, parse_iso, pretty_dates, weekday
from vera.compose.playbook import F, Plan, handles

WINDOW = {"7d": ("this week", "is hafte"), "30d": ("over the last 30 days", "pichhle 30 din mein")}
METRIC = {
    "calls": "calls",
    "views": "profile views",
    "directions": "direction requests",
    "ctr": "CTR",
    "leads": "leads",
}
PEER_KEY = {"calls": "avg_calls_30d", "views": "avg_views_30d", "directions": "avg_directions_30d", "ctr": "avg_ctr"}
DELTA_KEY = {"views_pct": "views", "calls_pct": "calls", "ctr_pct": "ctr"}


# --- shared helpers ---------------------------------------------------------------------------------
_ABBREV = re.compile(r"(?:\b(?:Dr|Mr|Mrs|Ms|St|vs|p|No)|\b[A-Z])\.$")


def sentences(text: str | None) -> list[str]:
    """Split prose into sentences without breaking after 'Dr.', 'p.' or initials."""
    out: list[str] = []
    buf = ""
    for piece in re.split(r"(?<=[.!?])\s+", str(text or "").strip()):
        buf = f"{buf} {piece}".strip() if buf else piece
        if not _ABBREV.search(buf):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return [s for s in out if s]


def first_sentence(text: str | None) -> str:
    parts = sentences(text)
    return pretty_dates(parts[0].rstrip(".") + ".") if parts else ""


def metric_render(ctx: Ctx, metric: str, value: Any = None) -> str:
    value = ctx.perf.get(metric) if value is None else value
    if metric == "ctr" and isinstance(value, int | float):
        return f"{value * 100:.1f}%"
    return fmt_int(value) if isinstance(value, int | float) else str(value)


def peer_gap(ctx: Ctx, metric: str) -> tuple[float, float] | None:
    mine, peer = ctx.perf.get(metric), ctx.peer.get(PEER_KEY.get(metric, ""))
    if isinstance(mine, int | float) and isinstance(peer, int | float) and peer:
        return float(mine), float(peer)
    return None


def peer_phrase(ctx: Ctx, metric: str) -> str | None:
    gap = peer_gap(ctx, metric)
    if not gap:
        return None
    mine, peer = gap
    if ctx.lang == "hinglish":
        return (
            f"{metric_render(ctx, metric, mine)} {METRIC[metric]}, jabki metro {ctx.slug} average "
            f"{metric_render(ctx, metric, peer)} hai"
        )
    return (
        f"{metric_render(ctx, metric, mine)} {METRIC[metric]} vs the metro {ctx.slug} average of "
        f"{metric_render(ctx, metric, peer)}"
    )


def best_lead(ctx: Ctx) -> tuple[str, float] | None:
    """Metric where the merchant most exceeds the peer average (ratio > 1.1)."""
    best: tuple[str, float] | None = None
    for metric in ("ctr", "calls", "views", "directions"):
        gap = peer_gap(ctx, metric)
        if gap and gap[0] / gap[1] > 1.1 and (best is None or gap[0] / gap[1] > best[1]):
            best = (metric, gap[0] / gap[1])
    return best


def worst_gap(ctx: Ctx) -> tuple[str, float] | None:
    worst: tuple[str, float] | None = None
    for metric in ("calls", "views", "ctr", "directions"):
        gap = peer_gap(ctx, metric)
        if gap and gap[0] / gap[1] < 0.9 and (worst is None or gap[0] / gap[1] < worst[1]):
            worst = (metric, gap[0] / gap[1])
    return worst


def ratio_text(ctx: Ctx, ratio: float) -> str:
    rounded = round(ratio, 1)
    ctx.derive(rounded)
    return f"about {rounded:g}x"


def profile_fix(ctx: Ctx, lift: bool = False) -> tuple[str, str, str]:
    """(framing sentence, ask, deliverable) from the merchant's own signals.

    lift=False: a dip, so the signal is framed as a likely factor. lift=True: things are going well, so the same
    signal is framed as the next lever, never as the cause of the growth.
    """
    lead_en, lead_hi = ("Next lever:", "Agla step:") if lift else ("One likely factor:", "Ek wajah ho sakti hai:")
    if ctx.has_signal("unverified_gbp") or ctx.identity.get("verified") is False:
        return (
            ctx.t(
                f"{lead_en} your Google profile is still unverified.",
                f"{lead_hi} aapka Google profile abhi verified nahi hai.",
            ),
            ctx.t("Want me to start the verification for you today?", "Kya main aaj hi verification shuru kar doon?"),
            "Google profile verification steps",
        )
    stale = next((s for s in ctx.signals if s.startswith("stale_posts")), None)
    if stale:
        return (
            ctx.t(f"{lead_en} your {signal_label(stale)}.", f"{lead_hi} aapka {signal_label(stale)}."),
            ctx.t(
                "Want me to draft a fresh Google post you can approve?",
                "Kya main ek naya Google post draft kar doon jo aap approve kar sakein?",
            ),
            "Google post draft",
        )
    offer = ctx.active_offers[0] if ctx.active_offers else None
    if offer:
        return (
            "",
            ctx.t(
                f"Want me to put your {offer} offer up as a fresh Google post?",
                f"Kya main aapka {offer} offer ek naye Google post mein daal doon?",
            ),
            f"Google post featuring {offer}",
        )
    suggestion = ctx.catalog("@", "free")
    if suggestion:
        return (
            ctx.t(
                "There is no active offer on your profile right now.",
                "Abhi aapke profile par koi active offer nahi hai.",
            ),
            ctx.t(
                f"Want me to set up {suggestion} as a starter offer?",
                f"Kya main {suggestion} ko starter offer ki tarah laga doon?",
            ),
            f"starter offer {suggestion}",
        )
    return (
        "",
        ctx.t("Want me to draft a fresh Google post for you?", "Kya main ek naya Google post draft kar doon?"),
        "Google post draft",
    )


def base_facts(ctx: Ctx) -> list[Any]:
    facts = [F("Business", ctx.business, "merchant", True), F("Locality", ctx.locality, "merchant", True)]
    for offer in ctx.active_offers:
        facts.append(F("Active offer (theirs)", offer, "merchant", True))
    return facts


def plan(
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
    return Plan(
        family=family,
        cta=cta,
        lines=lines,
        ask=ask,
        facts=facts + base_facts(ctx),
        levers=levers,
        primary=primary,
        deliverable=deliverable,
        notes=notes or [],
    )


def source_of(item: dict[str, Any]) -> str:
    return str(item.get("source") or "this week's digest")


# --- knowledge family -------------------------------------------------------------------------------
@handles("research_digest")
def research_digest(ctx: Ctx) -> Plan | Skip:
    item = ctx.digest_item(ctx.payload.get("top_item_id")) or ctx.pick_digest(["research", "tech", "trend"])
    if not item:
        return Skip(reason="no_hook:no_digest_item")
    src, title = source_of(item), str(item.get("title") or "")
    lines = [ctx.t(f"One item from {src} worth your time: {title}.", f"{src} mein ek kaam ki cheez aayi hai: {title}.")]
    facts = [F("Digest item", title), F("Source", src), F("Summary", item.get("summary", ""))]
    if item.get("trial_n"):
        facts.append(F("Trial size", f"{fmt_int(item['trial_n'])} patients"))
    cohort = ctx.agg.get("high_risk_adult_count")
    if item.get("patient_segment") == "high_risk_adults" and cohort:
        lines.append(
            ctx.t(
                f"It applies to your {cohort} high-risk adult patients.",
                f"Yeh aapke {cohort} high-risk adult patients par seedha laagu hota hai.",
            )
        )
        facts.append(F("High-risk adult patients on roster", cohort, "merchant"))
    else:
        lines.append(first_sentence(item.get("summary")))
    ask = ctx.t(
        f"Want me to turn it into a short WhatsApp note for your {ctx.people}?",
        f"Kya main isse aapke {ctx.people} ke liye ek short WhatsApp note bana doon?",
    )
    return plan(
        ctx,
        "knowledge",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["specificity + citation", "reciprocity", "effort externalisation"],
        f"digest item: {title}",
        deliverable=f"{ctx.people} WhatsApp note from: {item.get('summary', title)}",
    )


@handles("regulation_change")
def regulation_change(ctx: Ctx) -> Plan | Skip:
    item = ctx.digest_item(ctx.payload.get("top_item_id")) or ctx.pick_digest(["compliance"])
    if not item:
        return Skip(reason="no_hook:no_compliance_item")
    src, title = pretty_dates(source_of(item)), pretty_dates(str(item.get("title") or ""))
    deadline = fmt_date(ctx.payload.get("deadline_iso") or item.get("date"), with_year=True)
    topic = re.split(r"\s+(?:effective|from|w\.e\.f\.?|starting)\b", title, maxsplit=1)[0].strip().rstrip(".,")
    when_line = ctx.t(f", effective {deadline}", f", {deadline} se laagu") if deadline else ""
    lines = [ctx.t(f"{src}: {topic}{when_line}.", f"{src}: {topic}{when_line}."), first_sentence(item.get("summary"))]
    rest = sentences(item.get("summary"))
    if len(rest) > 1:
        lines.append(pretty_dates(rest[1]))
    when = f" before {deadline}" if deadline else ""
    ask = ctx.t(
        f"Want a 1-page checklist to confirm your setup{when}?",
        f"Kya main{(' ' + deadline + ' se pehle') if deadline else ''} setup check karne ke liye "
        f"1-page checklist bana doon?",
    )
    facts = [
        F("Rule", title),
        F("Source", src),
        F("Details", item.get("summary", "")),
        F("Effective date", deadline or "not stated"),
        F("What to do", item.get("actionable", "")),
    ]
    return plan(
        ctx,
        "knowledge",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["loss aversion (deadline)", "specificity + citation", "effort externalisation"],
        f"rule: {title}",
        deliverable=f"compliance checklist: {item.get('actionable', '')}",
        notes=["calm, clinical; quote dates as dates"],
    )


@handles("cde_opportunity")
def cde_opportunity(ctx: Ctx) -> Plan | Skip:
    item = ctx.digest_item(ctx.payload.get("digest_item_id")) or ctx.pick_digest(["cde"])
    if not item:
        return Skip(reason="no_hook:no_cde_item")
    title, src = str(item.get("title") or ""), source_of(item)
    when = ", ".join(x for x in (fmt_date(item.get("date")), fmt_time(item.get("date"))) if x)
    credits = ctx.payload.get("credits") or item.get("credits")
    credit_txt = f", worth {credits} CDE credits" if credits else ""
    lines = [
        ctx.t(
            f"{title} ({src}) is on {when}{credit_txt}.",
            f"{title} ({src}) {when} ko hai{credit_txt.replace('worth', 'aur isse milenge')}.",
        ),
        first_sentence(item.get("summary")),
    ]
    if item.get("actionable"):
        lines.append(str(item["actionable"]).rstrip(".") + ".")
    ask = ctx.t("Shall I send you a reminder the day before?", "Kya main ek din pehle reminder bhej doon?")
    facts = [
        F("Event", title),
        F("Organiser", src),
        F("When", when),
        F("Credits", credits or "not stated"),
        F("Fee", item.get("actionable", "")),
        F("About", item.get("summary", "")),
    ]
    return plan(
        ctx,
        "knowledge",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["curiosity", "specificity"],
        f"CDE event: {title}",
        deliverable=f"event summary: {title}, {when}{credit_txt}",
    )


@handles("supply_alert")
def supply_alert(ctx: Ctx) -> Plan | Skip:
    if ctx.slug != "pharmacies":
        return Skip(reason="mismatch:supply_alert_outside_pharmacies")
    p = ctx.payload
    molecule, batches = p.get("molecule"), [str(b) for b in p.get("affected_batches") or []]
    if not molecule or not batches:
        return Skip(reason="no_hook:thin_supply_alert")
    item = ctx.digest_item(p.get("alert_id")) or ctx.pick_digest(["alert"])
    src = source_of(item) if item else "a regulator alert"
    maker = f" by {p['manufacturer']}" if p.get("manufacturer") else ""
    batch_txt = ctx.t(" and ", " aur ").join(batches)
    lines = [
        ctx.t(
            f"Urgent: voluntary recall on {molecule} batches {batch_txt}{maker} ({src}).",
            f"Urgent: {molecule} ke batches {batch_txt}{maker} par voluntary recall aaya hai ({src}).",
        )
    ]
    parts = sentences(item.get("summary")) if item else []
    if len(parts) > 1:
        lines.append(parts[1])
    rx = ctx.agg.get("chronic_rx_count")
    if rx:
        lines.append(
            ctx.t(
                f"Worth checking your {rx} chronic-Rx customers against these batches.",
                f"Aapke {rx} chronic-Rx customers ko in batches ke against check karna chahiye.",
            )
        )
    ask = ctx.t(
        "Want me to draft the customer WhatsApp and the replacement steps?",
        "Kya main customer WhatsApp aur replacement steps draft kar doon?",
    )
    facts = [
        F("Molecule", molecule, visible=True),
        F("Batches", batch_txt, visible=True),
        F("Manufacturer", p.get("manufacturer", "")),
        F("Source", src),
        F("Alert details", item.get("summary", "") if item else ""),
        F("Chronic-Rx customers", rx or "n/a"),
    ]
    return plan(
        ctx,
        "knowledge",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["urgency + specificity", "bounded risk", "effort externalisation"],
        f"recall: {molecule}",
        deliverable=f"customer note for {molecule} batches {batch_txt} + replacement steps",
        notes=["manufacturer as in the trigger, never the digest's wording", "no alarm"],
    )


def parse_trend(token: str) -> str | None:
    m = re.match(r"^(.*?)_demand_([+-]?\d+)$", token)
    if not m:
        return None
    name = m.group(1).replace("_", "-")
    name = {"antifungal": "anti-fungal", "cold-cough": "cold-cough"}.get(name, name)
    value = m.group(2)
    return f"{name} {value if value[0] in '+-' else '+' + value}%"


@handles("category_seasonal")
def category_seasonal(ctx: Ctx) -> Plan | Skip:
    trends = [t for t in (parse_trend(str(x)) for x in ctx.payload.get("trends") or []) if t]
    item = ctx.pick_digest(["seasonal"])
    if not trends and not item:
        return Skip(reason="no_hook:no_seasonal_signal")
    lines = []
    if trends:
        joined = ", ".join(trends[:4])
        lines.append(
            ctx.t(
                f"The seasonal demand shift has started: {joined}.",
                f"Seasonal demand shift shuru ho gaya hai: {joined}.",
            )
        )
    elif item:
        lines.append(f"{item.get('title')}.")
    if item and item.get("actionable"):
        lines.append(
            ctx.t(
                f"Easiest move this week: {item['actionable']}.",
                f"Is hafte ka sabse aasaan kaam: {item['actionable']}.",
            )
        )
    delivery = next((o for o in ctx.active_offers if "deliver" in o.lower()), None)
    tail = f", with your {delivery} offer" if delivery else ""
    ask = ctx.t(
        f"Want me to draft a short customer note about it{tail}?",
        f"Kya main iske baare mein customers ke liye ek short note draft kar doon{tail.replace('with your', 'aapke')}"
        f"{' ke saath' if delivery else ''}?",
    )
    facts = [
        F("Demand shifts", ", ".join(trends) or "n/a", visible=True),
        F("Seasonal item", item.get("summary", "") if item else ""),
        F("Recommended action", item.get("actionable", "") if item else ""),
    ]
    return plan(
        ctx,
        "knowledge",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["timing", "specificity", "effort externalisation"],
        "seasonal demand numbers",
        deliverable="seasonal customer note",
    )


# --- performance family -------------------------------------------------------------------------------
def delta_line(ctx: Ctx, metric: str, delta: float, window: str, baseline: Any = None) -> str:
    en_w, hi_w = WINDOW.get(window, WINDOW["7d"])
    direction_en, direction_hi = ("down", "kam") if delta < 0 else ("up", "zyada")
    base_en = f" against a baseline of {baseline}" if baseline not in (None, "") else ""
    base_hi = f" (baseline {baseline})" if baseline not in (None, "") else ""
    name = METRIC.get(metric, humanize(metric))
    return ctx.t(
        f"Your {name} are {direction_en} {fmt_pct(delta)} {en_w}{base_en}.",
        f"{hi_w.capitalize()} aapke {name} {fmt_pct(delta)} {direction_hi} hue hain{base_hi}.",
    )


@handles("perf_dip")
def perf_dip(ctx: Ctx) -> Plan | Skip:
    p, facts = ctx.payload, []
    if not ctx.placeholder and isinstance(p.get("delta_pct"), int | float):
        metric = str(p.get("metric") or "calls")
        lines = [delta_line(ctx, metric, float(p["delta_pct"]), str(p.get("window") or "7d"), p.get("vs_baseline"))]
        facts.append(F(f"{METRIC.get(metric, metric)} change", fmt_pct(p["delta_pct"], signed=True), visible=True))
        primary = f"{metric} {fmt_pct(p['delta_pct'], signed=True)}"
    else:
        negatives = sorted((v, k) for k, v in ctx.deltas.items() if v < 0 and k in DELTA_KEY)
        if negatives:
            delta, key = negatives[0]
            metric = DELTA_KEY[key]
            lines = [delta_line(ctx, metric, delta, "7d")]
            primary = f"{metric} {fmt_pct(delta, signed=True)} (7d)"
            facts.append(F(f"{METRIC[metric]} change this week", fmt_pct(delta, signed=True), "merchant", True))
        else:
            gap = worst_gap(ctx)
            if not gap:
                return Skip(reason="no_hook:nothing_lagging")
            metric = gap[0]
            phrase = peer_phrase(ctx, metric) or ""
            lines = [
                ctx.t(f"One number is lagging: {phrase} over 30 days.", f"Ek number peeche hai: 30 din mein {phrase}.")
            ]
            primary = f"{metric} below peer average"
            facts.append(F("Gap to peers", phrase, "derived"))
    factor, ask, deliverable = profile_fix(ctx)
    lines.append(factor)
    facts.append(F("Profile signals", "; ".join(signal_label(s) for s in ctx.signals) or "none", "merchant", True))
    return plan(
        ctx,
        "performance",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["loss aversion", "specificity", "effort externalisation"],
        primary,
        deliverable,
        notes=["state the likely factor as a possibility, not a diagnosis"],
    )


@handles("perf_spike")
def perf_spike(ctx: Ctx) -> Plan | Skip:
    p, facts = ctx.payload, []
    if not ctx.placeholder and isinstance(p.get("delta_pct"), int | float):
        metric = str(p.get("metric") or "calls")
        line = delta_line(ctx, metric, float(p["delta_pct"]), str(p.get("window") or "7d"), p.get("vs_baseline"))
        driver = p.get("likely_driver")
        if driver:
            d = humanize(str(driver))
            line = line.rstrip(".") + ctx.t(
                f", and the lift lines up with your {d}.", f", aur yeh aapke {d} ke baad aaya hai."
            )
        lines, primary = [line], f"{metric} {fmt_pct(p['delta_pct'], signed=True)}"
        facts.append(F(f"{METRIC.get(metric, metric)} change", fmt_pct(p["delta_pct"], signed=True), visible=True))
    else:
        positives = sorted(((v, k) for k, v in ctx.deltas.items() if v > 0 and k in DELTA_KEY), reverse=True)
        if positives:
            delta, key = positives[0]
            metric = DELTA_KEY[key]
            if delta < 0.10:
                name = METRIC[metric]
                lines = [
                    ctx.t(
                        f"Your {name} are rising steadily: {fmt_pct(delta, signed=True)} this week.",
                        f"Aapke {name} dheere dheere badh rahe hain: is hafte {fmt_pct(delta, signed=True)}.",
                    )
                ]
            else:
                lines = [delta_line(ctx, metric, delta, "7d")]
            primary = f"{metric} {fmt_pct(delta, signed=True)} (7d)"
            facts.append(F(f"{METRIC[metric]} change this week", fmt_pct(delta, signed=True), "merchant", True))
        else:
            lead = best_lead(ctx)
            if not lead:
                return Skip(reason="no_hook:no_positive_metric")
            metric = lead[0]
            lines = [
                ctx.t(
                    f"A strength worth using: {peer_phrase(ctx, metric)}, {ratio_text(ctx, lead[1])}.",
                    f"Ek strength: {peer_phrase(ctx, metric)}, {ratio_text(ctx, lead[1])}.",
                )
            ]
            primary = f"{metric} above peer average"
    offer = ctx.active_offers[0] if ctx.active_offers else None
    if offer:
        lines.append(
            ctx.t(
                f"Your {offer} offer is the natural next step for those enquiries.",
                f"Aapka {offer} offer in enquiries ke liye sahi agla step hai.",
            )
        )
        ask = ctx.t(
            "Want me to draft a 3-line reply you can send everyone who enquires this week?",
            "Kya main ek 3-line reply draft kar doon jo aap is hafte har enquiry ko bhej sakein?",
        )
        deliverable = f"3-line enquiry reply featuring {offer}"
    else:
        factor, ask, deliverable = profile_fix(ctx, lift=True)
        lines.append(factor)
    return plan(
        ctx,
        "performance",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["curiosity", "timing", "effort externalisation"],
        primary,
        deliverable,
    )


@handles("seasonal_perf_dip")
def seasonal_perf_dip(ctx: Ctx) -> Plan | Skip:
    p = ctx.payload
    if p.get("is_expected_seasonal") is False:
        return perf_dip(ctx)
    if ctx.placeholder or not isinstance(p.get("delta_pct"), int | float):
        return perf_dip(ctx)
    metric = str(p.get("metric") or "views")
    beat = ctx.beat("lowest", "retention", "acquisition", "lull", "slow")
    lines = [delta_line(ctx, metric, float(p["delta_pct"]), str(p.get("window") or "7d"))]
    if beat:
        lines.append(
            ctx.t(
                f"That matches the usual {beat['month_range']} pattern: {beat['note']}.",
                f"Yeh har saal ka {beat['month_range']} pattern hai: {beat['note']}.",
            )
        )
    members, churn, peer_churn = (
        ctx.agg.get("total_active_members"),
        ctx.agg.get("monthly_churn_pct"),
        ctx.peer.get("monthly_churn_pct"),
    )
    if members and isinstance(churn, float) and isinstance(peer_churn, float):
        lines.append(
            ctx.t(
                f"With {members} active members and monthly churn at {fmt_pct(churn)} vs the "
                f"{fmt_pct(peer_churn)} metro average, retention is where effort pays right now.",
                f"{members} active members aur churn {fmt_pct(churn)} (metro average {fmt_pct(peer_churn)}), "
                "toh abhi retention par focus sabse zyada kaam aayega.",
            )
        )
    ask = ctx.t(
        "Want me to draft a member check-in message to keep attendance up through the dip?",
        "Kya main members ke liye ek check-in message draft kar doon taaki attendance bani rahe?",
    )
    facts = [
        F(f"{METRIC.get(metric, metric)} change", fmt_pct(p["delta_pct"], signed=True), visible=True),
        F("Seasonal note", beat["note"] if beat else "n/a", "category"),
        F("Active members", members or "n/a", "merchant"),
        F("Monthly churn", fmt_pct(churn) if churn else "n/a"),
    ]
    return plan(
        ctx,
        "performance",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["reassurance + judgment", "specificity", "effort externalisation"],
        "seasonal dip",
        deliverable="member check-in message",
    )


@handles("milestone_reached")
def milestone_reached(ctx: Ctx) -> Plan | Skip:
    p = ctx.payload
    pos = ctx.top_theme("pos")
    if not ctx.placeholder and isinstance(p.get("value_now"), int) and isinstance(p.get("milestone_value"), int):
        now, goal = p["value_now"], p["milestone_value"]
        metric = humanize(str(p.get("metric") or "reviews")).replace("review count", "reviews")
        diff = ctx.derive(goal - now)
        lines = [
            ctx.t(
                f"You're at {now} {metric}, just {diff} away from {goal}.",
                f"Aap {now} {metric} par hain, {goal} se sirf {diff} door.",
            )
        ]
        primary = f"{now} → {goal} {metric}"
        facts = [F("Now", now, visible=True), F("Milestone", goal, visible=True)]
    else:
        lead = best_lead(ctx)
        if lead:
            metric = lead[0]
            lines = [
                ctx.t(
                    f"A number worth showing off: {peer_phrase(ctx, metric)}, {ratio_text(ctx, lead[1])}.",
                    f"Ek number jo dikhana chahiye: {peer_phrase(ctx, metric)}, {ratio_text(ctx, lead[1])}.",
                )
            ]
            primary, facts = f"{metric} lead over peers", [F("Lead over peers", peer_phrase(ctx, metric), "derived")]
        elif pos:
            n, theme_name = pos.get("occurrences_30d"), humanize(pos["theme"])
            lines = [
                ctx.t(
                    f"A number worth showing off: {n} reviews this month praise your {theme_name}.",
                    f"Ek number jo dikhana chahiye: is mahine {n} reviews aapki {theme_name} ki tareef karte hain.",
                )
            ]
            primary, facts = f"{n} positive reviews", [F("Positive reviews", f"{theme_name}, {n}", "merchant")]
            pos = None  # already used as the primary signal
        else:
            return Skip(reason="no_hook:no_positive_number")
    if pos:
        n = pos.get("occurrences_30d")
        lines.append(
            ctx.t(
                f"Customers keep praising your {humanize(pos['theme'])} ({n} mentions this month).",
                f"Customers aapki {humanize(pos['theme'])} ki tareef kar rahe hain (is mahine {n} baar).",
            )
        )
        facts.append(F("Top positive review theme", f"{humanize(pos['theme'])}, {n} mentions", "merchant"))
    ask = ctx.t(
        f"Want me to draft a short review request you can send your regular {ctx.people}?",
        f"Kya main aapke regular {ctx.people} ke liye ek short review request draft kar doon?",
    )
    return plan(
        ctx,
        "performance",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["social proof", "momentum", "effort externalisation"],
        primary,
        deliverable="review request message + celebratory Google post",
    )


# --- account family ----------------------------------------------------------------------------------------
@handles("renewal_due")
def renewal_due(ctx: Ctx) -> Plan | Skip:
    p, sub = ctx.payload, ctx.subscription
    days = p.get("days_remaining") if not ctx.placeholder else sub.get("days_remaining")
    plan_name = (p.get("plan") if not ctx.placeholder else None) or sub.get("plan") or "current"
    amount = p.get("renewal_amount") if not ctx.placeholder else None
    facts = [F("Plan", plan_name, visible=True)]
    if sub.get("status") == "expired" and sub.get("days_since_expiry"):
        lines = [
            ctx.t(
                f"Your {plan_name} plan lapsed {sub['days_since_expiry']} days ago, so profile upkeep is paused.",
                f"Aapka {plan_name} plan {sub['days_since_expiry']} din pehle lapse ho gaya, profile upkeep ruka hua hai.",
            )
        ]
        ask = ctx.t("Want me to restart it?", "Kya main ise dobara shuru kar doon?")
        return plan(
            ctx,
            "account",
            "binary_yes_no",
            lines,
            ask,
            facts,
            ["loss aversion", "single binary commitment"],
            "expired plan",
            deliverable="plan reactivation request",
        )
    if not isinstance(days, int):
        return Skip(reason="no_hook:no_renewal_details")
    price = f" ({fmt_money(amount)})" if amount else ""
    lines = [
        ctx.t(
            f"Your {plan_name} plan renews in {days} days{price}.",
            f"Aapka {plan_name} plan {days} din mein renew hona hai{price}.",
        )
    ]
    views = ctx.perf.get("views")
    if isinstance(views, int):
        lines.append(
            ctx.t(
                f"It keeps your profile upkeep running behind the {fmt_int(views)} views you got in the last 30 days.",
                f"Isi se aapke profile ka upkeep chalta hai, jisne pichhle 30 din mein {fmt_int(views)} views laaye.",
            )
        )
    facts += [
        F("Days remaining", days, visible=True),
        F("Renewal amount", fmt_money(amount) if amount else "not stated"),
    ]
    ask = ctx.t(
        "Reply CONFIRM and I'll raise the renewal request.",
        "CONFIRM reply karein aur main renewal request raise kar doongi.",
    )
    return plan(
        ctx,
        "account",
        "binary_confirm_cancel",
        lines,
        ask,
        facts,
        ["loss aversion", "single binary commitment"],
        f"renewal in {days} days",
        deliverable=f"renewal request for {plan_name}{price}",
    )


@handles("winback_eligible")
def winback_eligible(ctx: Ctx) -> Plan | Skip:
    p, sub = ctx.payload, ctx.subscription
    if sub.get("status") == "active":
        return Skip(reason="kind_not_true:subscription_active")
    days = p.get("days_since_expiry") or sub.get("days_since_expiry")
    lapsed = p.get("lapsed_customers_added_since_expiry")
    dip = p.get("perf_dip_pct")
    if not days:
        return Skip(reason="no_hook:no_expiry_details")
    parts_en = [f"since your plan paused {days} days ago"]
    if lapsed:
        parts_en.append(f"{lapsed} more customers have gone quiet")
    line_en = (
        "Since your plan paused "
        + f"{days} days ago"
        + (f", {lapsed} more {ctx.people} have gone quiet" if lapsed else "")
        + (f" and your numbers are down {fmt_pct(dip)}" if isinstance(dip, float) else "")
        + "."
    )
    line_hi = (
        f"Plan ruke {days} din ho gaye"
        + (f", aur {lapsed} {ctx.people} wapas nahi aaye" if lapsed else "")
        + (f"; numbers {fmt_pct(dip)} neeche hain" if isinstance(dip, float) else "")
        + "."
    )
    ask = ctx.t(
        f"Want me to restart with one quick win: a comeback message to those {ctx.people}?",
        f"Kya main ek quick win se shuru karoon: un {ctx.people} ke liye ek comeback message?",
    )
    facts = [
        F("Days since expiry", days, visible=True),
        F("Customers lapsed since expiry", lapsed or "n/a", visible=True),
        F("Performance change", fmt_pct(dip, signed=True) if isinstance(dip, float) else "n/a", visible=True),
    ]
    return plan(
        ctx,
        "account",
        "binary_yes_no",
        [ctx.t(line_en, line_hi)],
        ask,
        facts,
        ["loss aversion", "curiosity", "single binary commitment"],
        "lapsed customers since expiry",
        deliverable="comeback message for lapsed customers + reactivation step",
        notes=["do not repeat the earlier expiry notice wording"],
    )


@handles("dormant_with_vera")
def dormant_with_vera(ctx: Ctx) -> Plan | Skip:
    lapsed_key = next((k for k in ctx.agg if k.startswith("lapsed_") and isinstance(ctx.agg[k], int)), None)
    silent = ctx.payload.get("days_since_last_merchant_message")
    facts = [F("Days since last merchant message", silent or "n/a", visible=True)]
    why_now = (
        [
            ctx.t(
                f"It's been {silent} days since we last heard from you.", f"Aapse pichhli baat ko {silent} din ho gaye."
            )
        ]
        if isinstance(silent, int) and not isinstance(silent, bool)
        else []
    )
    if lapsed_key and ctx.agg[lapsed_key]:
        m = re.search(r"(\d+)d", lapsed_key)
        span = f"{m.group(1)}+ days" if m else "a while"
        if m:
            ctx.derive(int(m.group(1)))
        n, total = ctx.agg[lapsed_key], ctx.agg.get("total_unique_ytd")
        of_en = (
            f"{n} of the {fmt_int(total)} {ctx.people} you've seen this year" if total else f"{n} of your {ctx.people}"
        )
        of_hi = f"is saal aaye aapke {fmt_int(total)} {ctx.people} mein se {n}" if total else f"aapke {n} {ctx.people}"
        lines = [
            ctx.t(
                f"magicpin data shows {of_en} haven't been back in {span}.",
                f"magicpin data ke hisaab se {of_hi}, {span.replace('days', 'din')} se wapas nahi aaye.",
            )
        ]
        ask = ctx.t(
            "What usually brings them back for you: a seasonal offer or a simple reminder?",
            "Aapke yahan unhe wapas kya laata hai: koi seasonal offer ya ek simple reminder?",
        )
        primary = f"{n} lapsed {ctx.people}"
        facts.append(F("Lapsed customers", f"{n} ({span})", "merchant"))
    else:
        negatives = sorted((v, k) for k, v in ctx.deltas.items() if v < 0 and k in DELTA_KEY)
        if negatives:
            delta, key = negatives[0]
            lines = [delta_line(ctx, DELTA_KEY[key], delta, "7d")]
            ask = ctx.t(
                "Has anything changed on your side lately, like timings, menu or staff?",
                "Kya aapki taraf kuch badla hai, jaise timings, menu ya staff?",
            )
            primary = f"{DELTA_KEY[key]} {fmt_pct(delta, signed=True)}"
            facts.append(F("Change this week", fmt_pct(delta, signed=True), "merchant", True))
        else:
            views, calls = ctx.perf.get("views"), ctx.perf.get("calls")
            if not isinstance(views, int):
                return Skip(reason="no_hook:dormant_without_numbers")
            lines = [
                ctx.t(
                    f"Your profile had {fmt_int(views)} views and {calls} calls in the last 30 days.",
                    f"Pichhle 30 din mein aapke profile par {fmt_int(views)} views aur {calls} calls aaye.",
                )
            ]
            ask = ctx.t(
                "What's the one thing you'd like more of this month: calls, walk-ins or orders?",
                "Is mahine aapko kis cheez ki sabse zyada zarurat hai: calls, walk-ins ya orders?",
            )
            primary = "30-day views and calls"
    return plan(
        ctx,
        "account",
        "open_ended",
        why_now + lines,
        ask,
        facts,
        ["reciprocity", "asking the merchant", "curiosity"],
        primary,
        deliverable="next step based on the merchant's answer",
        notes=["no renewal pitch; ask, don't sell"],
    )


@handles("gbp_unverified")
def gbp_unverified(ctx: Ctx) -> Plan | Skip:
    if ctx.identity.get("verified") is True:
        return Skip(reason="kind_not_true:verified")
    p = ctx.payload
    uplift = p.get("estimated_uplift_pct")
    raw_path = humanize(str(p.get("verification_path") or ""))
    path = ctx.t(raw_path.replace(" or ", " or a ").replace("postcard", "a postcard"), raw_path.replace(" or ", " ya "))
    lines = [
        ctx.t(
            "Your Google profile is still unverified"
            + (
                f", and magicpin estimates about {fmt_pct(uplift)} more visibility once it is."
                if isinstance(uplift, float)
                else "."
            ),
            "Aapka Google profile abhi verified nahi hai"
            + (
                f"; magicpin ke estimate se verify hone par lagbhag {fmt_pct(uplift)} zyada visibility milti hai."
                if isinstance(uplift, float)
                else "."
            ),
        )
    ]
    views, calls = ctx.perf.get("views"), ctx.perf.get("calls")
    if isinstance(views, int) and isinstance(calls, int):
        lines.append(
            ctx.t(
                f"That would build on the {fmt_int(views)} views and {calls} calls you get now.",
                f"Yeh aapke abhi ke {fmt_int(views)} views aur {calls} calls ke upar hoga.",
            )
        )
    how = f" through {path}" if path else ""
    ask = ctx.t(
        f"Want me to start the verification{how} for you?",
        f"Kya main {path + ' se ' if path else ''}verification shuru kar doon?",
    )
    facts = [
        F("Verified", "no", visible=True),
        F("Verification path", path or "n/a"),
        F("Estimated uplift (magicpin)", fmt_pct(uplift) if isinstance(uplift, float) else "n/a"),
    ]
    return plan(
        ctx,
        "account",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["loss aversion", "effort externalisation"],
        "unverified profile",
        deliverable=f"verification steps{how}",
    )


# --- moment family -------------------------------------------------------------------------------------
FESTIVE_WORDS = {
    "salons": ("bridal", "spa", "facial", "keratin"),
    "dentists": ("whitening", "smile"),
    "restaurants": ("family", "combo", "brunch", "starter", "cake"),
    "gyms": ("couple", "family", "combo", "annual"),
    "pharmacies": ("health card", "diabetic", "check"),
}


def festive_offer(ctx: Ctx) -> tuple[str | None, bool]:
    words = FESTIVE_WORDS.get(ctx.slug, ())
    theirs = next((o for o in ctx.active_offers if any(w in o.lower() for w in words)), None)
    if theirs:
        return theirs, True
    suggestion = ctx.catalog(*words) if words else None
    if suggestion:
        return suggestion, False
    return (ctx.active_offers[0], True) if ctx.active_offers else (None, False)


@handles("festival_upcoming")
def festival_upcoming(ctx: Ctx) -> Plan | Skip:
    p = ctx.payload
    festival, day = p.get("festival"), fmt_date(p.get("date"))
    parsed = parse_iso(p.get("date"))
    beat = ctx.beat("festival", "wedding", "diwali", month=parsed.month if parsed else None)
    offer, theirs = festive_offer(ctx)
    if festival and day:
        line = ctx.t(f"{festival} is on {day}", f"{festival} {day} ko hai")
        if beat:
            line += ctx.t(
                f", inside your {beat['month_range']} peak ({beat['note']}).",
                f", aapke {beat['month_range']} peak ke beech ({beat['note']}).",
            )
        else:
            line += "."
        lines, primary = [line], f"{festival} on {day}"
    elif beat:
        lines = [
            ctx.t(
                f"Your busiest stretch is coming: {beat['month_range']}, {beat['note']}.",
                f"Aapka sabse busy season aa raha hai: {beat['month_range']}, {beat['note']}.",
            )
        ]
        primary = f"season {beat['month_range']}"
    else:
        return Skip(reason="no_hook:no_festival_or_beat")
    if offer and theirs:
        ask = ctx.t(
            f"Want me to draft a festive post around your {offer} offer so it's live early?",
            f"Kya main aapke {offer} offer ke saath ek festive post draft kar doon taaki woh jaldi live ho?",
        )
    elif offer:
        ask = ctx.t(
            f"Want me to set up {offer} as a festive offer and draft the post?",
            f"Kya main {offer} ko festive offer ki tarah set karke post draft kar doon?",
        )
    else:
        ask = ctx.t("Want me to draft a festive post so it's live early?", "Kya main ek festive post draft kar doon?")
    facts = [
        F("Festival", festival or "n/a", visible=True),
        F("Date", day or "n/a", visible=True),
        F("Season note", f"{beat['month_range']}: {beat['note']}" if beat else "n/a", "category"),
        F("Offer to feature", f"{offer} ({'theirs' if theirs else 'catalog suggestion'})" if offer else "none"),
    ]
    return plan(
        ctx,
        "moment",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["timing", "effort externalisation"],
        primary,
        deliverable=f"festive Google post + WhatsApp broadcast featuring {offer or 'the festival'}",
        notes=["quote the date, never 'N days until'"],
    )


@handles("ipl_match_today")
def ipl_match_today(ctx: Ctx) -> Plan | Skip:
    if ctx.slug != "restaurants":
        return Skip(reason="mismatch:ipl_outside_restaurants")
    p = ctx.payload
    match, venue, when = p.get("match"), p.get("venue"), fmt_time(p.get("match_time_iso"))
    if not match:
        return Skip(reason="no_hook:thin_ipl")
    day = weekday(p.get("match_time_iso"))
    lines = [ctx.t(f"{match} at {venue} tonight, {when}.", f"Aaj raat {when} par {venue} mein {match} hai.")]
    item = next(
        (d for d in ctx.digest if "ipl" in str(d.get("title", "")).lower() or "ipl" in str(d.get("id", ""))), None
    )
    weekend = p.get("is_weeknight") is False
    if item and weekend:
        evidence = " ".join(sentences(item.get("summary"))[:2]) or str(item.get("title") or "")
        lines.append(f"{source_of(item)}: {evidence}")
        lines.append(
            ctx.t(
                "So a dine-in match promo tonight is likely to underperform.",
                "Toh aaj raat dine-in match promo se zyada fayda nahi hoga.",
            )
        )
    delivery, dine_in = ctx.agg.get("delivery_orders_30d"), ctx.agg.get("dine_in_orders_30d")
    offer = ctx.active_offers[0] if ctx.active_offers else None
    if offer and day and weekend and "tue" in offer.lower():  # the merchant's own offer is the sharper point
        lines.append(
            ctx.t(
                f"Your {offer} doesn't cover a {day}, so keep it for the weeknights.",
                f"Aapka {offer} {day} ko valid nahi hai, use weeknights ke liye rakhiye.",
            )
        )
    elif isinstance(delivery, int) and isinstance(dine_in, int) and delivery + dine_in:
        share = ctx.derive(round(100 * delivery / (delivery + dine_in)))
        lines.append(
            ctx.t(
                f"Delivery already brings {share}% of your orders ({delivery} delivery vs {dine_in} dine-in in 30 days).",
                f"Delivery pehle se aapke {share}% orders laati hai (30 din mein {delivery} delivery vs {dine_in} dine-in).",
            )
        )
    ask = ctx.t(
        "Want me to draft a delivery-night post for tonight instead?",
        "Kya main aaj raat ke liye ek delivery-night post draft kar doon?",
    )
    facts = [
        F("Match", match, visible=True),
        F("Venue", venue, visible=True),
        F("Time", when, visible=True),
        F("Weeknight", "no" if weekend else "yes", visible=True),
        F("IPL insight", item.get("summary", "") if item else "n/a", "category"),
        F("Delivery vs dine-in (30d)", f"{delivery} vs {dine_in}" if delivery else "n/a", "merchant"),
    ]
    return plan(
        ctx,
        "moment",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["judgment", "loss aversion", "effort externalisation"],
        f"{match} tonight",
        deliverable="delivery-night post for the match",
        notes=["advise against a dine-in promo on a weekend match night"],
    )


@handles("competitor_opened")
def competitor_opened(ctx: Ctx) -> Plan | Skip:
    p, pos = ctx.payload, ctx.top_theme("pos")
    facts = []
    if not ctx.placeholder and p.get("competitor_name"):
        opened = fmt_date(p.get("opened_date"))
        line = ctx.t(
            f"{p['competitor_name']} opened {p.get('distance_km')} km away"
            + (f" on {opened}" if opened else "")
            + (f", advertising {p['their_offer']}." if p.get("their_offer") else "."),
            f"{p['competitor_name']} {p.get('distance_km')} km door khula hai"
            + (f" ({opened})" if opened else "")
            + (f", aur woh {p['their_offer']} de rahe hain." if p.get("their_offer") else "."),
        )
        lines, primary = [line], f"competitor {p['competitor_name']}"
        facts += [
            F("Competitor", p["competitor_name"], visible=True),
            F("Distance", f"{p.get('distance_km')} km", visible=True),
            F("Their offer", p.get("their_offer", "n/a"), visible=True),
        ]
    else:
        lines = [
            ctx.t(
                f"A new listing in your category has come up near {ctx.locality}.",
                f"{ctx.locality} ke paas aapki category mein ek nayi listing aayi hai.",
            )
        ]
        primary = "new nearby listing (unnamed)"
    if pos and pos.get("common_quote"):
        lines.append(
            ctx.t(
                f"Matching on price isn't the move: {pos.get('occurrences_30d')} reviews this month say "
                f'"{pos["common_quote"]}", and that is hard to copy.',
                f"Price match karna zaroori nahi: is mahine {pos.get('occurrences_30d')} reviews kehte hain "
                f'"{pos["common_quote"]}", yeh copy karna mushkil hai.',
            )
        )
        facts.append(
            F("Strength from reviews", f"{pos['common_quote']} ({pos.get('occurrences_30d')} mentions)", "merchant")
        )
    elif pos:
        lines.append(
            ctx.t(
                f"Your edge is {humanize(pos['theme'])}: {pos.get('occurrences_30d')} positive mentions this month.",
                f"Aapki strength {humanize(pos['theme'])} hai: is mahine {pos.get('occurrences_30d')} positive mentions.",
            )
        )
    else:
        views = ctx.perf.get("views")
        if isinstance(views, int):
            lines.append(
                ctx.t(
                    f"You start ahead with {fmt_int(views)} profile views in the last 30 days.",
                    f"Aap {fmt_int(views)} profile views (30 din) ke saath aage hain.",
                )
            )
    ask = ctx.t(
        "Want me to update your Google description to lead with that strength?",
        "Kya main aapka Google description us strength ke saath update kar doon?",
    )
    return plan(
        ctx,
        "moment",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["curiosity", "loss aversion", "judgment"],
        primary,
        deliverable="Google description/post leading with the merchant's strength",
        notes=["never disparage the competitor", "never name a competitor that is not in the payload"],
    )


# --- reputation family --------------------------------------------------------------------------------------
@handles("review_theme_emerged")
def review_theme_emerged(ctx: Ctx) -> Plan | Skip:
    p = ctx.payload
    theme = None if ctx.placeholder else p
    if not theme or not theme.get("theme"):
        theme = ctx.top_theme("neg")
    if not theme:
        ask = ctx.t(
            "What's the one thing customers mention most in your reviews lately, so I can draft replies you can reuse?",
            "Customers aajkal sabse zyada kis baat ka zikr kar rahe hain, taaki main reuse karne layak replies bana doon?",
        )
        lead = ctx.t("One quick thing on your Google reviews.", "Aapke Google reviews ke baare mein ek chhoti baat.")
        return plan(
            ctx,
            "reputation",
            "open_ended",
            [lead],
            ask,
            [],
            ["asking the merchant", "reciprocity"],
            "ask about review themes",
            deliverable="reusable review replies",
        )
    name, n, quote = humanize(str(theme["theme"])), theme.get("occurrences_30d"), theme.get("common_quote")
    trend = f", and the count is {theme['trend']}" if theme.get("trend") else ""
    line = ctx.t(
        f"{n} reviews in the last 30 days mention {name}{trend}" + (f'; one says "{quote}".' if quote else "."),
        f"Pichhle 30 din mein {n} reviews ne {name} ki baat ki hai" + (f'; ek ne likha "{quote}".' if quote else "."),
    )
    lines = [line]
    pos = ctx.top_theme("pos")
    if pos and pos.get("theme") != theme.get("theme"):
        lines.append(
            ctx.t(
                f"On the bright side, {pos.get('occurrences_30d')} reviews praise your {humanize(pos['theme'])}, "
                "so the core product isn't the problem.",
                f"Achhi baat: {pos.get('occurrences_30d')} reviews aapki {humanize(pos['theme'])} ki tareef karte hain, "
                "toh asli product mein dikkat nahi hai.",
            )
        )
    ask = ctx.t(
        f"Want me to draft short, polite replies to those {n} reviews?",
        f"Kya main un {n} reviews ke liye short, polite replies draft kar doon?",
    )
    facts = [
        F("Theme", name, visible=True),
        F("Mentions (30d)", n, visible=True),
        F("Quote", quote or "n/a", visible=True),
        F("Positive theme", f"{humanize(pos['theme'])} ({pos.get('occurrences_30d')})" if pos else "n/a", "merchant"),
    ]
    return plan(
        ctx,
        "reputation",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["specificity (count + quote)", "judgment", "effort externalisation"],
        f"{n} reviews on {name}",
        deliverable=f"review replies addressing {name}",
    )


# --- conversation family ------------------------------------------------------------------------------------
@handles("curious_ask_due")
def curious_ask_due(ctx: Ctx) -> Plan | Skip:
    offers = ctx.active_offers
    lines = [
        ctx.t(
            "I'll turn your answer into this week's Google post and a ready reply for price questions.",
            "Aapke jawab se main is hafte ka Google post aur price questions ke liye ek ready reply bana doongi.",
        )
    ]
    if len(offers) >= 2:
        ask = ctx.t(
            f"Which is getting asked about more this week: {offers[0]} or {offers[1]}?",
            f"Is hafte kiske baare mein zyada log pooch rahe hain: {offers[0]} ya {offers[1]}?",
        )
    elif offers:
        ask = ctx.t(
            f"Is {offers[0]} still what people ask about most, or is something else picking up this week?",
            f"Kya log ab bhi sabse zyada {offers[0]} ke baare mein poochte hain, ya is hafte kuch aur chal raha hai?",
        )
    else:
        ask = ctx.t(
            "Which service are people asking about most this week?",
            "Is hafte log sabse zyada kis service ke baare mein pooch rahe hain?",
        )
    return plan(
        ctx,
        "conversation",
        "open_ended",
        lines,
        ask,
        [],
        ["asking the merchant", "reciprocity", "curiosity"],
        "weekly curious ask",
        deliverable="Google post + price-question reply from the merchant's answer",
    )


def numbers_sentence(text: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\d", sentence) and "?" not in sentence:
            return sentence.strip().rstrip(".")
    return None


@handles("active_planning_intent")
def active_planning_intent(ctx: Ctx) -> Plan | Skip:
    topic = humanize(str(ctx.payload.get("intent_topic") or ""))
    if not topic:
        return Skip(reason="no_hook:no_intent_topic")
    proposal = ctx.last_vera_proposal() or ""
    anchor = numbers_sentence(proposal)
    if anchor:
        anchor = re.sub(r"^(?:suggest|suggested|maybe|how about)\s+", "", anchor, flags=re.IGNORECASE)
        anchor = anchor[0].lower() + anchor[1:] if anchor[:1].isupper() and not anchor[:2].isupper() else anchor
    offer = ctx.active_offers[0] if ctx.active_offers else None
    if ctx.slug == "restaurants":
        draft = (
            f"{topic.capitalize()}, first draft: base it on your {offer}"
            if offer
            else f"{topic.capitalize()}, first draft"
        )
        draft += (
            "; bulk rate for 10+ plates ₹___ (your call); orders by the previous evening; one lunch delivery window."
        )
    else:
        draft = (
            f"{topic.capitalize()}, first draft: "
            + (f"{anchor}; " if anchor else "")
            + "batch timings ___; "
            + (f"intro offer {offer}." if offer else "intro price ₹___.")
        )
    lines = [
        ctx.t("Here's the draft, with the blanks for you to fill.", "Yeh raha draft, blanks aap bhar dijiye."),
        draft,
    ]
    if anchor and ctx.slug == "restaurants":
        lines.append(ctx.t(f"For reference: {anchor}.", f"Reference ke liye: {anchor}."))
    ask = ctx.t(
        "Reply CONFIRM with the blanks filled and I'll turn it into a Google post and a WhatsApp message.",
        "Blanks bhar ke CONFIRM reply karein, main ise Google post aur WhatsApp message bana doongi.",
    )
    facts = [
        F("Topic", topic, visible=True),
        F("Merchant said", ctx.payload.get("merchant_last_message", ""), visible=True),
        F("Earlier Vera proposal", proposal or "n/a", "merchant"),
    ]
    return plan(
        ctx,
        "conversation",
        "binary_confirm_cancel",
        lines,
        ask,
        facts,
        ["effort externalisation", "momentum", "single confirm"],
        f"planning: {topic}",
        deliverable=f"publish-ready {topic}",
        notes=["deliver the draft now; no qualifying question", "unknown numbers stay as ___ blanks"],
    )


# --- generic handler ----------------------------------------------------------------------------------------
@handles("__generic__")
def generic(ctx: Ctx) -> Plan | Skip:
    scalars = [
        (k, v)
        for k, v in ctx.payload.items()
        if k != "placeholder"
        and isinstance(v, str | int | float)
        and not isinstance(v, bool)
        and not str(k).endswith("_id")
    ]
    facts = [F(humanize(k), v, visible=True) for k, v in scalars[:4]]
    if scalars and not ctx.placeholder:
        key, value = scalars[0]
        shown = fmt_date(value) or value
        lines = [ctx.t(f"Heads-up: {humanize(key)} is now {shown}.", f"Ek update: {humanize(key)} ab {shown} hai.")]
    else:
        views, calls = ctx.perf.get("views"), ctx.perf.get("calls")
        if not isinstance(views, int):
            return Skip(reason="no_hook:generic_without_numbers")
        lines = [
            ctx.t(
                f"Your profile had {fmt_int(views)} views and {calls} calls in the last 30 days.",
                f"Pichhle 30 din mein aapke profile par {fmt_int(views)} views aur {calls} calls aaye.",
            )
        ]
    ask = ctx.t(
        "Want a quick idea to turn more of that into bookings?",
        "Kya main isse zyada bookings mein badalne ka ek quick idea bhejoon?",
    )
    return plan(
        ctx,
        "generic",
        "binary_yes_no",
        lines,
        ask,
        facts,
        ["specificity", "single binary commitment"],
        f"generic handler for {ctx.kind}",
        deliverable="one concrete growth idea",
    )
