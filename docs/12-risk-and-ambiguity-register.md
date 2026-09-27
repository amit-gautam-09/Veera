# 12 — Risk and Ambiguity Register

Every contradiction, assumption and risk found while reading the package, with the resolution we chose.
IDs are stable; other docs cite them. **Status**: `resolved` (decided, reflected in the design), `open`
(needs Amit's call), `watch` (accepted risk, monitored).

## A. Contradictions in the challenge material
| ID | Issue | Evidence | Resolution | Status |
|---|---|---|---|---|
| R-01 | Re-posting the same context version: "no-op" vs 409 | testing-brief §2.1 says no-op; api-call-examples 1.5 returns 409 `stale_version` | Return 409 for same **or** lower version; state untouched (a no-op on state), healthz unchanged | resolved |
| R-02 | URLs "allowed when they add value" vs −3 per URL hard fail | challenge-brief §5.4 and FAQ vs api-call-examples F.4 | Never put URLs in bodies; validator V3 rejects them | resolved |
| R-03 | Timeouts: 30 s official vs 15 s tick/reply, 10 s context, 5 s healthz in the simulator | testing-brief §5; `judge_simulator.py` L413–434; api-call-examples table says 10 s / 5 s / 2 s | Design to the strictest: tick deadline 7 s, reply 5 s, context/healthz memory-only | resolved |
| R-04 | Rubric names "trigger relevance" vs "decision quality" | challenge-brief §8 vs challenge page and simulator (`decision_quality`, falls back to `trigger_relevance`) | Satisfy both: every message states *why now* and is built on one chosen signal; rationale names the choice | resolved |
| R-05 | Timeline inconsistencies | Priya `last_visit` 2026-05-12 while scenarios are ~2026-04-26; Diwali `days_until: 188`; DCI circular dated 2026-11-04 in a W17 digest; generated customers all `last_visit` 2026-04-01 | Never derive durations from `now` or mix dates; quote explicit payload dates; use a payload's own duration field (e.g. `days_remaining`) verbatim | resolved |
| R-06 | Trigger expiry vs simulator clock | simulator sends wall-clock `now` (today 2026-09-27); dataset `expires_at` Apr–Jun 2026 | Only triggers in `available_triggers` are candidates; `expires_at` is never compared with `now` (used only to order candidates) | resolved |
| R-07 | First auto-reply response: `wait` 14400 vs `send` owner line | api-call-examples 2.5 vs 4.1 | `send` one owner-directed line on the first canned reply, `wait` 86400 on the second, `end` on the third (09 §3); tests accept either `send` or `wait` on turn 1 | resolved |
| R-08 | Taboo key name | testing-brief §3.1 uses `voice.taboos`; dataset and simulator use `voice.vocab_taboo` | Read both keys and union them | resolved |
| R-09 | CTA shape: "binary YES/STOP for action triggers" vs examples using `open_ended` | challenge-brief §5.3 vs api-call-examples 2.2 | Playbook assigns CTA per family (07 §1.3); binary for action asks, `open_ended` for curiosity/asking-the-merchant | resolved |
| R-10 | Digest vs trigger facts disagree | atorvastatin: digest "manufacturer X", trigger `MfrZ` | Trigger payload wins for event facts; never blend both in one message | resolved |
| R-11 | Multiple messages per merchant per tick | FAQ allows one per `(merchant, conversation)`; restraint is rewarded | At most one new merchant-facing conversation per merchant per tick; others stay eligible for later ticks | resolved |

## B. Harness behaviour that shapes the design
| ID | Finding | Evidence | Resolution | Status |
|---|---|---|---|---|
| R-12 | Placeholder triggers (75/100; 13/30 test pairs) | `generate_dataset.py` L277–279 | Thin-payload strategy per kind (07); validator blocks invented specifics; placeholder perf triggers must match the sign of a real `delta_7d` or reframe | resolved |
| R-13 | Kind/category mismatch (e.g. `chronic_refill_due` for a dentist's customer) | generator assigns kinds to random merchants | Reinterpret per category or stay silent; rationale says which (07) | resolved |
| R-14 | Sparse generated merchants (no offers, history, signals) | `expand_merchants` | Fact ranking uses what exists: performance, deltas, peer gaps, locality, digest, seasonal beats, catalog suggestions | resolved |
| R-15 | Replies arrive on conversation ids the bot never created | simulator `conv_auto_1..4`, `conv_intent_1`, `conv_hostile` | Lazy conversation bound to `merchant_id`, seeded from `conversation_history`; auto-reply counted per merchant | resolved |
| R-16 | Keyword intent check | simulator L740–749 | Action mode delivers the artefact with a confirm CTA; V17 bans the five qualifying phrases in action mode | resolved |
| R-17 | Hostile check | simulator L776–781 | `end` on stop+hostile; one apology (contains "sorry") on hostility without stop | resolved |
| R-18 | Simulator uses seed files; harness uses expanded set | simulator L60, L359–380 | Test against both (10) | resolved |
| R-19 | Simulator never pushes customers; warmup pushes only 5 merchants | simulator `_warmup`, `_full` | Customer-scoped triggers without a customer context re-route to a merchant-facing approval message; missing merchant → skip | resolved |
| R-20 | Scorer sees only part of the context | simulator L504–530 | Prefer judge-visible facts for the primary hook; attribute deeper facts in-body (06 §2.2) | resolved |
| R-21 | Simulator penalties are never computed; "all" scenario scores nothing | `ScoreResult.penalties` never set; `_all` has no scoring | Use `full_evaluation` for scores; our harness computes penalties itself (10) | resolved |
| R-22 | Simulator on Windows: `json.load(open(f))` mojibakes ₹ into pushes; `█` crashes piped cp1252 stdout | simulator L105, L364, L374 | Always run under `PYTHONUTF8=1` via `scripts/run_simulator.py`; our code always passes `encoding="utf-8"` | resolved |
| R-23 | Simulator's Anthropic default model is retired, and it reads `content[0]["text"]` | simulator L187, L206 | Wrapper sets the model and patches the provider to read the first text block (Sonnet 5 may return a thinking block first) | resolved |
| R-24 | Simulator config is hard-coded | simulator L24–39 | Wrapper sets module globals from env; the vendor file is never edited or committed with keys | resolved |
| R-25 | `localhost` on Windows adds IPv6 fallback delay | observed behaviour | Use `http://127.0.0.1:8080` locally | resolved |
| R-26 | 8 kinds never appear in the 30 test pairs | generator `write_test_pairs` takes 2 per kind alphabetically | Golden set adds one trigger per missing kind (10) | resolved |

## C. Model and platform
| ID | Risk | Resolution | Status |
|---|---|---|---|
| R-27 | `temperature=0` is rejected (400) on `claude-sonnet-5` | No sampling params; determinism from the compose cache keyed by input hash (ADR-004) | resolved |
| R-28 | Sonnet 5 runs adaptive thinking when `thinking` is omitted → latency | Send `thinking={"type": "disabled"}`; measure effort in M4 | resolved |
| R-29 | SDK default timeout 10 min with 2 retries (timeouts retried) | `AsyncAnthropic(max_retries=0)`, per-call timeout = remaining deadline | resolved |
| R-30 | Anthropic rate limits with 20 parallel composes + reply calls | Concurrency cap 10 (configurable); 429 → immediate fallback; precompute on push spreads load | watch |
| R-31 | LLM outage during the test window | Deterministic fallback composer and replies; `VERA_LLM_ENABLED=false` kill switch | resolved |
| R-32 | LLM cost overrun | Token usage logged per call; concurrency cap; console spend limit (11) | watch |
| R-33 | Separate classifier model | Dropped: rules classify; one merged reply call classifies-and-composes when rules are inconclusive (saves a round trip) | resolved |

## D. State, persistence, operations
| ID | Risk | Resolution | Status |
|---|---|---|---|
| R-34 | Restart mid-test loses pushed context (judge does not re-push) | Write-through SQLite, reload on boot (spec B11) | resolved |
| R-35 | Persisted state from an earlier run inflates warmup healthz counts (expects 5/50/200/0) and carries opt-out/auto-reply flags | **Restore window**: reload on boot only if the last write is < `VERA_RESTORE_WINDOW_S` (2 h) old, else wipe; teardown wipes; runbook requires teardown before submission (ADR-003) | resolved — Amit to confirm (deviation from plain B11) |
| R-36 | Judge runs a second slot against the same live process without teardown | Stale suppression keys would block resends and trigger counts would be off. Mitigation: teardown is optional for the judge, so the runbook keeps the process idle and wiped before the window; accepted residual risk | watch |
| R-37 | Healthz failures (3 consecutive = disqualification) | Memory-only handler; always-on host with no sleep; uptime monitor | resolved |
| R-38 | Multi-worker deployment would split state | Single uvicorn worker enforced in Dockerfile and runbook | resolved |
| R-39 | Deploy region latency: India host → US LLM endpoint adds ~200–250 ms per call | Benchmark `bom` vs a US region before the final deploy (11) | watch |

## E. Content and compliance
| ID | Risk | Resolution | Status |
|---|---|---|---|
| R-40 | Case-study plagiarism check | No case-study text in prompts/fixtures/templates; V14 similarity check in CI and the harness | resolved |
| R-41 | Fabrication (caps every dimension at 5) | Fact sheet + digit/date/name/source validators + fallback built only from facts | resolved |
| R-42 | Consent: generated customers only have `promotional_offers` | Consent gate on existence/opt-in; scope changes framing, not eligibility (ADR-008) | resolved |
| R-43 | Names inside ids and composite names ("Aanya (parent: Sneha)", "(walk-in, no profile)") | Never derive names from ids; address the parent; walk-ins get no customer send | resolved |
| R-44 | `owner_first_name` already contains "Dr." for generated dentists | Salutation normaliser strips then re-applies the honorific | resolved |
| R-45 | Every merchant lists `hi` | Regional language policy (ADR-007): Hinglish unless a southern language is listed | resolved |
| R-46 | Due-diligence dossier facts leaking into messages | The dossier is never loaded by the bot; it is PRD background only | resolved |

## F. Decisions that need Amit
| ID | Question | Recommendation | Status |
|---|---|---|---|
| R-47 | Hosting provider | Fly.io (always-on machine, volume, remote builds, `bom` region) — see 11 | open |
| R-48 | Anthropic API key and spend cap for dev + eval + test window | One key in `.env` locally and in host secrets; set a console spend limit | open |
| R-49 | Public repo contains the challenge package and the dossier | Challenge package is public anyway; confirm the dossier may be public or move it out of the repo | open |
| R-50 | `/v1/metadata` identity | `team_name` and `team_members` = "Amit Gautam"; contact email to confirm | open |
| R-51 | Restore-window persistence instead of unconditional reload (R-35) | Keep the restore window | open |
