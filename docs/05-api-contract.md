# 05 — API Contract

Source of truth: `reference/challenge/challenge-testing-brief.md` §2–3 and
`reference/challenge/examples/api-call-examples.md`. Machine-readable version: `/openapi.yaml`. Where the two
sources disagree, the resolution is in `12-risk-and-ambiguity-register.md` (R-01 versioning, R-02 URLs).

All endpoints: JSON in/out, UTF-8, no auth. The bot never returns 5xx by design: every handler has a last-resort
catch that returns the endpoint's safe response (listed per endpoint) and logs the error.

## Summary
| Endpoint | Method | Success | Errors | Budget (ours) |
|---|---|---|---|---|
| `/v1/context` | POST | 200 accepted | 400 malformed, 409 stale | < 200 ms |
| `/v1/tick` | POST | 200 `{actions}` | 400 malformed JSON only | p99 < 8 s cold, < 500 ms warm |
| `/v1/reply` | POST | 200 send / wait / end | 400 malformed JSON only | p99 < 6 s |
| `/v1/healthz` | GET | 200 | — | < 50 ms |
| `/v1/metadata` | GET | 200 | — | < 50 ms |
| `/v1/teardown` | POST | 200 | — | < 500 ms |

## `POST /v1/context`
Request
```json
{ "scope": "category|merchant|customer|trigger", "context_id": "string", "version": 1,
  "payload": { }, "delivered_at": "2026-04-26T10:00:00Z" }
```
Rules
1. Body > 500 KB (raw bytes) → 400 `payload_too_large`.
2. Missing field, wrong type, `version` not a non-negative integer, `payload` not an object → 400
   `invalid_body` with `details`.
3. `scope` not one of the four → 400 `invalid_scope`.
4. Stored version for `(scope, context_id)` ≥ incoming → 409 `stale_version` with `current_version`. State is
   untouched (this is the "no-op" the brief describes).
5. Otherwise replace atomically (memory + SQLite in one step), invalidate dependent compose-cache entries, and
   schedule precompute when the scope is `trigger` (see TRD §6).
6. Payload content is stored as received (`extra` fields kept). `context_id` is the key even if the payload's
   own id differs; a mismatch is logged, not rejected.

Responses
```json
200 { "accepted": true, "ack_id": "ack_merchant_m_001_drmeera_dentist_delhi_v2", "stored_at": "2026-04-26T10:30:00.789Z" }
409 { "accepted": false, "reason": "stale_version", "current_version": 2 }
400 { "accepted": false, "reason": "invalid_scope", "details": "scope must be one of category, merchant, customer, trigger" }
```
`ack_id` format: `ack_{scope}_{context_id}_v{version}` (deterministic). `stored_at` is server wall-clock UTC with
milliseconds.

## `POST /v1/tick`
Request
```json
{ "now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_001_research_digest_dentists"] }
```
`available_triggers` defaults to `[]`. Unknown trigger ids are ignored (logged).

Response
```json
{ "actions": [ {
    "conversation_id": "conv_m001_drmeera_research_digest_20260426_3f9a1c",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "send_as": "vera",
    "trigger_id": "trg_001_research_digest_dentists",
    "template_name": "vera_knowledge_v1",
    "template_params": ["Dr. Meera", "<hook sentences>", "<final CTA sentence>"],
    "body": "…",
    "cta": "open_ended",
    "suppression_key": "research:dentists:2026-W17",
    "rationale": "…"
} ] }
```
Rules
- 0–20 actions. Every action carries **all eleven fields**; `customer_id` is `null` for merchant-facing sends.
- `send_as` ∈ {`vera`, `merchant_on_behalf`}; `cta` ∈ {`open_ended`, `binary_yes_no`,
  `binary_confirm_cancel`, `multi_choice_slot`, `none`}.
- `conversation_id` is new and never returned by a previous tick. At most one action per
  `(merchant_id, conversation_id)` (trivially true since ids are unique) and at most one new merchant-facing
  conversation per merchant per tick (FR-13).
- `template_params` renders to `body` when substituted into the template's `{{1}} {{2}} {{3}}` slots in order.
- Returning an action marks its `suppression_key` as sent; an identical later tick will not resend it
  (stateful idempotency: no double effects).
- Safe response on any internal failure: `{"actions": []}` (whatever was already composed and validated before
  the failure is still returned).

## `POST /v1/reply`
Request
```json
{ "conversation_id": "conv_…", "merchant_id": "m_…", "customer_id": null,
  "from_role": "merchant|customer", "message": "Yes please", "received_at": "2026-04-26T10:42:00Z",
  "turn_number": 2 }
```
Only `conversation_id` and `message` are required; `merchant_id`, `customer_id`, `from_role` (default
`merchant`), `received_at` and `turn_number` are optional (api-call-examples 2.5–2.7 omit `merchant_id`). A
schema problem never produces FastAPI's default 422, which the judge would count as malformed. Unknown
`conversation_id` is valid: state is created lazily and bound to `merchant_id` (FR-28).
Suppression and opt-out block *proactive* tick sends only; an inbound reply is always answered (possibly with
`end`).

Responses (exactly one shape)
```json
{ "action": "send", "body": "…", "cta": "binary_confirm_cancel", "rationale": "…" }
{ "action": "wait", "wait_seconds": 86400, "rationale": "…" }
{ "action": "end",  "rationale": "…" }
```
Rules
- `send` never has an empty body and never repeats a body already sent to this merchant.
- A replayed request (same `conversation_id`, `turn_number`, message) returns the stored response unchanged and
  does not advance counters.
- Safe response on internal failure: `{"action": "wait", "wait_seconds": 3600, "rationale": "internal error; backing off"}`.

## `GET /v1/healthz`
```json
{ "status": "ok", "uptime_seconds": 3600,
  "contexts_loaded": { "category": 5, "merchant": 50, "customer": 200, "trigger": 0 } }
```
Counts are the number of distinct `(scope, context_id)` currently stored (one per id regardless of version).
Served from in-memory counters; never touches the LLM or disk.

## `GET /v1/metadata`
```json
{ "team_name": "Amit Gautam", "team_members": ["Amit Gautam"], "model": "claude-sonnet-5",
  "approach": "fact-sheet grounded LLM composer with deterministic fallback, rules-first reply state machine",
  "contact_email": "…", "version": "0.1.0", "submitted_at": "2026-…Z" }
```
Values come from env (`VERA_*`, see TRD §11); `model` reflects the configured composer model.

## `POST /v1/teardown` (optional)
Wipes memory and SQLite (contexts, conversations, suppressions, flags, cache, audit). Response
`{"wiped": true}`. Healthz counts return to zero.

## Status-code matrix
| Situation | context | tick | reply | healthz/metadata |
|---|---|---|---|---|
| Valid | 200 | 200 | 200 | 200 |
| Invalid JSON | 400 `invalid_body` | 400 `{"actions": [], "error": "invalid_body"}` | 400 `{"action":"wait",…}` | — |
| Schema violation | 400 `invalid_body` | 200, defaults applied where possible | 200, defaults applied | — |
| Stale version | 409 | — | — | — |
| Over 500 KB | 400 `payload_too_large` | 400 | 400 | — |
| Internal exception | 400 `internal_error` (never 5xx) | 200 safe response | 200 safe response | 200 |
| LLM down / slow | n/a | 200, fallback composer | 200, fallback reply | 200 |
