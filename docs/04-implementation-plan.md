# 04 — Implementation Plan

Risk-ordered: contract correctness first (a malformed or slow bot scores nothing), then grounding (fabrication
caps every dimension at 5), then quality, then hardening. Each milestone lands on its own branch and PR
(ADR-011). Boxes are ticked in the same commit that lands the work.

```mermaid
flowchart LR
  M0[M0 bootstrap] --> M1[M1 docs] --> CP{{Checkpoint with Amit}} --> M2[M2 contract skeleton]
  M2 --> M3[M3 fact sheet + fallback] --> M4[M4 LLM composer + validator + cache]
  M4 --> M5[M5 tick planner] --> M6[M6 reply engine] --> M7[M7 eval harness]
  M7 --> M8[M8 hardening] --> M9[M9 packaging + deploy]
  M3 -.-> M6
```

## M0 — Ingestion and bootstrap
- [x] Clone/init, remote `origin`, bootstrap commit on `main`, branch `docs/m1-foundation`
- [x] Extract package into `reference/challenge/`, move challenge page and dossier into `reference/`
- [x] Run generator (`PYTHONUTF8=1`) → verified 5 / 50 / 200 / 100 / 30
- [x] `pyproject.toml`, ruff, mypy, pytest, pre-commit config, `.env.example`, `.gitignore`, `.gitattributes`
- [x] `CLAUDE.md` v0, `CHANGELOG.md`, smoke test (`tests/test_smoke.py`)
- **Accept**: generator counts verified; `ruff check`, `mypy`, `pytest` green. ✅

