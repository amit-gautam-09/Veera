"""FastAPI app: the six endpoints of docs/05-api-contract.md. No route can return 5xx."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from vera.api.schemas import ContextPush, ReplyRequest, ReplyWait, TickRequest
from vera.compose.models import ComposedMessage, Skip
from vera.config import Settings, load_settings
from vera.domain.ids import ack_id
from vera.observability.log import log_event, log_exception, setup_logging
from vera.planner.tick import plan_tick
from vera.store.sqlite import Database
from vera.store.state import SCOPES, Store

SAFE_WAIT = {"action": "wait", "wait_seconds": 3600, "rationale": "internal error; backing off"}


class Composer(Protocol):
    async def compose(self, trigger_id: str, deadline: float) -> ComposedMessage | Skip: ...
    def fallback(self, trigger_id: str) -> ComposedMessage | Skip: ...
    def on_context(self, scope: str, context_id: str) -> None: ...


class ReplyHandler(Protocol):
    async def handle(self, request: ReplyRequest) -> dict[str, Any]: ...


def _error(status: int, reason: str, details: str = "") -> JSONResponse:
    body: dict[str, Any] = {"accepted": False, "reason": reason}
    if details:
        body["details"] = details[:500]
    return JSONResponse(body, status_code=status)


async def _read_json(request: Request, limit: int) -> tuple[Any, str | None]:
    raw = await request.body()
    if len(raw) > limit:
        return None, "payload_too_large"
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "invalid_body"


def build_store(settings: Settings) -> Store:
    db = Database(settings.db_path) if settings.db_path else None
    store = Store(db)
    restored = store.restore(settings.restore_window_s)
    log_event("store.boot", restored=restored, counts=store.counts())
    return store


def _default_components(store: Store, settings: Settings) -> tuple[Composer, ReplyHandler]:
    from vera.compose.composer import Composer as PipelineComposer
    from vera.llm.gateway import make_gateway
    from vera.reply.engine import ReplyEngine

    gateway = make_gateway(settings)
    composer = PipelineComposer(store, gateway, settings.repair_min_remaining_s, settings.llm_timeout_s)
    return composer, ReplyEngine(store, gateway, settings.reply_deadline_s, min(settings.llm_timeout_s, 4.5))


def create_app(
    settings: Settings | None = None,
    store: Store | None = None,
    composer: Composer | None = None,
    replies: ReplyHandler | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    setup_logging()
    store = store if store is not None else build_store(settings)
    if composer is None or replies is None:
        default_composer, default_replies = _default_components(store, settings)
        composer = composer or default_composer
        replies = replies or default_replies
    started = time.monotonic()
    app = FastAPI(title="Vera", version=settings.version, docs_url=None, redoc_url=None)
    app.state.store, app.state.settings, app.state.composer = store, settings, composer

    @app.get("/v1/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "uptime_seconds": int(time.monotonic() - started), "contexts_loaded": store.counts()}

    @app.get("/v1/metadata")
    async def metadata() -> dict[str, Any]:
        return {
            "team_name": settings.team_name,
            "team_members": settings.team_members,
            "model": settings.composer_model if settings.llm_active else f"{settings.composer_model} (fallback mode)",
            "approach": "fact-sheet grounded LLM composer with deterministic fallback; rules-first reply state machine",
            "contact_email": settings.contact_email,
            "version": settings.version,
            "submitted_at": settings.submitted_at,
        }

    @app.post("/v1/context")
    async def push_context(request: Request) -> JSONResponse:
        try:
            data, err = await _read_json(request, settings.max_payload_bytes)
            if err:
                return _error(400, err)
            try:
                push = ContextPush.model_validate(data)
            except ValidationError as exc:
                return _error(400, "invalid_body", str(exc.errors(include_url=False)))
            if push.scope not in SCOPES:
                return _error(400, "invalid_scope", f"scope must be one of {', '.join(SCOPES)}")
            result = store.put_context(push.scope, push.context_id, push.version, push.payload)
            if not result.accepted:
                log_event("context.stale", scope=push.scope, context_id=push.context_id, version=push.version)
                return JSONResponse(
                    {"accepted": False, "reason": "stale_version", "current_version": result.current_version},
                    status_code=409,
                )
            composer.on_context(push.scope, push.context_id)
            return JSONResponse(
                {
                    "accepted": True,
                    "ack_id": ack_id(push.scope, push.context_id, push.version),
                    "stored_at": result.stored_at,
                }
            )
        except Exception as exc:  # noqa: BLE001 - route guard, never 5xx
            log_exception("context.error")
            return _error(400, "internal_error", type(exc).__name__)

    @app.post("/v1/tick")
    async def tick(request: Request) -> JSONResponse:
        try:
            data, err = await _read_json(request, settings.max_payload_bytes)
            if err:
                return JSONResponse({"actions": [], "error": err}, status_code=400)
            try:
                body = TickRequest.model_validate(data if isinstance(data, dict) else {})
            except ValidationError:
                body = TickRequest()
            actions = await plan_tick(store, body, composer.compose, composer.fallback, settings.tick_deadline_s)
            return JSONResponse({"actions": [a.model_dump() for a in actions]})
        except Exception:  # noqa: BLE001 - route guard, never 5xx
            log_exception("tick.error")
            return JSONResponse({"actions": []})

    @app.post("/v1/reply")
    async def reply(request: Request) -> JSONResponse:
        try:
            data, err = await _read_json(request, settings.max_payload_bytes)
            if err:
                return JSONResponse(SAFE_WAIT, status_code=400)
            try:
                body = ReplyRequest.model_validate(data)
            except ValidationError:
                return JSONResponse(ReplyWait(wait_seconds=3600, rationale="unreadable reply").model_dump())
            return JSONResponse(await replies.handle(body))
        except Exception:  # noqa: BLE001 - route guard, never 5xx
            log_exception("reply.error")
            return JSONResponse(SAFE_WAIT)

    @app.post("/v1/teardown")
    async def teardown() -> dict[str, bool]:
        store.wipe()
        log_event("store.teardown")
        return {"wiped": True}

    return app
