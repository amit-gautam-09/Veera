# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
### Added
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
