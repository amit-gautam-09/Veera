"""Request/response bodies (docs/05-api-contract.md, docs/03-backend-schema.md §2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Cta = Literal["open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"]
SendAs = Literal["vera", "merchant_on_behalf"]


class ContextPush(BaseModel):
    scope: str  # plain str so unknown scopes reach our own invalid_scope check
    context_id: str = Field(min_length=1)
    version: int = Field(ge=0)
    payload: dict[str, Any]
    delivered_at: str | None = None

    @field_validator("version", mode="before")
    @classmethod
    def _no_bool_or_float(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("version must be a non-negative integer")
        return value


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    now: str | None = None
    available_triggers: list[str] = Field(default_factory=list)


class TickAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str
    merchant_id: str
    customer_id: str | None
    send_as: SendAs
    trigger_id: str
    template_name: str
    template_params: list[str]
    body: str = Field(min_length=1)
    cta: Cta
    suppression_key: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    conversation_id: str = Field(min_length=1)
    message: str
    merchant_id: str | None = None
    customer_id: str | None = None
    from_role: str = "merchant"
    received_at: str | None = None
    turn_number: int | None = None


class ReplySend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["send"] = "send"
    body: str = Field(min_length=1)
    cta: Cta
    rationale: str


class ReplyWait(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["wait"] = "wait"
    wait_seconds: int = Field(ge=60)
    rationale: str


class ReplyEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["end"] = "end"
    rationale: str


ReplyResponse = ReplySend | ReplyWait | ReplyEnd