## M1 — Documentation set
- [x] 00 digest, 01 PRD, 02 TRD, 03 schema, 04 plan, 05 API contract + `openapi.yaml`
- [x] 06 composer spec, 07 trigger playbook, 08 voice guide, 09 conversation policy
- [x] 10 evaluation and test plan, 11 deployment runbook, 12 risk register, ADR-001…011
- [x] PR `docs/m1-foundation → main` opened (#1, merged); review checkpoint with Amit
- **Accept**: every B1–B11 and N-finding has a register entry and a TRD resolution; no case-study text in docs.

## M2 — Contract-correct skeleton (`feat/m2-skeleton`)
Depends on M1 approval.
- [x] `config.py` (env → settings, `.env` via python-dotenv)
- [x] `api/schemas.py` + `app.py`: all six endpoints, 500 KB guard on raw bytes, 400/409 semantics, custom
      validation handler (no 422), route guards (no 5xx), healthz counts from memory, metadata from env
- [x] `store/state.py` + `store/sqlite.py`: versioned ContextStore, conversations, suppressions, flags,
      write-through, restore window, teardown wipe
- [x] Stub composer: schema-valid actions from a fixed per-family template (placeholder for M3)
- [x] `scripts/run_simulator.py` wrapper (env config, UTF-8 mode, first-text-block patch, teardown first)
- **Tests**: contract suite (every `api-call-examples.md` case), restore-window unit tests
- **Accept**: contract suite green; simulator `warmup` and `all` run clean against localhost. ✅ (planner guards,
  ranking and per-merchant cap landed here too; M5 adds the property tests)

## M3 — Fact sheet and deterministic fallback (`feat/m3-facts-fallback`)
- [x] `compose/numbers.py` normalisation; `compose/facts.py` FactSheetBuilder with derived facts and the
      allowed-token index; `domain/salutation.py`, `domain/language.py`
- [x] `compose/playbook.py` + `merchant_kinds.py` + `customer_kinds.py`: registry for all 26 kinds + generic (07), consent gate + approval re-route,
      S-PERF / S-DIGEST / S-MISMATCH / S-SEASON rules
- [x] `compose/validator.py` V1–V17
- [x] Fallback wording per kind (English + Hinglish) inside the handlers, original wording
- [x] Golden set: 30 pairs + 8 uncovered kinds (38 cases), LLM disabled, snapshot-reviewed
- **Accept**: all 38 golden cases produce valid, grounded messages with the LLM off; grounding audit: zero
  untraceable tokens; similarity check clean. ✅ (sweep over all 100 triggers: 96 composed, 4 correct
  opt-out skips)

## M4 — LLM composer, repair loop, cache, precompute (`feat/m4-llm-composer`)
- [ ] `llm/gateway.py` (AsyncAnthropic, `max_retries=0`, semaphore, error mapping, token logging)
- [ ] `compose/prompts/composer_v1.txt`, `compose/composer.py` (structured output, thinking disabled)
- [ ] Drop-sentence → repair → fallback ladder; rationale rebuild on body change
- [ ] `compose/cache.py`: canonical hashing, persistent cache, precompute task registry, re-schedule on
      dependent version bumps
- [ ] Measure effort `low` vs default: latency p50/p99 and golden-set judge scores; record in CHANGELOG
- **Accept**: p99 tick < 8 s for 20 triggers cold, < 500 ms warm; zero validator escapes on the golden set.

## M5 — Tick planner (`feat/m5-planner`)
- [ ] `planner/tick.py`: resolve (listed only), guards with logged reasons, ranking, per-merchant cap, ≤ 20,
      deadline handling, commit
- **Tests**: hypothesis properties P1–P8 (10 §4)
- **Accept**: properties hold over 10k generated ticks; simulator `full_evaluation` completes with no timeouts.

## M6 — Reply engine (`feat/m6-replies`)
- [ ] `reply/classifier.py` rules (English, Hinglish, Devanagari), per-merchant auto-reply counter
- [ ] `reply/policy.py` state machine (09), lazy conversations seeded from history, replay cache
- [ ] `reply/composer.py` + `prompts/reply_v1.txt`, deterministic fallback replies, V17
- **Tests**: replay suite R1–R14
- **Accept**: replay suite 100%; simulator `auto_reply_hell`, `intent_transition`, `hostile` pass.

## M7 — Evaluation harness (`feat/m7-eval`)
- [ ] `eval/harness.py`: expanded dataset, incremental trigger pushes, persona-played reply turns, full-context
      LLM judge, grounding auditor, similarity checker, repetition checker, adaptation test, latency capture
- [ ] Results under `eval/results/<timestamp>/`; score row appended to `10` §13
- **Accept**: harness average ≥ 45/50; simulator `full_evaluation` average ≥ 45/50; no similarity above 0.6.

## M8 — Hardening (`feat/m8-hardening`)
- [ ] `scripts/soak.py` 10 req/s for 45 min; chaos cases (LLM timeouts, 429s, malformed contexts, unknown
      scopes/kinds/merchants, > 500 KB, out-of-order versions)
- [ ] Restart-recovery test (kill -9 mid-run, restart, compare state; outside the window → wiped)
- **Accept**: zero 5xx, zero timeouts, state intact after restart, teardown zeroes counts.

## M9 — Packaging and deployment (`feat/m9-release`)
- [ ] `Dockerfile` (single worker, non-root, HEALTHCHECK), host config (per checkpoint decision)
- [ ] `bot.py` (`compose(category, merchant, trigger, customer)`), `conversation_handlers.py`
      (`respond(state, message)`), `scripts/generate_submission.py` → `submission.jsonl` (30 lines)
- [ ] 1-page `README.md`; final docs pass; `CHANGELOG.md` release entry; version bump
- [ ] Optional: precomputed cache for the 100 base triggers
- [ ] `scripts/smoke_public_url.sh`; simulator against the public URL
- **Accept**: pre-flight checklist in `11-deployment-runbook.md` §10 fully green.

## Cross-cutting gates (every PR)
- `ruff check`, `mypy`, default `pytest` green; docs updated in the same PR when behaviour changes;
  no secrets (pre-commit `detect-private-key`); no case-study text (similarity check once it exists).
