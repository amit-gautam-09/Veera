# CLAUDE.md — Veera (Vera bot for the magicpin AI Challenge)

## What this is
An HTTP bot that plays **Vera**, magicpin's WhatsApp assistant for merchant growth. An LLM judge pushes context
(category / merchant / customer / trigger), calls `/v1/tick` to see what we'd send, plays the merchant on
`/v1/reply`, and scores each message on specificity, category fit, merchant fit, decision quality (why-now) and
engagement compulsion. Docs are the spec; code implements them. When code diverges, update the doc in the same commit.

## Status
- M0 bootstrap: done. M1 docs: in progress on `docs/m1-foundation`.
- Milestone checklist: `docs/04-implementation-plan.md`.

## Commands (Windows / Git Bash)
```bash
uv venv .venv && uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m pytest -q
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
