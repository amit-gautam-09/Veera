# ADR-009: Code decides, the LLM writes three fields

**Status**: Accepted (M1) · **Date**: 2026-09-27

## Context
The judge scores decision quality (one best signal, right CTA, right recipient) and punishes fabrication and
contract errors. Letting the LLM choose facts, CTA types, template names and parameters puts every one of those
at the mercy of a sampling-free but still non-deterministic generator.

## Decision
Deterministic code builds the fact sheet, picks the family, primary signal, supporting facts, levers, CTA,
`send_as`, template name and language (the playbook registry, 07). The LLM returns only
`{opener, middle, ask}`; the rationale is generated in code from the decision (M4 change: it always matches the
body and saves output tokens). Code assembles `body` and `template_params = [opener, middle, ask]` against
the template `{{1}} {{2}} {{3}}`. The earlier idea of returning `used_fact_ids` was dropped: the validator traces
every token directly, which is stricter and cheaper.

## Consequences
- The CTA is always last by construction; contract fields are always valid.
- Decisions are unit-testable without an LLM; the fallback composer reuses the same decision.
- Prose quality depends on the prompt and fact rendering, which M4/M7 evaluate.
