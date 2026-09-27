# ADR-004: Determinism through an input-hash compose cache

**Status**: Accepted (M1) · **Date**: 2026-09-27

## Context
The brief requires identical inputs to produce identical outputs. The composer model rejects `temperature`
(ADR-002), and even temperature 0 is not a byte-level guarantee.

## Options
| Option | Guarantee | Cost |
|---|---|---|
| Rely on temperature 0 | None on Sonnet 5 (param rejected); approximate elsewhere | — |
| Cache keyed by a hash of canonical inputs | Byte-identical for identical inputs, across restarts (persisted) | Hashing discipline |
| Deterministic templates only | Full | Much lower message quality |

## Decision
`input_hash = sha256(canonical_json({prompt_version, model, trigger(version, payload), merchant version,
category version, customer version, decision}))`, canonical JSON = sorted keys, compact separators, UTF-8.
Validated LLM outputs are stored in memory and SQLite (`compose_cache`). Conversation ids, ranking tie-breaks
and template parameters are derived from inputs, never from randomness or the wall clock. Reply outputs are
cached by conversation-state digest + inbound message + prompt version.

## Consequences
- Re-running a tick or `bot.py` on the same inputs reproduces the stored output.
- Any prompt edit bumps `prompt_version`, invalidating the cache on purpose.
- Fallback outputs are deterministic by construction and are not cached (a later identical request may get the
  LLM version); M4 checks whether this matters for the judge.
