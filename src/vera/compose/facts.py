"""Context resolution, typed facts and the allowed-token index (06 §2, TRD §4.5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from vera.compose.numbers import allowed_dates, allowed_numbers, renderings
from vera.domain.language import Language, customer_language, merchant_language
from vera.domain.salutation import CustomerName, customer_name, merchant_opener, owner_name

PEOPLE = {
    "dentists": "patients",
    "salons": "clients",
    "gyms": "members",
    "restaurants": "customers",
    "pharmacies": "customers",
}
ACRONYM_ALLOWLIST = {
    "GBP",
    "CTR",
    "ORS",
    "OTC",
    "MRP",
    "RCT",
    "OPG",
    "IOPA",
    "RVG",
    "DCI",
    "IDA",
    "CDE",
    "PT",
    "HIIT",
    "BOGO",
    "IPL",
    "GST",
    "FSSAI",
    "CDSCO",
    "AOV",
    "SPF",
    "OK",
    "YES",
    "NO",
    "STOP",
    "CONFIRM",
    "CA",
    "PDF",
    "SOP",
    "DC",
    "MI",
    "JIDA",
    "ICMR",
    "DGCI",
    "FDA",
    "AM",
    "PM",
    "WA",
    "UPI",
    "LDL",
    "CAD",
    "CAM",
    "PFM",
    "EMOM",
    "AMRAP",
    "BMR",
    "RPC",
    "GRO",
    "YOY",
    "NCR",
    "HSR",
    "RMZ",
}
_CAPITALISED = re.compile(r"\b[A-Z][a-zA-Z'’]+\b")
_ALLCAPS = re.compile(r"\b[A-Z]{2,}\b")

SIGNAL_LABELS: dict[str, str] = {
    "stale_posts": "last Google post was {n} days ago",
    "ctr_below_peer_median": "CTR is below the peer median",
    "high_risk_adult_cohort": "has a high-risk adult patient cohort",
    "engaged_in_last_48h": "replied to Vera in the last 48 hours",
    "renewal_due_soon": "subscription renews in {n} days",
    "perf_dip_severe": "performance dropped sharply this week",
    "unverified_gbp": "Google profile is not verified",
    "dormant_with_vera": "no reply to Vera in {n} days",
    "no_active_offers": "no active offer on the profile",
    "high_engagement": "highly engaged",
    "above_peer_median_calls": "calls above the peer median",
    "growing_views_7d": "views growing this week",
    "winback_eligible": "subscription lapsed, eligible for win-back",
    "perf_dip_post_expiry": "performance dropped after the plan expired",
    "new_merchant": "new on magicpin",
    "trial_ending_soon": "trial ending soon",
    "ipl_eligible_locality": "locality with IPL match-night demand",
    "seasonal_dip_apr_may": "seasonal April-May dip",
    "above_peer_ctr": "CTR above the peer average",
    "no_recent_post": "no recent Google post",
    "high_retention": "high member retention",
    "active_planning": "planning a new programme",
    "boutique_segment": "boutique studio",
    "compliance_aware": "compliance-aware",
    "high_repeat_rate": "high repeat-customer rate",
    "above_peer_calls": "calls above the peer average",
    "no_recent_conversation": "no recent conversation with Vera",
    "delivery_not_set_up": "home delivery not set up",
    "stable_growth": "steady growth",
    "high_volume": "high order volume",
}


def humanize(key: str) -> str:
    return key.replace("_", " ").replace("  ", " ").strip()


def signal_label(signal: str) -> str:
    base, _, arg = signal.partition(":")
    m = re.match(r"^(.*?)_(\d+)d$", base)
    if m and not arg:
        base, arg = m.group(1), m.group(2)
    n = re.sub(r"\D", "", arg)
    template = SIGNAL_LABELS.get(base)
    if template:
        return template.format(n=n) if "{n}" in template and n else template.replace(" {n} days", "")
    return humanize(base)


@dataclass
class Fact:
    label: str
    render: str
    source: str
    visible: bool = False

    def line(self, idx: int) -> str:
        return f"F{idx:02d} [{self.source}] {self.label}: {self.render}"


@dataclass
class Ctx:
    """Everything the playbook needs for one trigger, with rendering helpers."""

    trigger_id: str
    trigger: dict[str, Any]
    merchant: dict[str, Any]
    category: dict[str, Any]
    customer: dict[str, Any] | None
    derived: list[Any] = field(default_factory=list)

    # --- identity -----------------------------------------------------------------------------
    @property
    def kind(self) -> str:
        return str(self.trigger.get("kind") or "unknown")

    @property
    def payload(self) -> dict[str, Any]:
        p = self.trigger.get("payload")
        return p if isinstance(p, dict) else {}

    @property
    def placeholder(self) -> bool:
        return bool(self.payload.get("placeholder")) or not self.payload

    @property
    def slug(self) -> str:
        return str(self.category.get("slug") or self.merchant.get("category_slug") or "")

    @property
    def identity(self) -> dict[str, Any]:
        return self.merchant.get("identity") or {}

    @property
    def business(self) -> str:
        return str(self.identity.get("name") or "your business")

    @property
    def owner(self) -> str | None:
        return owner_name(self.merchant)

    @property
    def locality(self) -> str:
        return str(self.identity.get("locality") or self.identity.get("city") or "your area")

    @property
    def people(self) -> str:
        return PEOPLE.get(self.slug, "customers")

    @property
    def lang(self) -> Language:
        return merchant_language(self.merchant, self.category)

    @property
    def cust_lang(self) -> Language:
        return customer_language(self.customer) if self.customer else "english"

    @property
    def cust_name(self) -> CustomerName | None:
        return customer_name(self.customer) if self.customer else None

    def opener(self) -> str:
        return merchant_opener(self.merchant, self.slug, self.lang)

    @staticmethod
    def pick(lang: Language, en: str, hi: str) -> str:
        return hi if lang == "hinglish" else en

    def t(self, en: str, hi: str) -> str:
        return self.pick(self.lang, en, hi)

    def tc(self, en: str, hi: str) -> str:
        return self.pick(self.cust_lang, en, hi)

    # --- merchant data --------------------------------------------------------------------------
    @property
    def perf(self) -> dict[str, Any]:
        return self.merchant.get("performance") or {}

    @property
    def deltas(self) -> dict[str, float]:
        d = self.perf.get("delta_7d") or {}
        return {k: float(v) for k, v in d.items() if isinstance(v, int | float) and not isinstance(v, bool)}

    @property
    def peer(self) -> dict[str, Any]:
        return self.category.get("peer_stats") or {}

    @property
    def agg(self) -> dict[str, Any]:
        return self.merchant.get("customer_aggregate") or {}

    @property
    def signals(self) -> list[str]:
        return [str(s) for s in (self.merchant.get("signals") or [])]

    def has_signal(self, name: str) -> bool:
        return any(s.split(":")[0].startswith(name) for s in self.signals)

    @property
    def subscription(self) -> dict[str, Any]:
        return self.merchant.get("subscription") or {}

    @property
    def active_offers(self) -> list[str]:
        return [
            str(o["title"])
            for o in self.merchant.get("offers") or []
            if isinstance(o, dict) and o.get("title") and o.get("status", "active") == "active"
        ]

    @property
    def themes(self) -> list[dict[str, Any]]:
        return [t for t in self.merchant.get("review_themes") or [] if isinstance(t, dict) and t.get("theme")]

    def top_theme(self, sentiment: str) -> dict[str, Any] | None:
        pool = [t for t in self.themes if t.get("sentiment") == sentiment]
        return max(pool, key=lambda t: t.get("occurrences_30d") or 0, default=None)

    @property
    def history(self) -> list[dict[str, Any]]:
        return [h for h in self.merchant.get("conversation_history") or [] if isinstance(h, dict)]

    def last_vera_proposal(self) -> str | None:
        for turn in reversed(self.history):
            if turn.get("from") == "vera" and "?" in str(turn.get("body") or ""):
                return str(turn["body"])
        return None

    # --- category data --------------------------------------------------------------------------
    @property
    def digest(self) -> list[dict[str, Any]]:
        return [d for d in self.category.get("digest") or [] if isinstance(d, dict)]

    def digest_item(self, item_id: Any) -> dict[str, Any] | None:
        return next((d for d in self.digest if d.get("id") == item_id), None) if item_id else None

    def pick_digest(self, kinds: list[str]) -> dict[str, Any] | None:
        for kind in kinds:
            items = [d for d in self.digest if d.get("kind") == kind]
            if items:
                seg_match = [d for d in items if d.get("patient_segment") and self.agg_matches(d["patient_segment"])]
                return (seg_match or items)[0]
        return None

    def agg_matches(self, segment: str) -> bool:
        seg = segment.replace("_", " ")
        return any(seg.split()[0] in k for k in self.agg) or any(seg.replace(" ", "_") in s for s in self.signals)

    def catalog(self, *keywords: str) -> str | None:
        """First catalog title containing any keyword (suggestion only, never 'yours')."""
        items = [o for o in self.category.get("offer_catalog") or [] if isinstance(o, dict) and o.get("title")]
        for kw in keywords:
            for item in items:
                if kw.lower() in str(item["title"]).lower():
                    return str(item["title"])
        return None

    def beat(self, *keywords: str, month: int | None = None) -> dict[str, Any] | None:
        beats = [b for b in self.category.get("seasonal_beats") or [] if isinstance(b, dict)]
        matches = (
            [b for b in beats if any(k in str(b.get("note", "")).lower() for k in keywords)] if keywords else beats
        )
        if month is not None:
            in_month = [b for b in matches if month_in_range(month, str(b.get("month_range", "")))]
            if in_month:
                return in_month[0]
        return matches[0] if matches else None

    def derive(self, value: Any) -> Any:
        """Register a code-computed value so the validator accepts it."""
        self.derived.append(value)
        return value


_MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def month_in_range(month: int, month_range: str) -> bool:
    names = re.findall(r"[A-Za-z]{3}", month_range)
    idx = [_MONTH_ABBR.index(n.lower()) + 1 for n in names if n.lower() in _MONTH_ABBR]
    if not idx:
        return False
    if len(idx) == 1:
        return month == idx[0]
    start, end = idx[0], idx[-1]
    return start <= month <= end if start <= end else (month >= start or month <= end)


@dataclass
class FactSheet:
    facts: list[Fact]
    allowed_numbers: set[str]
    allowed_dates: set[tuple[int, int]]
    allowed_names: set[str]
    allowed_acronyms: set[str]
    allowed_sources: set[str]
    taboos: list[str]

    def render(self) -> str:
        return "\n".join(f.line(i + 1) for i, f in enumerate(self.facts))


def _strings(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_strings(v))
    elif isinstance(obj, str):
        out.append(obj)
    return out


def taboo_phrases(category: dict[str, Any]) -> list[str]:
    voice = category.get("voice") or {}
    raw = list(voice.get("vocab_taboo") or []) + list(voice.get("taboos") or [])
    phrases = [re.sub(r"\s*\(.*?\)\s*", "", str(p)).strip() for p in raw]
    return [p for p in dict.fromkeys(phrases + ["guaranteed", "100%", "best in town", "limited time only"]) if p]


def build_fact_sheet(ctx: Ctx, facts: list[Fact], extra_sources: list[Any] | None = None) -> FactSheet:
    sources: list[Any] = [ctx.trigger, ctx.merchant, ctx.category, ctx.customer or {}, ctx.derived]
    sources += extra_sources or []
    sources += [f.render for f in facts]
    strings = [s for src in sources for s in _strings(src)]
    names = {m.group(0).strip("'’") for s in strings for m in _CAPITALISED.finditer(s)}
    acronyms = {m.group(0) for s in strings for m in _ALLCAPS.finditer(s)} | ACRONYM_ALLOWLIST
    source_words: set[str] = {"magicpin", "Google"}
    for d in ctx.digest:
        source_words |= {w for w in re.findall(r"[A-Za-z][A-Za-z.&+-]+", str(d.get("source") or "")) if len(w) > 2}
    for key in ("regulatory_authorities", "professional_journals"):
        for item in ctx.category.get(key) or []:
            source_words |= {w for w in re.findall(r"[A-Za-z][A-Za-z.&+-]+", str(item)) if len(w) > 2}
    numbers = allowed_numbers(sources)
    for value in ctx.derived:
        numbers |= renderings(value)
    return FactSheet(
        facts=facts,
        allowed_numbers=numbers,
        allowed_dates=allowed_dates(sources),
        allowed_names=names,
        allowed_acronyms=acronyms,
        allowed_sources=source_words,
        taboos=taboo_phrases(ctx.category),
    )
