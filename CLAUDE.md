# CLAUDE.md — Veera (Vera bot for the magicpin AI Challenge)

## What this is
An HTTP bot that plays **Vera**, magicpin's WhatsApp assistant for merchant growth. An LLM judge pushes context
(category / merchant / customer / trigger), calls `/v1/tick` to see what we'd send, plays the merchant on
`/v1/reply`, and scores each message on specificity, category fit, merchant fit, decision quality (why-now) and
engagement compulsion. Docs are the spec; code implements them. When code diverges, update the doc in the same commit.

## Status
- M0–M6 done: tick composer (LLM behind `ANTHROPIC_API_KEY`, deterministic without) and reply engine.
  Next: M7 eval harness, M8 hardening, M9 packaging/deploy.
- Golden snapshots: `tests/golden/snapshots.json`; regenerate after an intended wording change with
  `UPDATE_GOLDEN=1 PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/golden`.
- Milestone checklist: `docs/04-implementation-plan.md`.

## Docs (read in this order when starting cold)
| Doc | Use it for |
|---|---|
| `docs/00-context-digest.md` | Two-page summary of the challenge and business |
| `docs/02-TRD.md` | Architecture, components, latency budget, config, error matrix |
| `docs/07-trigger-playbook.md` | Per-kind rules the decision step implements (26 kinds + generic) |
| `docs/06-composer-spec.md` | Fact sheet format, prompt, output schema, validator rules V1–V17 |
| `docs/09-conversation-policy.md` | Reply classifier + state machine |
| `docs/12-risk-and-ambiguity-register.md` | Every contradiction and how it was resolved |
| `docs/01-PRD.md`, `03`, `05` + `openapi.yaml`, `08`, `10`, `11`, `adr/` | Requirements, schema, API, voice, tests, deploy, decisions |

## Key decisions (details in ADRs)
- Code decides (signal, CTA, template, send_as, language); the LLM writes `{opener, middle, ask, rationale}` (ADR-009).
- `claude-sonnet-5`, thinking disabled, structured output, **no temperature** (rejected on Sonnet 5);
  determinism via the input-hash compose cache (ADR-002, ADR-004).
- SQLite write-through with a 2 h restore window on boot; teardown wipes (ADR-003).
- Only listed `available_triggers` are candidates; never compare `expires_at` or derive durations from `now`.
- Auto-reply: pattern + per-merchant repeat count → send, wait 24h, end (ADR-006).
- Consent gate; failures re-route to a merchant approval message (ADR-008). Language by region (ADR-007).

## Commands (Windows / Git Bash)
```bash
uv venv .venv && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m pytest -q
# run the bot (1 worker; state in data/vera.db)
.venv/Scripts/python.exe -m vera.main
# official simulator via wrapper (non-scoring scenarios need no key)
.venv/Scripts/python.exe scripts/run_simulator.py --scenario all
# regenerate the expanded dataset (PYTHONUTF8 is required on Windows)
PYTHONUTF8=1 python reference/challenge/dataset/generate_dataset.py \
  --seed-dir reference/challenge/dataset --out reference/challenge/expanded
```

## Map
| Path | What |
|---|---|
| `reference/challenge/` | Official package (briefs, `judge_simulator.py`, dataset seeds, generator, examples). Read-only. |
| `reference/challenge/expanded/` | Generator output: 5 categories, 50 merchants, 200 customers, 100 triggers, `test_pairs.json` (30). |
| `reference/challenge-page.md` | Scraped public challenge page (rubric names "decision quality"). |
| `reference/research/` | magicpin due-diligence dossier. Background for the PRD only; never cited in messages. |
| `docs/00…12`, `docs/adr/` | Spec set: digest, PRD, TRD, schema, plan, API, composer, trigger playbook, voice, conversation policy, eval, runbook, risk register, ADRs. |
| `src/vera/` | Code (M2+): `api/ store/ planner/ compose/ reply/ llm/ domain/ observability/`. |
| `tests/` | pytest suites (unit, contract, property, golden, replay, perf). |

## Conventions
- Conventional Commits; never commit to `main` (feature branch + PR). Check `gh auth status --active` is
  `amit-gautam-09` before any push.
- Never commit `.env`, keys, or an edited `judge_simulator.py`. The wrapper `scripts/run_simulator.py` injects config.
- Python: 4-space indent, `pathlib`, `python-dotenv`, `main()` + `__main__` guard, no bare `except:`.
- Message copy: original wording only. Never reuse case-study bodies (`examples/case-studies.md`) in prompts,
  fixtures, or templates — the judge runs a similarity check.

## Gotchas (read before touching behaviour)
- **Encoding**: the generator and simulator use `open()` without `encoding=` → set `PYTHONUTF8=1` on Windows.
- **Clock**: the simulator sends wall-clock `now` (Sept 2026) while data lives in Apr–Jun 2026. Treat
  `available_triggers` as authoritative; never derive durations from the clock; quote explicit payload dates.
- **Thin triggers**: 75/100 triggers (13/30 test pairs) have `payload: {"placeholder": true, ...}`. Never invent the
  missing specifics; build the hook from merchant + category facts.
- **Kind/category mismatch**: generated triggers pair kinds with random merchants (refill reminder for a dentist).
  Reinterpret for the category or stay silent; say which in the rationale.
- **Simulator never pushes customers** and uses unseen conversation ids (`conv_auto_1..4`) for one merchant →
  lazily create conversation state; track auto-replies per merchant, not just per conversation.
- **Scorer visibility**: the simulator's scorer sees only a subset of context (no digest, peer stats, aggregates,
  history, rationale). Attribute deeper facts in the body so provenance is visible.
- `owner_first_name` for generated dentists already contains "Dr." — normalise salutations.
- Single uvicorn worker only (state is in-process, write-through to SQLite).
