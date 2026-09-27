# Veera: Vera, rebuilt for the magicpin AI Challenge

An HTTP bot that plays **Vera**, magicpin's WhatsApp assistant for merchants. It decides whether to message a
merchant or one of the merchant's customers, what to say and why now, and it carries the conversation to an
outcome or a graceful exit. Author: Amit Gautam.

## Approach
```
context push ─► versioned store (memory + SQLite write-through, restore window)
tick ─► guards (suppression, opt-out, consent, missing context) ─► rank (urgency → expiry → order) ─► 1 per merchant
      ─► per trigger: fact sheet ─► decision (family, one primary signal, ≤2 supports, levers, CTA, language)
         ─► LLM writes {opener, middle, ask} from the facts + a grounded reference draft
         ─► validator (every number/date/name/source traced; taboos; URLs; one CTA) ─► drop sentence / repair / fallback
reply ─► rule classifier (EN / Hinglish / Devanagari) ─► state machine ─► deliverable or exit ─► validator
```
- **Code decides, the model writes.** Signal choice, CTA type, recipient, template and language are
  deterministic (a playbook for all 26 trigger kinds plus a generic handler). The LLM only phrases three short
  fields, so contract fields are always valid and the CTA is always the last sentence.
- **Thin and mismatched triggers** (75 of 100 generated triggers have placeholder payloads; kinds are assigned to
  random categories) get explicit strategies: use the merchant's real deltas, peer gaps, offers and review themes,
  and reinterpret the kind for the category or stay silent. Missing specifics are never invented.
- **Customers**: a consent gate; when a customer can't be messaged, the bot asks the merchant for approval instead.
- **Replies**: auto-replies are detected on first sight and counted per merchant across conversations (send one
  note, wait 24h, end). "Let's do it" delivers the draft immediately with a CONFIRM ask, and hostility ends the
  conversation and suppresses further ticks. Off-topic asks get a one-line decline and a redirect, and the reply
  language follows the latest message.

## Model and why
`claude-sonnet-5` with thinking disabled and structured JSON output: strong Hinglish and clinical-register prose
at tick latency. It rejects `temperature`, so determinism comes from a content-hashed compose cache: identical
inputs return byte-identical output. Without `ANTHROPIC_API_KEY` the same pipeline runs on the deterministic
wording each handler writes, which is grounded and valid by construction. That wording is also the fallback on any
timeout, 429 or validation failure.

## Guarantees and how they're met
| Property | Mechanism |
|---|---|
| No fabrication | fact sheet + token-class validator at runtime; an independent grounding auditor in tests and eval (0 findings over all 96 composable triggers) |
| Never times out | 7 s tick / 5 s reply deadlines (simulator allows 15 s); precompute on trigger push; LLM calls capped by the time left |
| Never breaks | no 422/5xx by design; chaos tests with malformed contexts for every kind; one sanitiser at the context boundary |
| Survives restarts | SQLite write-through restored on boot only inside a 2 h window (a stale DB would break warmup counts) |
| Original wording | no case-study text in prompts or templates; similarity check ≤ 0.6 in the validator |

## Tradeoffs
Rules-first reply classification (fast and predictable; misses unusual phrasings, so `unclear` restates the
open ask). One merchant-facing message per merchant per tick (restraint over volume). Deterministic wording is
plainer than LLM wording. Code-built rationales are consistent but formulaic.

## What context would have helped most
Real appointment slots and service prices per merchant (so customer messages could always offer a bookable
choice); the merchant's recent Vera replies with timestamps; which placeholder trigger fields are meant to be
filled in production; and the judge's actual `now` semantics (the local simulator sends wall-clock time against
April-2026 data).

## Run it
```bash
uv venv .venv && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"   # or: python -m venv; pip install -e ".[dev]"
.venv/Scripts/python.exe -m vera.main                        # http://127.0.0.1:8080, one worker
.venv/Scripts/python.exe -m pytest -q                        # 130+ tests (golden, replay, chaos, property, contract)
.venv/Scripts/python.exe scripts/run_simulator.py --scenario all   # official simulator, unedited (UTF-8 + config via env)
PYTHONUTF8=1 .venv/Scripts/python.exe -m eval.harness       # expanded-dataset harness; LLM judge with JUDGE_LLM_API_KEY
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/generate_submission.py   # submission.jsonl from bot.compose
```
Docs: `docs/00-context-digest.md` (start here), `docs/02-TRD.md`, `docs/07-trigger-playbook.md`,
`docs/12-risk-and-ambiguity-register.md`. Deploy: `docs/11-deployment-runbook.md` (Fly.io, `fly.toml`,
`Dockerfile`).
