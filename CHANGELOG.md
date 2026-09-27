# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
### Added
- M7 evaluation: independent grounding auditor (`eval/grounding.py`) with a fabrication negative control,
  extended harness (`python -m eval.harness`) with offline checks and optional LLM judge + personas, adaptation
  tests for new digest items, perf updates and injected customers.
- M6 reply engine: rule classifier (English/Hinglish/Devanagari), state machine per `docs/09` (auto-reply
  ladder counted per merchant across conversation ids, opt-out/hostile exits with suppression, action-mode
  deliverables per trigger kind, off-topic decline + redirect, defer waits, soft-no, slot confirmation, reply
  after end), replay idempotency, per-turn language mirroring, optional `reply_v1` LLM phrasing with
  validation; replay suite R1–R14.
- M5 planner invariants P1–P8 as hypothesis property tests.
### Fixed
- Empty `middle` produced a `template_params` entry that was empty (invalid for WhatsApp templates) and a
  double space; V1 now requires all three parts and the thin review handler has a lead sentence.
- M4 LLM composer: `AnthropicGateway` (Sonnet 5, thinking disabled, structured output, no retries,
  concurrency cap), `composer_v1` prompt, content-hashed persistent cache, single-flight precompute on trigger
  push and on dependent version bumps, drop-sentence and one-call repair before the deterministic fallback;
  fake-gateway tests and tick latency tests.
- M3 deterministic composer: fact sheet with allowed-token index, per-kind playbook for all 26 kinds
  + generic handler (thin-payload, mismatch, consent and approval rules), validator V1–V17, English and Hinglish
  grounded wording; golden set of 38 snapshot-reviewed cases and unit tests for numbers, validator, salutation,
  language and consent.
- M2 contract skeleton: all six endpoints per `docs/05-api-contract.md` (400/409/500 KB, no 422/5xx),
  versioned context store with SQLite write-through and a restore window, tick planner (guards, ranking,
  per-merchant cap, deadline), stub composer and reply handler, `scripts/run_simulator.py` wrapper,
  contract and persistence tests.
- Repository bootstrap: reference package extracted to `reference/challenge/`, expanded dataset generated
  (5 categories, 50 merchants, 200 customers, 100 triggers, 30 test pairs), tooling (`pyproject.toml`, ruff,
  mypy, pytest, pre-commit), `.env.example`, `CLAUDE.md`.
- Documentation set (M1): context digest, PRD, TRD, backend schema, implementation plan, API contract +
  `openapi.yaml`, composer spec, trigger playbook (26 kinds), category voice guide, conversation policy,
  evaluation and test plan, deployment runbook, risk and ambiguity register, ADR-001…011.
