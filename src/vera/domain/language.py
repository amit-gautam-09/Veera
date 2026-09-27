"""Language directive per audience (ADR-007) and per-turn detection (09 §2)."""

from __future__ import annotations

import re
from typing import Any, Literal

Language = Literal["hinglish", "english", "english_light_hindi"]

SOUTHERN = {"ta", "te", "kn", "ml"}
HINDI_WORDS = {
    "hai",
    "hain",
    "ke",
    "ki",
    "ka",
    "kar",
    "karo",
    "karna",
    "aap",
    "aapke",
    "aapka",
    "aapki",
    "mein",
    "main",
    "toh",
    "bhi",
    "nahi",
    "nahin",
    "kya",
    "haan",
    "ji",
    "theek",
    "thik",
    "accha",
    "achha",
    "abhi",
    "baad",
    "kal",
    "bhejo",
    "bhej",
    "doon",
    "dijiye",
    "chahiye",
    "kaise",
    "kitna",
    "hum",
    "hamara",
    "mera",
    "meri",
    "yeh",
    "woh",
    "aur",
    "lekin",
    "matlab",
    "shukriya",
    "dhanyavaad",
    "namaste",
    "chalo",
    "kab",
    "kyun",
}
UNAMBIGUOUS_HINDI = {"hai", "hain", "aap", "aapke", "aapka", "aapki", "nahi", "nahin", "kya", "hum", "yeh", "doon"}
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_WORD = re.compile(r"[a-zA-Z]+")


def merchant_language(merchant: dict[str, Any], category: dict[str, Any] | None) -> Language:
    langs = {str(x).lower() for x in ((merchant.get("identity") or {}).get("languages") or [])}
    code_mix = str(((category or {}).get("voice") or {}).get("code_mix") or "")
    if "hi" not in langs:
        return "english"
    if langs & SOUTHERN or code_mix.startswith("english_primary"):
        return "english_light_hindi"
    return "hinglish"


def customer_language(customer: dict[str, Any]) -> Language:
    pref = str((customer.get("identity") or {}).get("language_pref") or "").lower().strip()
    if pref in {"hi", "hindi", "hi-en mix", "hinglish", "hi-en"}:
        return "hinglish"
    return "english"


def hindi_word_count(text: str) -> int:
    return sum(1 for w in _WORD.findall(text.lower()) if w in HINDI_WORDS)


def detect_language(text: str) -> Language:
    """Language of an inbound message: Devanagari or >= 2 Hindi function words -> hinglish."""
    if _DEVANAGARI.search(text):
        return "hinglish"
    return "hinglish" if hindi_word_count(text) >= 2 else "english"
