# 11 — Deployment Runbook

| | |
|---|---|
| Owner | Amit Gautam |
| Status | v1 (M9). Files: `Dockerfile`, `.dockerignore`, `fly.toml`, `scripts/smoke_public_url.sh`. Host assumed Fly.io until Amit confirms. |
| Related | `02-TRD.md` (process model, config), `10-evaluation-and-test-plan.md` (smoke + simulator), `12-risk-and-ambiguity-register.md` |

Hard requirements from the harness: stable public HTTPS URL, **no sleeping or cold starts** (3 consecutive
healthz failures disqualify), one process (state is in-process), responses inside 30 s (15 s locally).

## 1. Host options
| Host | Always-on | Persistent disk | Build without local Docker | Cost (approx.) | Verdict |
|---|---|---|---|---|---|
| **Fly.io** | Yes: `min_machines_running = 1`, `auto_stop_machines = "off"` | Volumes (one machine per volume, which matches our single worker) | Yes: `fly deploy --remote-only` | Small shared-cpu machine + 1 GB volume, a few USD/month | **Recommended** |
| Railway | Yes on paid plans | Volumes | Yes: builds the Dockerfile from GitHub | ~USD 5/month + usage | Good fallback; fewer knobs for health checks |
| Render | Paid instances only; **free tier sleeps after idle → disqualifying** | Persistent disk on paid plans | Yes | Starter plan + disk | Acceptable only on a paid plan |
| Small VM (Lightsail, DO, Hetzner) | Yes | Local disk | Needs Docker or a venv on the box | ~USD 4–6/month | Most control, most ops (TLS via Caddy, restarts via systemd) |

Region: Fly `bom` (Mumbai) is the default because the judge is magicpin (India). Tradeoff: every LLM call then
crosses to Anthropic's US endpoints (~200–250 ms extra per call). Measure both `bom` and a US region with the
cold-tick benchmark before the final deploy; pick the lower p99.

