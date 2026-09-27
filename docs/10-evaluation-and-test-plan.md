# 10 — Evaluation and Test Plan

| | |
|---|---|
| Owner | Amit Gautam |
| Status | Draft v1 (M1) |
| Related | `01-PRD.md` §5–7 (FR/NFR/targets), `02-TRD.md`, `05-api-contract.md`, `09-conversation-policy.md` |

Every FR and NFR in the PRD maps to at least one suite below. Suites that call a real LLM cost money, need
`ANTHROPIC_API_KEY`, and are opt-in via the `llm` pytest marker. Everything else runs offline with a fake
LLM gateway and is part of the default `pytest` run.

## 1. Test pyramid
| Suite | Location | What it proves | Tool | Gate |
|---|---|---|---|---|
| Unit | `tests/unit/` | Fact extraction, number normalisation, validator rules, classifier rules, salutation, language choice, id formats | pytest | M2–M6 |
| Contract | `tests/contract/` | Every example in `api-call-examples.md`; status codes; required fields; limits | pytest + FastAPI `TestClient` | M2 |
| Property | `tests/property/` | Planner and store invariants over random inputs | hypothesis | M5 |
| Golden | `tests/golden/` | 38 fixed compositions (30 test pairs + 8 uncovered kinds) stay grounded and reviewed | pytest snapshots (JSON files) | M3, M4 |
| Grounding audit | `eval/grounding.py` (+ `tests/golden/`) | Every digit-run, date, acronym, honorific+name and source phrase in a body traces to a fact | own code | M3, M4, M7 |
| Replay | `tests/replay/` | Multi-turn conversation policy (auto-reply, intent, hostile, off-topic, slots…) | pytest | M6 |
| Adaptation | `tests/replay/test_adaptation.py` + `eval/harness.py` | A version bump changes the next composition | pytest / harness | M4, M7 |
| Latency | `tests/perf/` | Deadline logic and p99 budgets with a fake LLM of known delay | pytest + `time.perf_counter` | M4, M5 |
| Soak / chaos | `scripts/soak.py`, `tests/chaos/` | 10 req/s for 45 min; LLM timeouts/429s; hostile inputs | asyncio + httpx | M8 |
| Restart recovery | `tests/chaos/test_restart.py` | State restored within the restore window; wiped outside it; teardown zeroes counts | pytest + subprocess | M8 |
| Local simulator | `scripts/run_simulator.py` | Official `judge_simulator.py` runs clean with a non-trivial score | wrapper | M2 (warmup), M7 (score) |
| Extended harness | `eval/harness.py` | Full expanded dataset, reply turns, LLM judge with full context | own driver | M7 |

Markers (declared in `pyproject.toml` when the suites land): `llm` (real API calls), `slow` (> 10 s),
`soak` (45-minute run). Default `pytest` excludes all three.

## 2. Unit tests
**Fact extraction (`compose/facts.py`)**
- Each category/merchant/customer/trigger field used by the playbook yields a fact with id, value, source path
  and rendered forms; missing optional fields yield no fact (never `None` rendered into text).
- Ratios pre-render: `ctr: 0.021` → `2.1%` and `2`; `delta_pct: -0.50` → `50%`, `-50%`, `50`; peer comparison
  facts computed in code (`0.030 - 0.021` → `0.9` points; `62 / 28` → `2.2x`).
- Placeholder trigger (`payload.placeholder == true`) produces zero trigger-payload facts.
- Digest resolution: `payload.top_item_id` / `digest_item_id` / `alert_id` resolve to the digest item; an id not
  in the digest yields no digest fact and a logged warning.
- Trigger-payload event facts win over conflicting digest text (atorvastatin `MfrZ` vs "manufacturer X").

**Number normalisation (`compose/numbers.py`)**
- Table-driven: `2,410` = `2410`; `₹1,499` = `Rs 1499` = `INR 1,499` = `1499`; `1.2 lakh` = `120000`;
  `3.2k` = `3200`; `38%` = `0.38` fact; `-60%` matches `cold_cough_demand_-60`.
