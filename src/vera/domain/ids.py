"""Deterministic ids, hashes and text normalisation (docs/03-backend-schema.md §7)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    """Lowercase, NFKC, drop punctuation/emoji, collapse whitespace (used for repeat detection)."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "S")  # symbols incl. emoji
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def text_hash(text: str) -> str:
    return sha256(normalize_text(text))[:16]


def short_id(entity_id: str | None) -> str:
    """`m_001_drmeera_dentist_delhi` -> `m001_drmeera`; `c_001_priya_for_m001` -> `c001_priya`."""
    if not entity_id:
        return "x"
    parts = entity_id.split("_")
    if len(parts) >= 3:
        return f"{parts[0]}{parts[1]}_{parts[2]}"
    return entity_id.replace("_", "")


def yyyymmdd(now_iso: str | None) -> str:
    if now_iso:
        digits = re.sub(r"\D", "", now_iso)[:8]
        if len(digits) == 8:
            return digits
    return datetime.now(UTC).strftime("%Y%m%d")


def conversation_id(
    merchant_id: str,
    customer_id: str | None,
    kind: str,
    trigger_id: str,
    trigger_version: int,
    now_iso: str | None,
) -> str:
    who = short_id(merchant_id) + (f"_{short_id(customer_id)}" if customer_id else "")
    digest = sha256(f"{trigger_id}|{customer_id or ''}|{trigger_version}")[:6]
    return f"conv_{who}_{kind}_{yyyymmdd(now_iso)}_{digest}"


def ack_id(scope: str, context_id: str, version: int) -> str:
    return f"ack_{scope}_{context_id}_v{version}"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
