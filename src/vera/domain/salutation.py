"""Salutations and display names (08 §1.3, register R-43/R-44)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from vera.domain.language import Language

_HONORIFIC = re.compile(r"^(dr|mr|mrs|ms)\.?\s+", re.IGNORECASE)
_PARENT = re.compile(r"^\s*(?P<child>[^()]+?)\s*\(\s*parent:\s*(?P<parent>[^)]+?)\s*\)\s*$", re.IGNORECASE)


def strip_honorific(name: str) -> str:
    return _HONORIFIC.sub("", name.strip()).strip()


def owner_name(merchant: dict[str, Any]) -> str | None:
    raw = (merchant.get("identity") or {}).get("owner_first_name")
    return strip_honorific(str(raw)) if raw else None


def merchant_opener(merchant: dict[str, Any], category_slug: str, language: Language) -> str:
    first = owner_name(merchant)
    business = (merchant.get("identity") or {}).get("name") or "there"
    if not first:
        return f"{business} team,"
    if category_slug == "dentists":
        return f"Dr. {first},"
    if language == "hinglish" and category_slug in {"restaurants", "pharmacies"}:
        return f"{first} ji,"
    return f"Hi {first},"


@dataclass(frozen=True)
class CustomerName:
    addressee: str | None  # who the message greets
    subject: str | None  # who the service is for (child / senior), if different
    senior: bool
    walk_in: bool


def customer_name(customer: dict[str, Any]) -> CustomerName:
    identity = customer.get("identity") or {}
    raw = str(identity.get("name") or "").strip()
    senior = bool(identity.get("senior_citizen")) or str(identity.get("age_band", "")).startswith(("65", "60", "70"))
    if not raw or raw.startswith("(") or "walk-in" in raw.lower():
        return CustomerName(None, None, senior, walk_in=True)
    m = _PARENT.match(raw)
    if m:
        return CustomerName(m.group("parent").strip(), m.group("child").strip(), senior, walk_in=False)
    if _HONORIFIC.match(raw):  # "Mr. Sharma": message goes to family, subject is "Sharma ji"
        return CustomerName(None, strip_honorific(raw), senior, walk_in=False)
    return CustomerName(raw.split()[0], None, senior, walk_in=False)


def customer_opener(name: CustomerName, language: Language) -> str:
    if name.addressee:
        return f"Hi {name.addressee},"
    return "Namaste," if language == "hinglish" else "Hello,"
