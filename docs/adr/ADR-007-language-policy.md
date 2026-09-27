# ADR-007: Language policy by merchant region and customer preference

**Status**: Accepted (M1) · **Date**: 2026-09-27

## Context
Every merchant in the dataset lists `hi` in `identity.languages`; southern-city merchants also list `ta`, `te`
or `kn`. The FAQ says Hindi-English code-mix is encouraged where languages include `hi`; the judge checks that
language preference is honoured. Forcing Hinglish on a Chennai yoga studio reads as tone-deaf; pure English to a
Delhi pizza operator ignores the preference.

## Decision
- Merchant-facing: `hi` present and no southern language (`ta`, `te`, `kn`, `ml`) → natural Hinglish in Roman
  script. A southern language present → English-primary with at most one short Hindi phrase. No `hi` → English.
- Customer-facing: follow `identity.language_pref`: `hi` / `hi-en mix` → Hinglish; `en` / `english` → English;
  other mixes (`te-en`, `ta-en`, `kn-en`) → clear English, optionally a short correct greeting; never generated
  regional-language sentences.
- Replies mirror the language of the latest inbound message when it switches.
- Category `voice.code_mix` adjusts intensity (gyms: English-primary even in Hinglish mode).
- Script: Roman only; numbers in digits.

## Consequences
- Validator rule V15 enforces the directive.
- The policy is a heuristic; the rationale records which language was chosen and why.