- Digit-runs inside identifiers are extracted as whole tokens: `AT2024-1102` → `2024`, `1102`.
- Times: `6pm`, `18:00`, `6:00 PM` all normalise to the same slot token when a payload slot has that time.

**Validators (`compose/validator.py`)** — one positive and one negative case per rule:
| Rule | Must reject | Must accept |
|---|---|---|
| Digit-run traced | "31 of your patients" with no 31 in facts | "78 patients" when `lapsed_180d_plus: 78` |
| Small integers | — | "3 posts", "2-min", "reply 1 or 2" (≤ 10) |
| Dates from payload only | "on 12 Oct" with no such date | "15 Dec 2026" from `deadline_iso` |
| No derived durations | "in 188 days" / "in 34 days" | explicit date |
| ALL-CAPS acronyms | "FDA approved" when FDA not in context | "DCI", "IOPA", "GBP", "ORS" |
| Honorific + name | "Dr. Sharma" not in context | "Dr. Meera" (owner) |
| Source phrases | "per a Lancet trial" | "JIDA Oct 2026, p.14" |
| Taboo phrases (parenthetical stripped) | "guaranteed", "best price" | "price from your offer list" |
| snake_case jargon | "ctr_below_peer_median" | "CTR below the peer median" |
| URLs | "magicpin.com/x", "https://…", "www." | — |
| Single CTA in `ask` | two questions in `ask`; question in `middle` | one question at the end |
| No repeat | body equal to a previous body to this merchant | new body |
| Case-study similarity | `difflib` ratio > 0.6 vs any case-study body | our own wording |
| Replies: inbound numbers | — | echoing "₹249" the merchant just typed |
- Failure ladder: an untraceable middle sentence is dropped when the remainder still has a hook and the ask;
  otherwise one repair call; otherwise family template. Rationale is regenerated in code when the body changed.

