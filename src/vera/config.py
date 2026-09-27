"""Settings from env vars, then `.env`, then defaults (docs/02-TRD.md §10)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from vera import __version__

DEFAULT_COMPOSER_MODEL = "claude-sonnet-5"
# provider -> (default model, default effort). Gemini: the only free-tier Flash model that answered reliably
# and fast enough for the 7 s tick deadline when measured on 2026-09-27 (ADR-012).
PROVIDER_DEFAULTS = {
    "anthropic": (DEFAULT_COMPOSER_MODEL, None),
    "gemini": ("gemini-3.5-flash-lite", "low"),
    "openai_compatible": ("", None),
}


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if not raw else float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if not raw else int(raw)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None = None
    llm_provider: str = "anthropic"  # anthropic | gemini | openai_compatible
    llm_api_key: str | None = None  # key for non-Anthropic providers
    llm_base_url: str | None = None  # OpenAI-compatible base URL (gemini default built in)
    llm_enabled: bool = True
    composer_model: str = DEFAULT_COMPOSER_MODEL
    llm_max_concurrency: int = 10
    llm_timeout_s: float = 6.0
    llm_effort: str | None = None  # output_config.effort; None = model default
    tick_deadline_s: float = 7.0
    reply_deadline_s: float = 5.0
    repair_min_remaining_s: float = 3.0
    db_path: Path | None = None  # None = memory only (tests)
    restore_window_s: int = 7200
    max_payload_bytes: int = 512_000
    team_name: str = "Amit Gautam"
    team_members: list[str] = field(default_factory=lambda: ["Amit Gautam"])
    contact_email: str = ""
    submitted_at: str = field(default_factory=_now_iso)
    version: str = __version__

    @property
    def llm_active(self) -> bool:
        if not self.llm_enabled or not self.composer_model:
            return False
        key = self.anthropic_api_key if self.llm_provider == "anthropic" else self.llm_api_key
        return bool(key)


def load_settings() -> Settings:
    load_dotenv(override=False)  # real env vars win over .env
    members = os.getenv("VERA_TEAM_MEMBERS", "Amit Gautam")
    db_path = os.getenv("VERA_DB_PATH", "data/vera.db")
    provider = (os.getenv("VERA_LLM_PROVIDER") or "anthropic").strip().lower()
    default_model, default_effort = PROVIDER_DEFAULTS.get(provider, ("", None))
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        llm_provider=provider,
        llm_api_key=os.getenv("VERA_LLM_API_KEY") or None,
        llm_base_url=os.getenv("VERA_LLM_BASE_URL") or None,
        llm_enabled=_bool("VERA_LLM_ENABLED", True),
        composer_model=os.getenv("VERA_COMPOSER_MODEL") or default_model,
        llm_max_concurrency=_int("VERA_LLM_MAX_CONCURRENCY", 10),
        llm_timeout_s=_float("VERA_LLM_TIMEOUT_S", 6.0),
        llm_effort=os.getenv("VERA_LLM_EFFORT") or default_effort,
        tick_deadline_s=_float("VERA_TICK_DEADLINE_S", 7.0),
        reply_deadline_s=_float("VERA_REPLY_DEADLINE_S", 5.0),
        repair_min_remaining_s=_float("VERA_REPAIR_MIN_REMAINING_S", 3.0),
        db_path=Path(db_path) if db_path else None,
        restore_window_s=_int("VERA_RESTORE_WINDOW_S", 7200),
        max_payload_bytes=_int("VERA_MAX_PAYLOAD_BYTES", 512_000),
        team_name=os.getenv("VERA_TEAM_NAME", "Amit Gautam"),
        team_members=[m.strip() for m in members.split(",") if m.strip()],
        contact_email=os.getenv("VERA_CONTACT_EMAIL", ""),
        submitted_at=os.getenv("VERA_SUBMITTED_AT") or _now_iso(),
    )
