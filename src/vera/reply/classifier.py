"""Rule-based intent classification for inbound replies (09 §2). English, Hinglish (Roman) and Devanagari."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

Intent = Literal[
    "auto_reply", "opt_out", "hostile", "accept", "question", "off_topic", "defer", "soft_no", "engaged_info",
    "slot_selection", "unclear",
]  # fmt: skip

AUTO_REPLY_MIN_REPEAT_CHARS = 30


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


OPT_OUT = _rx(
    r"\bstop\b(?! (?:by|at|the|and think))",
    r"\bunsubscribe\b",
    r"\bdo ?n[o']?t (?:message|text|contact|send)",
    r"\bremove me\b",
    r"\bnot interested\b",
    r"\bleave me alone\b",
    r"\bno more (?:messages|msgs)\b",
    r"\bband karo\b",
    r"\bmat bhej",
    r"\bmessage mat\b",
    r"\bmsg mat\b",
    r"\bbas karo\b",
    r"\bpareshan mat",
    r"बंद करो",
    r"मत भेज",
    r"परेशान मत",
)
HOSTILE = _rx(
    r"\bspam\b",
    r"\buseless\b",
    r"\bbother(?:ing)?\b",
    r"\birritat",
    r"\bscam\b",
    r"\bfraud\b",
    r"\bnonsense\b",
    r"\brubbish\b",
    r"\bwaste of (?:my )?time\b",
    r"\bstupid\b",
    r"\bidiot",
    r"\bshut up\b",
    r"\bget lost\b",
    r"\bf+u+c+k",
    r"\bbakwas\b",
    r"\bpagal\b",
    r"\bfaltu\b",
    r"\bbekaar\b",
    r"\bbekar\b",
    r"\bchutiya",
    r"बकवास",
    r"पागल",
    r"फालतू",
)
AUTO_REPLY = _rx(
    r"thank(?:s| you) for (?:contacting|reaching out|your message|messaging)",
    r"our team will (?:respond|get back|contact|reply)",
    r"we(?:'ll| will) get back to you",
    r"(?:currently|presently) (?:unavailable|closed|away)",
    r"business hours",
    r"this is an? auto(?:mated|matic)?(?:-| )?(?:reply|message|response)",
    r"\bauto[- ]?reply\b",
    r"out of (?:the )?office",
    r"will respond (?:shortly|soon|as soon)",
    r"aapki (?:madad|jaankari) ke liye (?:bahut[- ]bahut )?shukriya",
    r"team tak pahuncha",
    r"jald hi (?:sampark|aapse)",
    r"main ek automated assistant",
    r"automated assistant",
    r"we have received your (?:message|query)",
)
ACCEPT = _rx(
    r"^(?:yes|yeah|yep|yup|ya|ok|okay|okk+|sure|done|fine|great|perfect|go ahead|please do|do it|send it|confirm(?:ed)?|"
    r"proceed|sounds good|let'?s do it|lets do it|let'?s go|haan|haa|han|haan ji|ji|ji haan|theek hai|thik hai|"
    r"chalo|kar do|kardo|bhej do|bhejo|हाँ|हां|ठीक है)\b",
    r"\b(?:go ahead|let'?s do it|lets do it|do it|please send|send (?:it|me|the)|confirm|proceed|sounds good|"
    r"kar do|bhej do|shuru karo|haan ji)\b",
    r"👍|✅",
)
DEFER = _rx(
    r"\blater\b",
    r"\bbusy\b",
    r"\bcall (?:me )?(?:later|tomorrow|back)\b",
    r"\btomorrow\b",
    r"\bin \d+ ?(?:min|mins|minutes|hr|hrs|hours?)\b",
    r"\bbaad mein\b",
    r"\bbaad me\b",
    r"\bkal\b",
    r"\babhi busy\b",
    r"\bthodi der\b",
    r"\bnext week\b",
    r"\bafter \d",
)
SOFT_NO = _rx(
    r"^no\b",
    r"\bno thanks\b",
    r"\bnot now\b",
    r"\bmaybe later\b",
    r"\bnot needed\b",
    r"\bnot required\b",
    r"\bnahi chahiye\b",
    r"\babhi nahi\b",
    r"\bzarurat nahi\b",
    r"^nahi\b",
    r"\bnope\b",
    r"^नहीं",
)
OFF_TOPIC = _rx(
    r"\bgst\b",
    r"\bincome tax\b",
    r"\btax(?:es)? (?:filing|return)",
    r"\bitr\b",
    r"\bchartered accountant\b",
    r"\bmy ca\b",
    r"\baccounting\b",
    r"\bloan\b",
    r"\belectricity bill\b",
    r"\blegal (?:notice|case|advice)\b",
    r"\binsurance\b",
    r"\bvisa\b",
    r"\bpassport\b",
    r"\bbank account\b",
    r"\bcredit card\b",
    r"\bpan card\b",
    r"\baadhaar\b",
)
QUESTION = _rx(
    r"\?\s*$",
    r"^(?:what|how|why|when|which|where|who|can|could|is|are|do|does|will|kya|kaise|kitna|kitne|kab|kyun|kaun)\b",
)
SLOT_NUMBER = re.compile(r"^\s*(?:option\s*)?#?\s*([1-9])\s*[.)!]?\s*$", re.IGNORECASE)
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass(frozen=True)
class Classification:
    intent: Intent
    evidence: str
    slot_index: int | None = None


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).strip().split())


def match_slot(text: str, labels: list[str]) -> int | None:
    """Index of the offered slot the customer picked: a number, or a weekday/date that appears in one label."""
    m = SLOT_NUMBER.match(text)
    if m:
        idx = int(m.group(1)) - 1
        return idx if 0 <= idx < len(labels) else None
    low = text.lower()
    for i, label in enumerate(labels):
        lab = label.lower()
        day = next((d for d in WEEKDAYS if re.search(rf"\b{d}", low) and d in lab), None)
        date = re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", low)
        if day or (date and date.group(1) in re.findall(r"\d+", lab)):
            return i
    return None


def classify(
    message: str,
    *,
    from_role: str,
    last_bot_was_proposal: bool,
    seen_before: bool,
    offered_slots: list[str] | None = None,
) -> Classification:
    text = normalize(message)
    low = text.lower()
    if not low:
        return Classification("unclear", "empty")
    if OPT_OUT.search(low):
        return Classification("opt_out", OPT_OUT.search(low).group(0))  # type: ignore[union-attr]
    if HOSTILE.search(low):
        return Classification("hostile", HOSTILE.search(low).group(0))  # type: ignore[union-attr]
    if AUTO_REPLY.search(low):
        return Classification("auto_reply", AUTO_REPLY.search(low).group(0))  # type: ignore[union-attr]
    if from_role == "customer" and offered_slots:
        idx = match_slot(text, offered_slots)
        if idx is not None:
            return Classification("slot_selection", "slot match", idx)
        if len(offered_slots) == 1 and ACCEPT.search(low):
            return Classification("slot_selection", "yes to the only slot", 0)
        if re.search(r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b|\d{1,2}\s*(?:am|pm)\b", low):
            return Classification("slot_selection", "time not offered", None)
    if OFF_TOPIC.search(low):
        return Classification("off_topic", OFF_TOPIC.search(low).group(0))  # type: ignore[union-attr]
    if ACCEPT.search(low):
        return Classification("accept" if last_bot_was_proposal else "engaged_info", "affirmative")
    if DEFER.search(low):
        return Classification("defer", DEFER.search(low).group(0))  # type: ignore[union-attr]
    if SOFT_NO.search(low):
        return Classification("soft_no", SOFT_NO.search(low).group(0))  # type: ignore[union-attr]
    # an unknown canned text: the same long statement arriving again (intents above are never auto-replies)
    if seen_before and len(low) >= AUTO_REPLY_MIN_REPEAT_CHARS:
        return Classification("auto_reply", "repeat of an earlier message")
    if QUESTION.search(low):
        return Classification("question", "question form")
    if len(low.split()) >= 3:
        return Classification("engaged_info", "statement")
    return Classification("unclear", "no rule matched")


def wait_seconds(message: str) -> int:
    """Wait implied by a defer message (09 §3): explicit durations, tomorrow, else 1 hour."""
    low = message.lower()
    m = re.search(r"\b(\d+)\s*(min|mins|minutes|hr|hrs|hour|hours)\b", low)
    if m:
        n = int(m.group(1)) * (60 if m.group(2).startswith("m") else 3600)
        return max(900, min(172800, n))
    if re.search(r"\b(?:tomorrow|kal|next day)\b", low):
        return 86400
    if "next week" in low:
        return 172800
    return 3600
