# ADR-006: Auto-reply detection by pattern and per-merchant repetition

**Status**: Accepted (M1) · **Date**: 2026-09-27

## Context
40–70% of production "merchant replies" are WhatsApp Business canned replies. The brief's hint is "same message
verbatim 3+ times"; the simulator sends one canned text four times on four *different* conversation ids for the
same merchant; the replay judge expects fast detection and a graceful exit. The API examples disagree on the
first response (`wait` 4 h in 2.5, one owner-directed `send` in 4.1).

## Options
| Option | Detects on | Wasted turns |
|---|---|---|
| Repetition per conversation only | Never in the simulator (each id seen once) | 4 |
| Repetition per merchant | 2nd occurrence | 1–2 |
| Pattern on first sight + repetition per merchant | 1st occurrence | 0–1 |
| LLM classification of every reply | 1st occurrence | Costs a call each time |

## Decision
Rules detect canned phrasing on first sight (English, Hinglish, Devanagari patterns) and a per-merchant counter
of normalised text hashes catches repeats across conversation ids. Policy: 1st → one short owner-directed
`send` restating the single ask; 2nd → `wait` 86400; 3rd+ → `end`.

## Consequences
- The simulator's auto-reply scenario ends on its third call.
- A merchant whose real reply happens to match a canned pattern gets one extra owner-directed line instead of
  a normal answer; acceptable.