**Classifier rules (`reply/classifier.py`)** — table of ≥ 60 labelled messages (English, Hinglish, Devanagari):
auto-reply ("Thank you for contacting…", "Our team will respond shortly", "aapki jaankari ke liye shukriya…
team tak pahuncha", "main ek automated assistant hoon"), opt-out ("stop", "mat bhejo", "band karo"),
hostile without stop ("useless", "bakwas"), accept ("ok lets do it", "haan kar do", "👍") *only* when the last
bot turn was a proposal, defer ("busy, call later", "baad mein", "kal"), off-topic ("GST filing", "ITR"),
question, slot selection ("2", "Wed works", "Sat?"), unclear. Each row asserts the class; ambiguous rows assert
`needs_llm`.

**Salutation (`domain/language.py`)**: `owner_first_name: "Dr. Asha"` → "Dr. Asha" (not "Dr. Dr. Asha");
dentist "Meera" → "Dr. Meera"; missing owner → merchant name; customer "Aanya (parent: Sneha)" → addresses
Sneha; "(walk-in, no profile)" → customer send blocked.

**Language (`domain/language.py`)**: `["en","hi"]` Delhi → Hinglish; `["en","hi","ta"]` → English-primary;
customer `hi-en mix` → Hinglish; `te-en mix` / `kn-en mix` → English; inbound in Devanagari or Hinglish → reply
in Hinglish for that turn.

**Ids**: `conversation_id` matches `^conv_[a-z0-9]+_[a-z_]+_\d{8}_[0-9a-f]{6}$`, is stable for identical
inputs, and differs across triggers; `ack_id` is `ack_{scope}_{context_id}_v{version}`.

## 3. Contract tests
One test per example in `reference/challenge/examples/api-call-examples.md`, asserting status code and
response shape (field names, types, enums). Policy content is asserted by the replay suite, not here.

| Example | Assertion |
|---|---|
| 1.1 healthz before pushes | 200, all four counts 0 |
| 1.2 metadata | 200, all seven fields present, `team_members` is a list |
| 1.3 / 1.4 category, merchant push | 200, `accepted: true`, `ack_id`, `stored_at` |
| 1.5 same version re-push | 409, `reason: stale_version`, `current_version: 1`; state unchanged |
| 1.6 version bump | 200; stored payload now has `views: 2580` |
| 1.7 healthz after warmup | counts exactly 5/50/200/0 after pushing the expanded dataset |
| 2.1 trigger push | 200; trigger count +1 |
| 2.2 tick with a live trigger | 200; one action with all 11 fields; `send_as` / `cta` in enums |
| 2.3 tick with nothing worth sending | 200, `{"actions": []}` |
| 2.4 engaged reply | 200, `action: send`, non-empty body, `cta` in enum |
| 2.5 auto-reply (no `merchant_id` in body) | 200 (never 422); `send` or `wait` (sequence per `09`) |
| 2.6 hard no | 200, `action: end` |
| 2.7 GST curveball | 200, `action: send`, body declines and returns to topic |
| 2.8 category v2 | 200; next compose for m_001 can cite `d_2026W17_dci_radiograph_NEW` |
| 2.9 customer push + recall tick | action has `send_as: merchant_on_behalf`, `customer_id` set |
| 4.1–4.3 replay shapes | covered in §8; here only shape |
| F.2 malformed action | our tick never emits an action missing any required field (asserted on every tick in every suite via a shared helper) |
| F.4 URL | no body in any suite contains a URL (shared helper) |
| F.5 repetition | no body repeats within a merchant (shared helper) |

Plus: invalid JSON → 400; unknown scope → 400 `invalid_scope`; `version: -1` / `"2"` → 400 `invalid_body`;
body of 500 KB + 1 byte → 400 `payload_too_large`; exactly 500 KB → 200; tick with 25 live triggers → ≤ 20
actions; two ticks never share a `conversation_id`; `/v1/reply` with only `conversation_id` + `message` → 200;
teardown → counts 0.

## 4. Property-based tests (hypothesis)
Strategy: the real expanded dataset (all 100 triggers) with random opt-out flags on up to 8 merchants and
random tick sequences (1–6 ticks of up to 40 ids drawn from the triggers plus random unknown strings), run
through the deterministic composer. P7 uses random push sequences over a small key space. 40 examples per
property (`tests/property/test_planner_props.py`).
- **P1** every tick returns ≤ 20 actions.
- **P2** no `conversation_id` appears twice across all ticks of a run.
- **P3** no `suppression_key` is sent twice across a run.
- **P4** no action targets a merchant flagged opted-out/hostile, or a customer whose send is blocked by consent.
- **P5** at most one merchant-facing (`send_as: vera`) action per merchant per tick.
- **P6** every action passes the shared shape helper (11 fields, enums, non-empty body/rationale).
- **P7** context store: for any sequence of pushes, stored version per key is the max accepted; every push with
  version ≤ stored returns 409 and leaves the payload byte-identical; healthz counts = distinct keys.
- **P8** determinism: the same store + tick sequence replayed on a fresh app yields byte-identical responses.

## 5. Golden set
38 cases: the 30 pairs in `reference/challenge/expanded/test_pairs.json` plus one trigger for each kind absent
from the pairs — `research_digest` (trg_001), `renewal_due` (trg_005), `review_theme_emerged` (trg_011),
`seasonal_perf_dip` (trg_014), `supply_alert` (trg_018), `trial_followup` (trg_017),
`wedding_package_followup` (trg_007), `winback_eligible` (trg_009).
- One snapshot file, `tests/golden/snapshots.json`, keyed by case id: `{trigger_id, cta, send_as, body}` (or
  `{skip: reason}`).
- Mode: `fallback` (LLM disabled). An `llm` mode over cached outputs is added once real-model runs exist.
- Any snapshot diff fails the test; updating requires `UPDATE_GOLDEN=1 pytest tests/golden` and a human read of
  the diff (commit message says which cases changed and why).
- Every golden body must pass the grounding audit and the case-study similarity check.

## 6. Grounding audit
`eval/grounding.py` takes a composed message plus the exact contexts it was composed from and reports every
token that is not traceable, by class (digit-run, date, acronym, honorific+name, source phrase, taboo, jargon,
URL). It reuses the validator's normalisation but runs independently of it (same rules, separate entry point),
so a validator bug that lets a token through is still caught in eval. Target: 0 findings across golden,
harness and simulator runs.

## 7. Latency benchmarks
Fake LLM gateway with a configurable delay distribution; real clock.
| Test | Setup | Pass |
|---|---|---|
| Cold tick, 20 triggers | fake delay 4 s ± 1 s, concurrency 10 | p99 < 8 s over 20 runs; all 20 actions valid (LLM or template) |
| Slow LLM | fake delay 12 s | tick returns by 7 s deadline + 0.5 s; every action is a template |
| Repair budget | first call fails validation at 5 s elapsed | no repair attempted (< 3 s left); template used |
| 429 | fake raises `RateLimitError` | template immediately, no retry |
| Warm tick | precompute finished | p99 < 500 ms |
| Reply | fake delay 3 s | p99 < 6 s |
| Context push / healthz / metadata | 255 base pushes | p99 < 200 ms each; push never awaits the LLM |
Real-LLM variant (`-m llm`): same cold-tick test against `claude-sonnet-5` with `thinking={"type":"disabled"}`,
once at default effort and once at `effort: "low"`; record p50/p99 and golden-set judge score for both and
pick the setting in M4 (result recorded in §12 and the composer spec).

## 8. Replay suite (`tests/replay/`)
Runs through the HTTP app with the fake LLM (deterministic) and again under `-m llm`.
| # | Scenario | Input | Expected |
|---|---|---|---|
| R1 | Auto-reply hell | same canned text on `conv_auto_1..4`, same merchant, turns 2–5 | turn 2 `send` (one owner-directed line, one CTA), turn 3 `wait` 86400, turn 4 `end`, turn 5 `end` |
| R2 | Intent transition | after one proposal: "Ok lets do it. Whats next?" | `send`; body contains the draft/next step and one of done/sending/draft/here/confirm/proceed/next; none of "would you", "do you", "can you tell", "what if", "how about"; `cta: binary_confirm_cancel` |
| R3 | Hostile + stop | "Stop messaging me. This is useless spam." | `end`; merchant suppressed; next tick sends nothing to this merchant |
| R4 | Abuse without stop | "This is useless." | one short apology `send` with no pitch and a stop option; no offer text |
| R5 | Off-topic | "Btw can you also help me with my GST filing this month?" | `send`: one-line decline (CA), back to the original topic, exactly one CTA |
| R6 | Defer | "busy right now, call later" | `wait` with 1800 ≤ `wait_seconds` ≤ 86400 |
| R7 | Language switch | English thread, merchant replies "haan theek hai, bhej do" | reply in Hinglish (Roman script) |
| R8 | Customer slot | recall with 2 payload slots; customer "2", then separately "Wed works" | confirms the exact slot label from payload |
| R9 | Unknown slot | customer "Friday 8pm?" not in payload | no invented availability; "we'll confirm" phrasing |
| R10 | Three unanswered | three ticks each open a conversation with the same merchant and no genuine reply arrives | the fourth tick skips that merchant with reason `unanswered_3` (09 §3 counters) |
| R11 | Reply after end | GST question on a conversation ended by opt-out | polite decline, no pitch; merchant remains suppressed for proactive sends |
| R12 | Idempotent replay | identical reply request sent twice | byte-identical response; counters advance once |
| R13 | Unknown conversation | reply on an id the bot never issued | 200, handled with lazily created state bound to `merchant_id` |
| R14 | Question we can't answer | "What's my competitor's rating?" | admits it doesn't have that; offers the nearest grounded fact + one next step |

## 9. Adaptation tests
1. Push expanded dataset; push trigger `trg_002` (DCI); tick → message A.
2. Push `dentists` category v2 with a new digest item and merchant m_001 v2 with new performance numbers.
3. Push a new trigger for m_001 that references the new digest item; tick → message B.
- Assert B cites the new item's source/numbers and uses v2 performance values; A's facts that changed do not
  reappear; no v1-only numbers in B.
- Assert an unsent trigger whose merchant was bumped is re-composed (its cached composition invalidated).
- Customer injection: push a new customer + `recall_due` 2 minutes (simulated) later → customer-facing action
  honouring that customer's `language_pref`.

## 10. Soak, chaos, restart
**Soak** (`scripts/soak.py`, `-m soak`): 10 req/s mixed traffic for 45 minutes against a local server with the
fake LLM (and a 5-minute real-LLM variant). Pass: 0 5xx, 0 responses slower than the endpoint budget, RSS growth
< 50 MB, healthz counts correct at the end.

**Chaos** (`tests/chaos/`): LLM timeout on every call; intermittent 429s; LLM returning invalid JSON / empty
text / a refusal stop reason; malformed context payloads (wrong types, missing identity, `payload: []`);
unknown scope; unknown trigger kind; trigger for an unknown merchant; customer for an unknown merchant;
payload > 500 KB; out-of-order versions (v3 then v2); 50 concurrent pushes to the same key. Pass: no 5xx, every
tick/reply response valid, fallback used and logged, store consistent.

**Restart recovery** (`tests/chaos/test_restart.py`): start server as a subprocess, push the base dataset + a
few triggers + a conversation, kill -9, restart.
- Within `VERA_RESTORE_WINDOW_S`: counts, conversations, suppressions and auto-reply counters restored; next
  tick does not resend suppressed keys.
- DB last write older than the window (clock injected via env): state wiped; healthz 0/0/0/0.
- `POST /v1/teardown` → memory and DB wiped; restart comes up at 0/0/0/0.

## 11. Local simulator wrapper
`judge_simulator.py` is never edited. `scripts/run_simulator.py`:
1. Sets `PYTHONUTF8=1` semantics (re-execs itself with `-X utf8` if needed) so seed JSON with `₹` is read as
   UTF-8 and the `█` score bar doesn't crash a piped cp1252 stdout.
2. Calls `POST {BOT_URL}/v1/teardown` so stale state can't skew warmup.
3. Imports `reference/challenge/judge_simulator.py` as a module and sets `BOT_URL`, `LLM_PROVIDER`,
   `LLM_API_KEY`, `LLM_MODEL`, `TEST_SCENARIO` from env (`BOT_URL`, `JUDGE_LLM_PROVIDER`,
   `JUDGE_LLM_API_KEY`, `JUDGE_LLM_MODEL`, `JUDGE_SCENARIO`; a `--scenario` flag overrides the env value).
4. Monkeypatches `AnthropicProvider.complete` to return the first `text` block (the stock code reads
   `content[0]["text"]`, which raises when Sonnet 5 returns a thinking block first and silently drops to the
   digit-counting fallback scorer).
5. Runs `main()`.

Known limits of the simulator (so we don't over-read its numbers): loads seed files only; warmup pushes only
the first 5 merchants; never pushes customers; never calls `/v1/reply` after ticks; never computes penalties;
scorer sees only a subset of context; default scenario `all` scores nothing — use `full_evaluation` for
scores and `all` for the reply checks. Use `BOT_URL=http://127.0.0.1:8080` on Windows (`localhost` tries IPv6
first and adds ~1–2 s per call).

## 12. Extended harness (`eval/harness.py`)
Closer to the real judge than the simulator.
- **Push**: expanded dataset (5/50/200) at warmup, assert healthz; triggers pushed incrementally per simulated
  5-minute tick; mid-run v2 category digests and v2 merchant performance (adaptation).
- **Tick set**: the 30 test-pair triggers, the 8 uncovered kinds, and adversarial variants: placeholder
  payloads on seed merchants, kind/category mismatches, a customer with no consent, a trigger for an unknown
  merchant, 25 triggers in one tick, duplicate suppression keys.
- **Merchant personas** (LLM, `claude-haiku-4-5-20251001`, one prompt per persona, given the merchant context
  and the bot's message): *engaged* (asks for the deliverable, then says yes), *auto-reply* (returns one fixed
  canned line every turn), *hard no* (declines, then asks to stop), *curveball* (asks an off-topic question, then
  a question the context can't answer), *Hindi switch* (replies in Hinglish/Devanagari). Up to 5 turns each.
- **Judge**: `claude-sonnet-5`, same five-dimension rubric and JSON shape as the simulator's scorer, but the
  prompt includes the *full* contexts, the rationale and the transcript, and adds two checks: rationale matches
  body; fabrication (list any untraceable claim). Output per message:
  `{"specificity": n, "category_fit": n, "merchant_fit": n, "decision_quality": n, "engagement_compulsion": n,
  "fabrications": [...], "rationale_matches": bool, "reasons": {...}}`; per conversation:
  `{"auto_reply_detected_turn": n|null, "intent_handled": bool, "exit_graceful": bool, "on_mission": bool}`.
- **Checks run alongside**: grounding auditor (§6), case-study similarity (> 0.6 fails), repetition checker,
  shape helper, latency capture (per endpoint p50/p99).
- **Output**: `eval/results/<UTC timestamp>/` (gitignored): `messages.jsonl`, `conversations.jsonl`,
  `scores.json`, `grounding.json`, `latency.json`, `summary.md`. The summary row is copied into §13 by hand.

## 13. Score tracking
| Date | Commit | prompt_version | Sim avg (/50) | Harness avg (/50) | Grounding findings | p99 tick (s) | Notes |
|---|---|---|---|---|---|---|---|
| 2026-09-27 | ba34655+M7 | composer_v1 (LLM off) | n/a (no judge key) | n/a (no judge key) | 0 / 36 actions | 0.05 | Offline harness: 38 cases → 36 actions (2 held by per-merchant cap), 0 shape errors, 0 URLs, 0 repeats, max case-study similarity 0.381; simulator `all` scenarios all PASS |
| | | | | | | | |

## 14. Commands
Run from the repo root (Git Bash on Windows).
```bash
PY=.venv/Scripts/python.exe

$PY -m pytest -q                                   # default: unit, contract, property, golden(fallback), replay, perf(fake)
$PY -m pytest tests/unit -q
$PY -m pytest tests/contract -q
$PY -m pytest tests/property -q
$PY -m pytest tests/golden -q                      # add --update-golden only after reviewing diffs
$PY -m pytest tests/replay -q
$PY -m pytest tests/perf -q
$PY -m pytest tests/chaos -q -m "not soak"

# opt-in, costs money (needs ANTHROPIC_API_KEY in .env)
$PY -m pytest -m llm -q
$PY -m pytest -m soak -q                           # 45-minute soak

# local server (single worker)
$PY -m uvicorn vera.api.app:app --host 127.0.0.1 --port 8080 --workers 1

# official simulator via wrapper (needs JUDGE_LLM_API_KEY)
BOT_URL=http://127.0.0.1:8080 $PY scripts/run_simulator.py --scenario all
BOT_URL=http://127.0.0.1:8080 $PY scripts/run_simulator.py --scenario full_evaluation

# extended harness
BOT_URL=http://127.0.0.1:8080 $PY eval/harness.py --out eval/results
$PY eval/grounding.py eval/results/<timestamp>/messages.jsonl
```

## 15. Exit criteria per milestone
| Milestone | Must be green |
|---|---|
| M2 | contract suite; simulator `warmup` via wrapper |
| M3 | golden (fallback mode) + grounding audit: 0 findings on 38 cases |
| M4 | golden (llm mode); latency cold/warm; adaptation |
| M5 | property P1–P8 |
| M6 | replay R1–R14; simulator `all` passes auto_reply / intent / hostile |
| M7 | simulator `full_evaluation` avg ≥ 45/50; harness avg ≥ 45/50; similarity < 0.6 everywhere |
| M8 | soak, chaos, restart recovery |
| M9 | all of the above against the public URL |
