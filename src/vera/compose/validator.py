"""Grounding and style validation, rules V1–V17 (06 §5, 09 §5)."""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from vera.compose.facts import FactSheet
from vera.compose.numbers import dates_in_text, numbers_in_text
from vera.domain.ids import text_hash
from vera.domain.language import UNAMBIGUOUS_HINDI, hindi_word_count

MAX_BODY_CHARS = 900
SMALL_INT_LIMIT = 10
PLAGIARISM_RATIO = 0.6
CASE_STUDIES = Path(
    os.getenv("VERA_CASE_STUDIES_PATH")
    or Path(__file__).resolve().parents[3] / "reference" / "challenge" / "examples" / "case-studies.md"
)

_URL = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|in|ai|io|org|net|co)\b", re.IGNORECASE)
_SNAKE = re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")
_JARGON = re.compile(
    r"\b(payload|trigger_id|placeholder|suppression|context_id|merchant_id|customer_id)\b", re.IGNORECASE
)
_CTA_MARKERS = re.compile(r"\b(click|tap here|call us now|reply (?:yes|no|stop|confirm|1|2))\b", re.IGNORECASE)
_HONORIFIC_NAME = re.compile(r"\b(?:Dr|Mr|Mrs|Ms)\.?\s+([A-Z][a-zA-Z]+)")
_JI_NAME = re.compile(r"\b([A-Z][a-zA-Z]+)\s+ji\b")
_ALLCAPS = re.compile(r"\b[A-Z]{2,}\b")
_SOURCE_CLAIM = re.compile(
    r"\b(stud(?:y|ies)|clinical trial|trial (?:showed|shows|found)|[\d,]+-patient trial|"
    r"circular|survey|journal|meta-analysis|research (?:shows|says|found)|reported by)\b",
    re.IGNORECASE,
)
_RELATIVE_DAYS = re.compile(r"\bin (\d+) (?:days?|weeks?)\b|\b(\d+) days? (?:left|to go|until)\b", re.IGNORECASE)
_REINTRO = re.compile(r"\b(this is vera|vera here|i am vera|i'm vera|vera from magicpin|vera se bol)\b", re.IGNORECASE)
QUALIFYING = ("would you", "do you", "can you tell", "what if", "how about")
GENERIC_BUSINESS_WORDS = {
    "dr",
    "s",
    "the",
    "and",
    "of",
    "by",
    "dental",
    "clinic",
    "care",
    "centre",
    "center",
    "studio",
    "salon",
    "salons",
    "family",
    "beauty",
    "hair",
    "spa",
    "lounge",
    "fitness",
    "gym",
    "yoga",
    "pharmacy",
    "medicos",
    "medical",
    "health",
    "cafe",
    "restaurant",
    "kitchen",
    "house",
    "express",
    "junction",
    "plus",
    "co",
}
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Check:
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def add(self, code: str, detail: str = "") -> None:
        self.violations.append(f"{code}:{detail}" if detail else code)


@lru_cache(maxsize=1)
def case_study_bodies() -> tuple[str, ...]:
    if not CASE_STUDIES.exists():
        return ()
    text = CASE_STUDIES.read_text(encoding="utf-8")
    return tuple(" ".join(b.split()) for b in re.findall(r"```\n(.*?)```", text, re.S) if len(b) > 80)


def plagiarism_ratio(body: str) -> float:
    norm = " ".join(body.split()).lower()
    return max((difflib.SequenceMatcher(None, norm, cs.lower()).ratio() for cs in case_study_bodies()), default=0.0)


