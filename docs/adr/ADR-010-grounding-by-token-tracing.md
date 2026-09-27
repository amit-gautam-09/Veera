# ADR-010: Grounding by token-class tracing, not full entity recognition

**Status**: Accepted (M1) · **Date**: 2026-09-27

## Context
Fabricated data caps every dimension at 5. Messages are Hinglish with emoji, brand names (Google, WhatsApp,
Swiggy), festivals and category vocabulary, so a general proper-noun check would reject correct messages.

## Options
| Option | Precision | Recall on real fabrications |
|---|---|---|
| NER over the body, every entity must be in context | Low on Hinglish (false rejections) | High |
| LLM self-check ("did you invent anything?") | Unreliable | Medium |
| **Trace the risky token classes**: digit-runs, dates, ALL-CAPS acronyms, honorific+name, source phrases | High | High for the fabrications the judge penalises (numbers, citations, people, competitors) |

## Decision
Validator rules V6–V11 (06 §5) trace digits, dates, acronyms, named people and cited sources against an
allowed-token index built from the fact sheet (including code-derived values and, in replies, the merchant's own
message). Small effort integers ≤ 10 are allowed. On failure: drop the offending sentence, then one repair call if
≥ 3 s remain, then the fallback template.

## Consequences
- A fabricated brand name without a number or honorific can slip through; the prompt forbids it and the eval
  grounding auditor (LLM-assisted, offline) samples for it.
- Rendering every fact in several numeric forms (`2.1%`, `0.021`, `2`) is required so correct messages pass.