## 2. Container
`Dockerfile` (summary; the real file is at the repo root):
```dockerfile
# Dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 PORT=8080 VERA_DB_PATH=/data/vera.db
WORKDIR /app
RUN useradd --create-home --uid 1000 vera && mkdir -p /data && chown vera:vera /data
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .
COPY reference/challenge/examples/case-studies.md ./reference/challenge/examples/case-studies.md  # validator V14
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/v1/healthz' % os.environ.get('PORT','8080'), timeout=2)"
# Fly volumes mount root-owned: fix ownership, then drop to the non-root user.
CMD ["sh", "-c", "chown vera:vera /data && exec setpriv --reuid=1000 --regid=1000 --init-groups \
  uvicorn vera.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-graceful-shutdown 10"]
```
Rules: exactly one uvicorn worker; no `--reload`; `.env` is never copied into the image (`.dockerignore`
excludes `.env*`, `eval/`, `tests/`, `scripts/`, `docs/`, `.venv/`, `data/`, and all of `reference/` except the
case-study file the validator's similarity check reads, via `VERA_CASE_STUDIES_PATH`).

`fly.toml` (outline):
```toml
# fly.toml
app = "veera-bot"
primary_region = "bom"

[env]
  PORT = "8080"
  VERA_DB_PATH = "/data/vera.db"
  VERA_RESTORE_WINDOW_S = "7200"
  LOG_LEVEL = "INFO"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 1

  [[http_service.checks]]
    grace_period = "10s"
    interval = "15s"
    timeout = "2s"
    method = "GET"
    path = "/v1/healthz"

[mounts]
  source = "vera_data"
  destination = "/data"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

## 3. Secrets
Only through the platform secret store; never in the repo, the image, or shell history.
| Secret | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (LLM mode) | Without it the bot runs on deterministic fallbacks |
| `VERA_CONTACT_EMAIL` | Yes | Shown in `/v1/metadata` |
| `VERA_SUBMITTED_AT` | Before submission | ISO timestamp for `/v1/metadata` |

```bash
# keep the values in a gitignored file (e.g. .env.prod) and import from stdin
fly secrets import < .env.prod
fly secrets list        # names only, never values
```
Setting or changing a secret restarts the machine; state is restored from SQLite because the restart falls
inside `VERA_RESTORE_WINDOW_S`.

## 4. First deploy (Windows)
```powershell
# install flyctl (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex
fly auth login
```
```bash
fly launch --no-deploy --name veera-bot --region bom      # writes fly.toml; review it against §2
fly volumes create vera_data --region bom --size 1
fly secrets import < .env.prod
fly deploy --remote-only                                  # builds on Fly's builder, no local Docker
fly status                                                # 1 machine, started, checks passing
```

## 5. Verify
1. `curl -sS https://veera-bot.fly.dev/v1/healthz` → 200 and all counts 0.
2. `scripts/smoke_public_url.sh https://veera-bot.fly.dev` (uses `curl` + `python -c` for JSON asserts, no `jq`):
   healthz → metadata (7 fields) → teardown → push category v1 (200) → re-push v1 (409 `stale_version`) →
   push merchant v1 → push trigger → tick (every action has the 11 fields, ≤ 20 actions) → reply (valid
   send/wait/end shape) → reply with only `conversation_id` + `message` (200) → healthz counts 1/1/0/1 →
   teardown → healthz 0/0/0/0. Exits non-zero on the first failed check.
3. Simulator against the public URL:
   `BOT_URL=https://veera-bot.fly.dev .venv/Scripts/python.exe scripts/run_simulator.py --scenario full_evaluation`
   then `--scenario all`.
4. Extended harness against the public URL (`eval/harness.py`), then `POST /v1/teardown`.

## 6. Monitoring
- **Logs**: `fly logs` streams JSON lines (`ts`, `level`, `event`, plus event fields). Useful events:
  `tick.done` (listed/candidates/actions), `tick.skip` / `tick.defer` (`reason`), `compose.llm_ok` (`path`:
  llm/repaired), `compose.llm_unavailable` / `compose.llm_rejected` (fell back), `fallback.violations`,
  `llm.call` (`latency_ms`, `tokens_in`, `tokens_out`), `llm.rate_limited`, `reply.done` (`intent`, `action`),
  `reply.validation`, `store.write_failed`, `store.boot` (`restored`, `counts`). Examples:
  `fly logs | grep llm.rate_limited`, `fly logs | grep '"event": "tick.done"'`.
- **Uptime monitor**: UptimeRobot or Better Stack free tier, HTTPS check on `/v1/healthz` every 1 minute,
  alert by email/phone after 1 failure (the harness disqualifies after 3 at 60 s intervals, so one alert gives
  ~2 minutes to act).
- **Platform checks**: the `fly.toml` HTTP check restarts an unhealthy machine automatically.

## 7. Budget guard
- LLM concurrency capped by `VERA_LLM_MAX_CONCURRENCY` (default 10); each call's timeout is the time left before
  the endpoint deadline; SDK retries disabled.
- Token usage logged per call (fields above); sum with `fly logs | grep input_tokens`.
- Set a monthly spend limit in the Anthropic Console before the first real run.
- Estimate per test run (Sonnet 5 at USD 2 / 10 per MTok):
  `cost ≈ calls × (in_tokens × 2 + out_tokens × 10) / 1e6`. With ~3,000 input and ~300 output tokens per call,
  one call ≈ USD 0.009; a run of ~200 compositions + ~400 reply turns ≈ 600 × 0.009 ≈ **USD 5.4**. Cached
  compositions cost nothing.

## 8. Rollback
```bash
fly releases                                   # list versions with image refs
fly deploy --image registry.fly.io/veera-bot:<previous-tag> --remote-only
fly status && scripts/smoke_public_url.sh https://veera-bot.fly.dev
```
A rollback restarts the machine; state survives within the restore window.

## 9. Judging window (keep-alive rules)
- No deploys, secret changes, or config edits from submission until results arrive.
- Before submitting the URL: run the smoke script, then `POST /v1/teardown`, then confirm healthz shows
  `0/0/0/0` (the harness's warmup expects a fresh bot).
- Keep the uptime monitor on; keep the Anthropic key funded; keep `min_machines_running = 1`.
- If magicpin re-runs a slot without calling teardown, stale triggers would inflate counts: check healthz is
  zero before each announced slot when possible.

## 10. Pre-flight checklist (all green before submission)
- [ ] All 5 endpoints live on the public URL with correct schemas; teardown works.
- [ ] Context push idempotency and version replacement verified; healthz counts exact after full warmup
      (5/50/200/0).
- [ ] `/v1/tick` returns within budget even with 20 triggers and cold cache; empty list when nothing is worth
      sending.
- [ ] `/v1/reply` handles unknown conversation ids, auto-reply ×4 across ids, intent, hostile, off-topic,
      defer, customer slot replies.
- [ ] `judge_simulator.py` runs clean (all scenarios) against the public URL with a non-trivial score.
- [ ] Zero URLs, zero taboo words, zero fabricated facts, zero verbatim repeats across the full evaluation run.
- [ ] State survives a process restart.
- [ ] `submission.jsonl` (30 lines), `bot.py`, `README.md` present and consistent with the live bot.
- [ ] `/v1/metadata` filled: `team_name` and `team_members` = "Amit Gautam", `contact_email` set from the
      secret, `model`, `approach`, `version`, `submitted_at`.
- [ ] Healthz shows 0/0/0/0 immediately before the URL is submitted.
- [ ] Restore-window behaviour verified on the deployed machine: restart within the window keeps state;
      a DB older than the window starts clean.
- [ ] Submitted URL is `https://` and has no trailing path.

## 11. Incident playbook
| Symptom | Check | Action |
|---|---|---|
| Healthz failing / monitor alert | `fly status`, `fly logs` (crash traceback? OOM?) | `fly machine restart <id>`; if it crash-loops, roll back (§8). State restores within the window. |
| LLM outage or sustained 5xx from Anthropic | logs show `composer: template` everywhere, API errors | Nothing required (templates serve automatically). To stop wasting the deadline on doomed calls: `fly secrets set VERA_LLM_ENABLED=false` (restarts the machine; state restored). Re-enable when resolved. |
| 429 rate limits | `validator_failures`/errors mention rate limit | Lower `VERA_LLM_MAX_CONCURRENCY` (e.g. 10 → 4); templates cover the gap. Check account tier limits. |
| Tick latency near 15 s | `latency_ms` on `/v1/tick` | Lower `VERA_TICK_DEADLINE_S` (7 → 5); check region RTT; confirm precompute is running on trigger push. |
| Healthz counts wrong at warmup | compare with pushes in logs | `POST /v1/teardown`, confirm 0/0/0/0; check `VERA_RESTORE_WINDOW_S` didn't restore an old run. |
| Disk full / DB error | `fly ssh console -C "df -h /data"`; logs show `store.write_failed` | Bot keeps serving from memory (write-through errors are logged, not fatal; crash recovery is degraded until fixed); extend the volume after the window. |
