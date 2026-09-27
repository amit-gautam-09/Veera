"""Number, money, percent and date normalisation shared by the fact sheet and the validator (06 §5)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from typing import Any

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_RE = "|".join(MONTHS)
_COMMA_IN_NUMBER = re.compile(r"(?<=\d),(?=\d)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})[a-z]*\b", re.IGNORECASE)
_MONTH_DAY = re.compile(rf"\b({_MONTH_RE})[a-z]*\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_LAKH = re.compile(r"(\d+(?:\.\d+)?)\s*(lakh|lac|k)\b", re.IGNORECASE)


def strip_separators(text: str) -> str:
    """`2,410` / `1,20,000` -> `2410` / `120000`; unicode minus -> `-`; Rs/INR -> ₹."""
    text = text.replace("−", "-").replace("–", "-")
    text = re.sub(r"\b(?:Rs\.?|INR)\s*", "₹", text)
    return _COMMA_IN_NUMBER.sub("", text)


def _expand_lakh(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        mult = 1000 if m.group(2).lower() == "k" else 100000
        return _fmt(float(m.group(1)) * mult)

    return _LAKH.sub(repl, text)


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _canon(token: str) -> str:
    """`3.0` -> `3`, `2.50` -> `2.5`, `007` -> `7` so renderings compare equal."""
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token.lstrip("0") or "0"


def numbers_in_text(text: str) -> list[str]:
    """Digit-runs in a message body after normalisation (the tokens V6 must trace)."""
    return [_canon(t) for t in _NUMBER.findall(_expand_lakh(strip_separators(text)))]


def renderings(value: Any) -> set[str]:
    """Every numeric string a correct message might use for a context value."""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, int):
        return {str(abs(value))}
    if isinstance(value, float):
        out = {_fmt(abs(value))}
        if abs(value) < 1:  # fractions: 0.021 -> 2.1 / 2 ; -0.5 -> 50
            pct = abs(value) * 100
            out |= {_fmt(round(pct, 1)), _fmt(round(pct)), _fmt(round(pct, 2))}
        else:
            out |= {_fmt(round(value, 1)), _fmt(round(value))}
        return out
    if isinstance(value, str):
        return set(numbers_in_text(value)) | time_renderings(value)
    return set()


def time_renderings(text: str) -> set[str]:
    """ISO datetimes -> 12-hour clock digits (`19:30` -> `7`, `30`)."""
    out: set[str] = set()
    for m in re.finditer(r"T(\d{2}):(\d{2})", text):
        hour = int(m.group(1))
        out |= {str(hour), str(hour % 12 or 12), m.group(2).lstrip("0") or "0"}
    return out


def walk_values(obj: Any) -> Iterator[Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)  # keys carry numbers too: lapsed_180d_plus, avg_views_30d
            yield from walk_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_values(v)
    else:
        yield obj


def allowed_numbers(sources: Iterable[Any]) -> set[str]:
    allowed: set[str] = set()
    for source in sources:
        for value in walk_values(source):
            allowed |= renderings(value)
    return allowed


def dates_in_text(text: str) -> set[tuple[int, int]]:
    """(day, month) pairs mentioned as dates: ISO, '15 Dec', 'Dec 15'."""
    found: set[tuple[int, int]] = set()
    for _y, mo, d in _ISO_DATE.findall(text):
        found.add((int(d), int(mo)))
    for d, mon in _DAY_MONTH.findall(text):
        found.add((int(d), MONTHS.index(mon[:3].lower()) + 1))
    for mon, d in _MONTH_DAY.findall(text):
        found.add((int(d), MONTHS.index(mon[:3].lower()) + 1))
    return {(d, m) for d, m in found if 1 <= d <= 31}


def allowed_dates(sources: Iterable[Any]) -> set[tuple[int, int]]:
    allowed: set[tuple[int, int]] = set()
    for source in sources:
        for value in walk_values(source):
            if isinstance(value, str):
                allowed |= dates_in_text(value)
    return allowed


def parse_iso(value: Any) -> datetime | date | None:
    if not isinstance(value, str):
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


# --- rendering helpers used by the playbook ------------------------------------------------------
def fmt_int(n: int | float) -> str:
    return f"{int(round(n)):,}"


def fmt_money(n: int | float | str) -> str:
    try:
        return f"₹{int(float(str(n).replace(',', ''))):,}"
    except ValueError:
        return f"₹{n}"


def fmt_pct(fraction: float, signed: bool = False) -> str:
    pct = round(abs(fraction) * 100)
    if not signed:
        return f"{pct}%"
    return f"{'+' if fraction >= 0 else '-'}{pct}%"


def fmt_date(value: Any, with_year: bool = False) -> str | None:
    parsed = parse_iso(value)
    if parsed is None:
        return None
    text = f"{parsed.day} {MONTHS[parsed.month - 1].title()}"
    return f"{text} {parsed.year}" if with_year else text


def fmt_time(value: Any) -> str | None:
    parsed = parse_iso(value)
    if not isinstance(parsed, datetime):
        return None
    hour = parsed.hour % 12 or 12
    suffix = "am" if parsed.hour < 12 else "pm"
    return f"{hour}{suffix}" if parsed.minute == 0 else f"{hour}:{parsed.minute:02d}{suffix}"


def pretty_dates(text: str) -> str:
    """`2026-12-15` inside prose -> `15 Dec 2026`."""
    return _ISO_DATE.sub(lambda m: f"{int(m.group(3))} {MONTHS[int(m.group(2)) - 1].title()} {m.group(1)}", text)


def weekday(value: Any) -> str | None:
    parsed = parse_iso(value)
    return parsed.strftime("%A") if parsed is not None else None
