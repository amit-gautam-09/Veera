"""Composition result types shared by the planner, composer and reply engine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from vera.api.schemas import Cta, SendAs


class ComposedMessage(BaseModel):
    body: str
    cta: Cta
    send_as: SendAs
    customer_id: str | None
    suppression_key: str
    rationale: str
    template_name: str
    template_params: list[str]
    family: str
    kind: str
    path: Literal["cache", "llm", "repaired", "fallback", "stub"] = "fallback"
    input_hash: str = ""
    prompt_version: str = ""
    promised_deliverable: str | None = None


class Skip(BaseModel):
    reason: str
