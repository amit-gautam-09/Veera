# ADR-001: Python + FastAPI, one Uvicorn worker

**Status**: Accepted (M1) · **Date**: 2026-09-27

## Context
The bot is an HTTP service with five JSON endpoints, parallel outbound LLM calls, and state that must stay in one
place for the whole test window. The official simulator, dataset generator and SDK examples are Python.

## Options
| Option | For | Against |
|---|---|---|
| Python + FastAPI + Uvicorn (async) | Same language as the package; async fits parallel LLM calls; Pydantic validation built in | Needs care to avoid FastAPI's default 422 |
| Node + Express/Hono | Fast I/O, good SDK | Second language next to the Python tooling; no gain in quality |
| Python + Flask (sync) | Simple | Parallel LLM calls need threads; weaker typing story |

## Decision
Python 3.11+ (developed on 3.14), FastAPI, Uvicorn with **exactly one worker**, Pydantic v2. Tooling: pytest,
pytest-asyncio, hypothesis, ruff, mypy (strict on `compose/` and `reply/`). Logging uses the stdlib `logging`
module with a JSON formatter instead of structlog, which saves a dependency for the same output.

## Consequences
- All state lives in one process; horizontal scaling is out of scope (it is not needed at 10 req/s).
- Validation errors are mapped to the contract's 400 / safe responses by a custom handler.
- Everything else in the design (asyncio deadlines, task-based precompute) assumes one event loop.
