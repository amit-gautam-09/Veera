# Session record — Veera (Vera bot, magicpin AI Challenge)

**Last updated**: 2026-09-27 (IST) · **Owner**: Amit Gautam · **Repo**: https://github.com/amit-gautam-09/Veera
**Resume branch**: `feat/m12-judge-tuning` (PR against `main`; M2–M11 already merged to `main` via #13)

Read this first when resuming, then `CLAUDE.md` (commands, map, gotchas). No secrets are in this file.

---

## 1. Where we stopped (exact point)
First **valid scored runs** of the official simulator (`full_evaluation`, 14 messages, 0 judge errors) are done with
judge `gemini-3.1-flash-lite` (`gemini-flash-latest` = `gemini-3.8-flash`, only 20 requests/day free).
- Run A (before M12): mean **40.3/50** (sim prints 38 = sum of floored per-dimension averages). 7 of 14 were fallback.
  Lowest: Karthik lapsed-member approval 27, Anjali dormancy 27 ("180 clients" looked fabricated: the scorer never
  sees `customer_aggregate`), Lakshmi wedding approval 36 ("robotic", missing payload details).
- M12 fixed those (below). Run B: mean **42.9/50**; all 14 messages were deterministic because Gemini was
  timing out/429 at that moment. Targets moved 27→42, 27→41, 36→41; unchanged messages scored identically (stable judge).
- Harness smoke with Gemini judge + personas (`--limit 5 --reply-turns 1`): judge avg 45.4, 0 findings, replies OK.

**Next action on resume**: full harness run (§5 step 1), then decide LLM vs deterministic (§6).

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
| M11 | **Free Gemini provider** (`OpenAICompatibleGateway`, `make_gateway`), prompt `composer_v3`, V18, ADR-012; judge retries in simulator wrapper | #12 |
| M12 | Queue-timeout fix (per-call cap after the semaphore), approval + dormancy wording, Hinglish approval sentences, V15 rejects Devanagari, harness Gemini judge/personas | open (see `gh pr list`) |

The stacked PRs #2–#10 and #12 were merged, and #13 brought the whole stack into `main` (2026-09-27).

## 3. Current configuration
- LLM: free **Google Gemini** key in the gitignored `.env` (`VERA_LLM_PROVIDER=gemini`, `VERA_LLM_API_KEY`,
  `VERA_LLM_MAX_CONCURRENCY=4`, judge: `JUDGE_LLM_PROVIDER=gemini`, `JUDGE_LLM_MODEL=gemini-3.1-flash-lite`: own free quota, separate from the bot's model).
  The key was pasted in chat once: **rotate it in AI Studio after the challenge**.
- Composer model: `gemini-3.5-flash-lite`, `reasoning_effort=low` (measured best on this key; ADR-012).
  `gemini-3.8-flash` quota tiny (429 after 2 calls); 3.5/3.7 Flash overloaded (503, 30 s hangs); 2.5 Flash gone.
- Without any key the bot runs the deterministic composer (grounded, valid by construction).
- Tests always force `VERA_LLM_ENABLED=false` (autouse fixture in `tests/conftest.py`): no network in tests.

## 4. Measured results so far
| Check | Result |
|---|---|
| Test suite | 139 pass (+1 `-m slow` restart test) · ruff + mypy clean |
| Deterministic sweep, 100 triggers | 96 composed, 4 correct opt-out skips; grounding audit 0 findings |
| Live Gemini, 38 golden cases, composer_v3 | 36 LLM + 2 repaired, 0 fallbacks, 0 grounding findings, p50 1.8 s, p90 2.3 s, max case-study similarity 0.26 |
| Official simulator `all` (replies) | warmup, auto_reply, intent, hostile all PASS |
| Official simulator `full_evaluation` | valid: run A 40.3/50 (mixed LLM/fallback), run B 42.9/50 (M12, all deterministic) |
| Offline harness (`python -m eval.harness`) | 38 cases → 36 actions, 0 shape errors, 0 findings, 0 URLs, 0 repeats |
| Soak | 2 min @ 10 rps clean; the 45-min local run was killed by Claude Code for low system memory (not a bot failure) |

Known behaviour: in the simulator's `full_evaluation` only 14/25 seed triggers get a message, because its batches
contain several triggers for one merchant and the bot sends at most one merchant-facing message per merchant per
tick (kept on purpose, register R-11).

## 5. Next steps (in order)
1. **Full harness run** (Gemini judge + personas now supported):
   `.venv/Scripts/python.exe -m vera.main` then `PYTHONUTF8=1 .venv/Scripts/python.exe -m eval.harness --reply-turns 3`.
   Read low scores + transcripts in `eval/results/<stamp>/results.jsonl`.
2. **LLM vs deterministic** (decision in §6): score a run with the LLM healthy and compare message by message with
   run B. Free Gemini bursts of 25 triggers get 429s (RPM) and >6 s latency, so half or more fall back anyway.
3. **Tune from the judge's reasons**: prompt `composer_v4` and/or deterministic wording; keep 0 grounding findings.
   The simulator scorer sees only: category voice/taboos, merchant identity, views/calls/CTR, signals, active offer
   titles, trigger kind/payload/urgency. Attribute anything else in the body ("magicpin data shows ...").
4. **Regenerate `submission.jsonl`**: `PYTHONUTF8=1 .venv/Scripts/python.exe scripts/generate_submission.py`
   (outputs cached in `data/bot_cache.db`, so reruns are identical); commit.
5. **Deploy** (needs Amit): install flyctl `iwr https://fly.io/install.ps1 -useb | iex`, `fly auth login`; then
   `fly launch --no-deploy`, `fly volumes create vera_data --region bom --size 1`,
   `fly secrets set VERA_LLM_PROVIDER=gemini VERA_LLM_API_KEY=... VERA_CONTACT_EMAIL=...`,
   `fly deploy --remote-only`, `scripts/smoke_public_url.sh https://<app>.fly.dev`, simulator + harness against the
   public URL, 45-min soak against the public URL (not locally). Runbook: `docs/11-deployment-runbook.md`.
6. **Pre-flight** (runbook §10), `POST /v1/teardown`, confirm healthz 0/0/0/0, submit the URL.

## 6. Decisions still needed from Amit
- Merge the M12 PR.
- Keep the LLM composer on for submission, or go deterministic-only? Run B (deterministic) scored 42.9 vs run A
  (half LLM) 40.3 on the simulator judge; one small sample, so measure again with the LLM healthy first.
- Contact email for `/v1/metadata` (`VERA_CONTACT_EMAIL`).
- Keep the due-diligence dossier in this **public** repo, or remove it?
- OK with the 2 h restore window (ADR-003)?
- OK to delete unused stubs `src/vera/compose/stub.py`, `src/vera/reply/stub.py`?

## 7. Gotchas learned this session
- Windows: run the simulator via `scripts/run_simulator.py` (UTF-8 re-exec); use `http://127.0.0.1:8080`, not
  `localhost`.
- The vendor simulator hides judge failures (digit-count fallback): trust only runs with no `LLM error` lines.
- Free Gemini: limits are per project and per model; RPD resets at midnight Pacific; judge and bot share a project.
- Long heredocs with regex backslashes corrupted files twice (a literal backspace in a regex); write patch
  scripts to files instead of inline heredocs.
- Don't run the 45-min soak locally (memory pressure); run it against the deployed URL.
- `gemini-flash-latest` resolves to `gemini-3.8-flash` (20 requests/day free): useless as a judge.
- The bot audit log (`audit_log` table in `data/vera.db`) keeps every tick action with `path` (llm/fallback/cache):
  use it to see which scored messages were LLM-written.
- Redirected Python stdout is block-buffered: set `PYTHONUNBUFFERED=1` to watch simulator logs live.
- Throwaway scripts/logs go in `.scratch/` (gitignored, so ruff skips it).
- Golden snapshots: after an intended wording change run
  `UPDATE_GOLDEN=1 PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/golden` and review the diff.
