"""Independent grounding auditor (docs/10 §6): every risky token in a body must trace to the raw contexts.

Deliberately separate from the runtime validator: it rebuilds its allowed sets straight from the contexts the
message was composed from, so a validator bug that lets a token through is still caught here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from vera.compose.numbers import allowed_dates, allowed_numbers, dates_in_text, numbers_in_text

SMALL_INT_LIMIT = 10
ALWAYS_OK_ACRONYMS = {"OK", "YES", "NO", "STOP", "CONFIRM", "CTR", "GBP", "PDF", "SOP", "CA", "GST", "PT", "AM", "PM"}
_ALLCAPS = re.compile(r"\b[A-Z]{2,}\b")
_HONORIFIC = re.compile(r"\b(?:Dr|Mr|Mrs|Ms)\.?\s+([A-Z][a-zA-Z]+)|\b([A-Z][a-zA-Z]+)\s+ji\b")
_SOURCE = re.compile(r"\b(?:study|studies|clinical trial|circular|survey|journal|meta-analysis)\b", re.IGNORECASE)
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_SNAKE = re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")


@dataclass
class Finding:
    kind: str
    token: str


@dataclass
class Audit:
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings


def _strings(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        return [s for k, v in obj.items() for s in [str(k), *_strings(v)]]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return [obj] if isinstance(obj, str) else []


def _numeric_values(contexts: list[Any]) -> list[float]:
    out: list[float] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, int | float) and not isinstance(obj, bool):
            out.append(float(obj))

    for c in contexts:
        if isinstance(c, dict):
            walk({k: v for k, v in c.items() if k not in {"digest", "offer_catalog", "patient_content_library"}})
    return out[:400]


def derivable(token: str, values: list[float], body: str, shown: set[float]) -> bool:
    """Code-derived values: a ratio written as 'Nx', or a difference/sum/share of two numbers shown in the body."""
    try:
        t = float(token)
    except ValueError:
        return False
    if re.search(rf"\b{re.escape(token)}x\b", body):
        return any(b and abs(a / b - t) < 0.051 for a in values for b in values)
    for a in shown:
        for b in shown:
            if abs(a - b - t) < 0.001 or abs(a + b - t) < 0.001:
                return True
            if b and (abs(100 * a / b - t) < 0.51 or (a + b and abs(100 * a / (a + b) - t) < 0.51)):
                return True
    return False


def _source_name(source: str) -> str:
    """'Dental Council of India circular 2026-11-04' -> 'Dental Council of India circular'."""
    return re.split(r"[,(]|\s\d", source, maxsplit=1)[0].strip()


def audit(body: str, contexts: list[Any], inbound: str = "") -> Audit:
    result = Audit()
    numbers = allowed_numbers(contexts) | set(numbers_in_text(inbound))
    values = _numeric_values(contexts)
    dates = allowed_dates(contexts)
    text = " ".join(_strings(contexts)) + " " + inbound
    body_tokens = numbers_in_text(body)
    shown = {float(x) for x in body_tokens if x in numbers}
    for token in body_tokens:
        if token in numbers or (token.isdigit() and int(token) <= SMALL_INT_LIMIT):
            continue
        if derivable(token, values, body, shown):
            continue
        result.findings.append(Finding("number", token))
    for day, month in dates_in_text(body):
        if (day, month) not in dates:
            result.findings.append(Finding("date", f"{day}/{month}"))
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    for m in _ALLCAPS.finditer(body):
        if m.group(0) not in ALWAYS_OK_ACRONYMS and m.group(0) not in text and m.group(0).lower() not in words:
            result.findings.append(Finding("acronym", m.group(0)))
    for m in _HONORIFIC.finditer(body):
        name = m.group(1) or m.group(2)
        if name and name not in text:
            result.findings.append(Finding("person", name))
    if _SOURCE.search(body):
        sources = [str(d.get("source")) for c in contexts if isinstance(c, dict) for d in c.get("digest") or []]
        if not any(s and _source_name(s) and _source_name(s) in body for s in sources):
            result.findings.append(Finding("source", _SOURCE.search(body).group(0)))  # type: ignore[union-attr]
    if _URL.search(body):
        result.findings.append(Finding("url", _URL.search(body).group(0)))  # type: ignore[union-attr]
    for m in _SNAKE.finditer(body):
        result.findings.append(Finding("jargon", m.group(0)))
    return result
