# Session record — Veera (Vera bot, magicpin AI Challenge)

**Last updated**: 2026-09-27 (IST) · **Owner**: Amit Gautam · **Repo**: https://github.com/amit-gautam-09/Veera
**Resume branch**: `feat/m11-gemini` (all work committed and pushed; PR #11)

Read this first when resuming, then `CLAUDE.md` (commands, map, gotchas). No secrets are in this file.

---

## 1. Where we stopped (exact point)
We were getting the **first valid scored run** of the official simulator (`full_evaluation`) with a free Gemini
judge. It could not complete:
- Run 1 (composer_v3, judge `gemini-flash-latest`): 11 of 14 judge calls hit Gemini free-tier 429/503, and the
  vendor simulator then silently falls back to a digit-counting heuristic, so its "28/50" is **invalid**. The only
  real judge scores were **34, 26, 35 /50**.
- Run 2: added judge retries with backoff + verbose reasons to `scripts/run_simulator.py` (committed). The judge
  model still returned 429 after 60 s backoffs, which means its free **daily** quota was used up. Run stopped; no
  reasons captured.

**Next action on resume**: get a valid scored run (see §5, step 1), read the judge's reasons, tune.

## 2. What is built (M0–M11)
| Milestone | What | PR |
|---|---|---|
| M0–M1 | Repo bootstrap, reference package, docs 00–12, ADR-001…011 | #1 (merged) |
| M2 | All endpoints, 400/409/500 KB, no 422/5xx, SQLite write-through + 2 h restore window, planner | #2 |
| M3 | Fact sheet, per-kind playbook (26 kinds + generic), validator V1–V17, EN/Hinglish grounded wording, golden set | #3 |
| M4 | LLM composer (Anthropic), cache, precompute, repair ladder | #4 |
| M5 | Hypothesis property tests P1–P8 | #5 |
| M6 | Reply engine (auto-reply ladder, intent → action, hostile/opt-out, off-topic, slots, language mirror) | #6 |
| M7 | Independent grounding auditor, extended harness, adaptation tests | #7 |
| M8 | Chaos, restart-recovery, soak script; context sanitiser | #8 |
| M9 | Dockerfile, fly.toml, bot.py, conversation_handlers.py, submission.jsonl, smoke script, README | #9 |
| M10 | Deterministic wording polish (5 fixes) | #10 |
| M11 | **Free Gemini provider** (`OpenAICompatibleGateway`, `make_gateway`), prompt `composer_v3`, V18, ADR-012; judge retries in simulator wrapper | #11 |

PRs #2–#11 are **stacked**: each is based on the previous branch. Merge in order; after each merge retarget the
next PR to `main`.

## 3. Current configuration
- LLM: free **Google Gemini** key in the gitignored `.env` (`VERA_LLM_PROVIDER=gemini`, `VERA_LLM_API_KEY`,
  `VERA_LLM_MAX_CONCURRENCY=4`, judge: `JUDGE_LLM_PROVIDER=gemini`, `JUDGE_LLM_MODEL=gemini-flash-latest`).
  The key was pasted in chat once: **rotate it in AI Studio after the challenge**.
- Composer model: `gemini-3.5-flash-lite`, `reasoning_effort=low` (measured best on this key; ADR-012).
  `gemini-3.8-flash` quota tiny (429 after 2 calls); 3.5/3.7 Flash overloaded (503, 30 s hangs); 2.5 Flash gone.
- Without any key the bot runs the deterministic composer (grounded, valid by construction).
- Tests always force `VERA_LLM_ENABLED=false` (autouse fixture in `tests/conftest.py`): no network in tests.

## 4. Measured results so far
| Check | Result |
|---|---|
| Test suite | 138 pass (+1 `-m slow` restart test) · ruff + mypy clean |
| Deterministic sweep, 100 triggers | 96 composed, 4 correct opt-out skips; grounding audit 0 findings |
| Live Gemini, 38 golden cases, composer_v3 | 36 LLM + 2 repaired, 0 fallbacks, 0 grounding findings, p50 1.8 s, p90 2.3 s, max case-study similarity 0.26 |
| Official simulator `all` (replies) | warmup, auto_reply, intent, hostile all PASS |
| Official simulator `full_evaluation` | not yet valid (judge quota); 3 real scores 34/26/35 |
| Offline harness (`python -m eval.harness`) | 38 cases → 36 actions, 0 shape errors, 0 findings, 0 URLs, 0 repeats |
| Soak | 2 min @ 10 rps clean; the 45-min local run was killed by Claude Code for low system memory (not a bot failure) |

Known behaviour: in the simulator's `full_evaluation` only 14/25 seed triggers get a message, because its batches
contain several triggers for one merchant and the bot sends at most one merchant-facing message per merchant per
tick (kept on purpose, register R-11).

## 5. Next steps (in order)
1. **Valid judge scores.** Options (pick one): wait for the free daily quota reset (midnight Pacific = 12:30 IST);
   use a judge model with its own quota (`gemini-flash-lite-latest` or `gemini-3.1-flash-lite`, not the bot's
   `gemini-3.5-flash-lite`); or a second Google AI Studio project/key just for the judge. Then:
   `.venv/Scripts/python.exe -m vera.main` (terminal 1) and
   `.venv/Scripts/python.exe scripts/run_simulator.py --scenario full_evaluation` (terminal 2).
2. **Extend `eval/harness.py`** judge + personas to support Gemini (today `make_llm` is Anthropic-only), with the
   same retry/backoff; run it for full-context scores and reply-turn transcripts.
3. **Tune from the judge's reasons**: prompt `composer_v4` and/or deterministic wording; re-run live golden
   (`scratchpad` scripts are gone — use `tests/golden` + a live run like `bot.compose`), keep 0 grounding findings.
4. **Regenerate `submission.jsonl` with Gemini**: `PYTHONUTF8=1 .venv/Scripts/python.exe scripts/generate_submission.py`
   (outputs cached in `data/bot_cache.db`, so reruns are identical); commit.
5. **Deploy** (needs Amit): install flyctl `iwr https://fly.io/install.ps1 -useb | iex`, `fly auth login`; then
   `fly launch --no-deploy`, `fly volumes create vera_data --region bom --size 1`,
   `fly secrets set VERA_LLM_PROVIDER=gemini VERA_LLM_API_KEY=... VERA_CONTACT_EMAIL=...`,
   `fly deploy --remote-only`, `scripts/smoke_public_url.sh https://<app>.fly.dev`, simulator + harness against the
   public URL, 45-min soak against the public URL (not locally). Runbook: `docs/11-deployment-runbook.md`.
6. **Pre-flight** (runbook §10), `POST /v1/teardown`, confirm healthz 0/0/0/0, submit the URL.

## 6. Decisions still needed from Amit
- Contact email for `/v1/metadata` (`VERA_CONTACT_EMAIL`).
- Keep the due-diligence dossier in this **public** repo, or remove it?
- OK with the 2 h restore window (ADR-003)?
- OK to delete unused stubs `src/vera/compose/stub.py`, `src/vera/reply/stub.py`?
- Merge PRs #2–#11 in order.

## 7. Gotchas learned this session
- Windows: run the simulator via `scripts/run_simulator.py` (UTF-8 re-exec); use `http://127.0.0.1:8080`, not
  `localhost`.
- The vendor simulator hides judge failures (digit-count fallback): trust only runs with no `LLM error` lines.
- Free Gemini: limits are per project and per model; RPD resets at midnight Pacific; judge and bot share a project.
- Long heredocs with regex backslashes corrupted files twice (a literal backspace in a regex); write patch
  scripts to files instead of inline heredocs.
- Don't run the 45-min soak locally (memory pressure); run it against the deployed URL.
- Golden snapshots: after an intended wording change run
  `UPDATE_GOLDEN=1 PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/golden` and review the diff.
