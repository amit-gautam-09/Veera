# ADR-005: Precompute compositions when triggers arrive

**Status**: Accepted (M1) · **Date**: 2026-09-27

## Context
A tick can carry up to 20 triggers and must answer within the simulator's 15 s (we budget 7 s). One composer
call takes a few seconds; 20 cold calls under a concurrency cap can exceed the budget. The harness pushes each
trigger context before the tick that lists it.

## Options
| Option | Latency at tick | Waste |
|---|---|---|
| Compose only at tick time | Worst case over budget → fallbacks | None |
| Precompute on trigger push (single-flight task per input hash) | Mostly cache hits | Compositions for triggers never listed |
| Also precompute on every merchant/category push | Same | Hundreds of calls at warmup for nothing |
| Ship a precomputed cache for the 100 base triggers | Zero for base triggers | Only helps if the judge reuses them unchanged |

## Decision
Precompute on trigger push, as `dict[input_hash → asyncio.Task]` (single flight), throttled by the LLM
semaphore and never awaited by the context handler. When a merchant, category or customer version changes,
re-schedule only the *unsent* triggers that depend on it (Phase 3 adaptation). At tick time, await existing
tasks up to the deadline; unfinished ones are cancelled and served by the fallback composer. Shipping a
precomputed base cache is optional work in M9.

## Consequences
- Warm ticks return in well under a second; cold ticks degrade to fallbacks rather than timeouts.
- Some LLM spend on triggers that are never listed; bounded by the number of pushed triggers.
