# ADR-003: In-memory state, SQLite write-through, restore window on boot

**Status**: Accepted (M1) — deviation from spec B11 flagged for Amit (R-51) · **Date**: 2026-09-27

## Context
The judge pushes 255 contexts once at warmup and never re-pushes. A process restart mid-test without persistence
loses everything. The opposite failure also exists: warmup expects `contexts_loaded` of 0/0/0/0 before pushes and
exactly 5/50/200/0 after; persisted state from an earlier run (local tests, a previous slot) would inflate those
counts and carry opt-out and auto-reply flags forward. The testing brief also asks that no context data persist
after the test.

## Options
| Option | Mid-test crash | Stale state on a later start | Complexity |
|---|---|---|---|
| Memory only | Lost | Never | Lowest |
| SQLite write-through, always reload (spec B11) | Recovered | Inflated counts, stale flags | Low |
| SQLite write-through, **reload only if last write is recent** | Recovered | Wiped | Low + one check |
| External store (Redis/Postgres) | Recovered | Same issue | New service |

## Decision
Memory is the source of truth for reads; every accepted write goes to SQLite (WAL, `synchronous=NORMAL`) in the
same step. On boot, if `meta.last_write_at` is within `VERA_RESTORE_WINDOW_S` (default 7200 s), everything is
reloaded; otherwise the tables are wiped. `/v1/teardown` wipes memory and tables. The SQLite file sits on the
host's persistent volume.

## Consequences
- A crash or platform restart during the 60-minute window restores state within milliseconds of boot.
- A fresh start hours later begins empty, so warmup counts are exact.
- Residual risk: a second judge slot against the *same running process* without teardown still sees old state
  (R-36); the runbook requires a teardown before the judging window.