def validate(
    opener: str,
    middle: str,
    ask: str,
    sheet: FactSheet,
    *,
    language: str,
    salutation_name: str | None,
    first_message: bool = True,
    prior_body_hashes: list[str] | None = None,
    extra_numbers: set[str] | None = None,
    action_mode: bool = False,
    business_name: str | None = None,
) -> Check:
    check = Check()
    body = f"{opener} {middle} {ask}".strip()
    # V1 structure
    if not opener.strip() or not middle.strip() or not ask.strip():  # WhatsApp template params can't be empty
        check.add("V1", "empty part")
    if len(body) > MAX_BODY_CHARS:
        check.add("V1", "too long")
    if "?" in opener or "?" in middle:
        check.add("V1", "question outside ask")
    # V2 single CTA: ask is one sentence, middle has no CTA markers
    if len([s for s in _SENTENCE.split(ask.strip()) if s]) > 1:
        check.add("V2", "ask has several sentences")
    if _CTA_MARKERS.search(middle):
        check.add("V2", "cta in middle")
    # V3 URLs
    if _URL.search(body):
        check.add("V3")
    # V4 taboos
    lowered = body.lower()
    for phrase in sheet.taboos:
        if phrase.lower() in lowered:
            check.add("V4", phrase)
    # V5 jargon
    for m in _SNAKE.finditer(body):
        check.add("V5", m.group(0))
    if _JARGON.search(body):
        check.add("V5", _JARGON.search(body).group(0))  # type: ignore[union-attr]
    # V6 numbers
    allowed = sheet.allowed_numbers | (extra_numbers or set())
    for token in numbers_in_text(body):
        if token in allowed:
            continue
        if token.isdigit() and int(token) <= SMALL_INT_LIMIT:
            continue
        check.add("V6", token)
    # V7 dates
    for day_month in dates_in_text(body):
        if day_month not in sheet.allowed_dates:
            check.add("V7", f"{day_month[0]}/{day_month[1]}")
    # V8 relative durations must be payload numbers (already V6-checked) - reject 'in N days' unless allowed
    for m in _RELATIVE_DAYS.finditer(body):
        n = m.group(1) or m.group(2)
        if n not in allowed:
            check.add("V8", n)
    # V9 acronyms
    for m in _ALLCAPS.finditer(body):
        if m.group(0) not in sheet.allowed_acronyms:
            check.add("V9", m.group(0))
    # V10 people
    for m in list(_HONORIFIC_NAME.finditer(body)) + list(_JI_NAME.finditer(body)):
        if m.group(1) not in sheet.allowed_names:
            check.add("V10", m.group(1))
    # V11 source claims need a known source in the body
    if _SOURCE_CLAIM.search(body) and not any(src.lower() in lowered for src in sheet.allowed_sources):
        check.add("V11", _SOURCE_CLAIM.search(body).group(0))  # type: ignore[union-attr]
    # V12 re-introduction
    if not first_message and _REINTRO.search(body):
        check.add("V12")
    # V13 repetition
    if prior_body_hashes and text_hash(body) in prior_body_hashes:
        check.add("V13")
    # V14 plagiarism
    if plagiarism_ratio(body) > PLAGIARISM_RATIO:
        check.add("V14")
    # V15 language
    if language == "hinglish" and hindi_word_count(body) < 2:
        check.add("V15", "expected hinglish")
    if language in {"english", "english_light_hindi"} and any(
        w in UNAMBIGUOUS_HINDI for w in re.findall(r"[a-z]+", lowered)
    ):
        check.add("V15", "expected english")
    # V16 salutation
    if salutation_name and salutation_name.lower() not in opener.lower():
        check.add("V16", salutation_name)
    if "dr. dr." in lowered:
        check.add("V16", "double honorific")
    # V18 customer-facing messages must say who is writing (a distinctive word of the business name)
    if business_name:
        tokens = [w for w in re.findall(r"[A-Za-z0-9]+", business_name) if w.lower() not in GENERIC_BUSINESS_WORDS]
        if tokens and not any(w.lower() in lowered for w in tokens):
            check.add("V18", business_name)
    # V17 action mode: no qualifying phrasing
    if action_mode and any(q in lowered for q in QUALIFYING):
        check.add("V17")
    return check


def validate_reply(
    body: str,
    sheet: FactSheet,
    *,
    language: str,
    extra_numbers: set[str] | None = None,
    action_mode: bool = False,
    prior_body_hashes: list[str] | None = None,
) -> Check:
    """Replies have no salutation slot: validate the body as middle + final sentence."""
    parts = [s for s in _SENTENCE.split(body.strip()) if s]
    ask = parts[-1] if parts else ""
    middle = " ".join(parts[:-1]) or ask
    check = validate(
        "-",
        middle,
        ask,
        sheet,
        language=language,
        salutation_name=None,
        first_message=False,
        prior_body_hashes=prior_body_hashes,
        extra_numbers=extra_numbers,
        action_mode=action_mode,
    )
    check.violations = [
        v for v in check.violations if v not in {"V1:question outside ask", "V2:ask has several sentences"}
    ]
    return check


def offending_sentences(middle: str, check: Check) -> list[str]:
    """Sentences in `middle` that contain an offending token (for the drop-sentence repair)."""
    tokens = [v.split(":", 1)[1] for v in check.violations if ":" in v and v.split(":", 1)[0] in {"V6", "V9", "V10"}]
    sentences = [s for s in _SENTENCE.split(middle) if s]
    return [s for s in sentences if any(t and t in s for t in tokens)]
