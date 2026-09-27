#!/usr/bin/env bash
# scripts/smoke_public_url.sh — exercise every endpoint of a deployed bot (docs/11-deployment-runbook.md §5).
# Usage: scripts/smoke_public_url.sh https://veera-bot.fly.dev
# WARNING: calls POST /v1/teardown (wipes state) at the start and the end. Never run during a judging slot.
set -euo pipefail

BASE="${1:?usage: $0 <base-url>}"
BASE="${BASE%/}"
PY="${PYTHON:-python}"
export PYTHONUTF8=1

step() { printf '  %-44s' "$1"; }
ok() { echo "ok"; }

# post <path> <json> <expected-status> -> prints body
post() {
  local out status
  out=$(curl -sS -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' -d "$2" "$BASE$1")
  status="${out##*$'\n'}"
  [[ "$status" == "$3" ]] || { echo "FAIL: POST $1 returned $status (want $3): ${out%$'\n'*}"; exit 1; }
  printf '%s' "${out%$'\n'*}"
}

get() { curl -sS --fail "$BASE$1"; }
check() { "$PY" -c "import json,sys; d=json.loads(sys.argv[1]); assert $2, d" "$1" || { echo "FAIL: $3"; exit 1; }; }

echo "Smoke test against $BASE"
step "healthz";  body=$(get /v1/healthz); check "$body" "d['status']=='ok'" healthz; ok
step "metadata (7 fields)"; body=$(get /v1/metadata)
check "$body" "set(d)>={'team_name','team_members','model','approach','contact_email','version','submitted_at'}" metadata; ok
step "teardown"; post /v1/teardown '{}' 200 >/dev/null; ok

CAT='{"scope":"category","context_id":"dentists","version":1,"payload":{"slug":"dentists","voice":{"tone":"peer_clinical","vocab_taboo":["guaranteed"]},"peer_stats":{"avg_ctr":0.03,"avg_calls_30d":12},"digest":[],"offer_catalog":[{"title":"Dental Cleaning @ ₹299"}]}}'
MER='{"scope":"merchant","context_id":"m_smoke","version":1,"payload":{"merchant_id":"m_smoke","category_slug":"dentists","identity":{"name":"Smoke Dental","owner_first_name":"Asha","locality":"Saket","languages":["en","hi"],"verified":false},"performance":{"views":900,"calls":6,"ctr":0.02,"delta_7d":{"calls_pct":-0.3}},"offers":[{"title":"Dental Cleaning @ ₹299","status":"active"}],"signals":["unverified_gbp"]}}'
TRG='{"scope":"trigger","context_id":"trg_smoke","version":1,"payload":{"id":"trg_smoke","scope":"merchant","kind":"perf_dip","merchant_id":"m_smoke","payload":{"metric":"calls","delta_pct":-0.3,"window":"7d","vs_baseline":8},"urgency":3,"suppression_key":"smoke:perf_dip"}}'

step "push category v1 (200)"; post /v1/context "$CAT" 200 >/dev/null; ok
step "re-push category v1 (409 stale_version)"; body=$(post /v1/context "$CAT" 409)
check "$body" "d['reason']=='stale_version' and d['current_version']==1" stale; ok
step "push merchant + trigger"; post /v1/context "$MER" 200 >/dev/null; post /v1/context "$TRG" 200 >/dev/null; ok
step "tick (11 fields, <= 20 actions)"
body=$(post /v1/tick '{"now":"2026-04-26T10:00:00Z","available_triggers":["trg_smoke"]}' 200)
check "$body" "len(d['actions'])<=20 and all(len(set(a))==11 and a['body'] and 'http' not in a['body'] for a in d['actions'])" tick
CONV=$("$PY" -c "import json,sys; a=json.loads(sys.argv[1])['actions']; print(a[0]['conversation_id'] if a else 'conv_smoke')" "$body"); ok
step "reply (send/wait/end shape)"
body=$(post /v1/reply "{\"conversation_id\":\"$CONV\",\"merchant_id\":\"m_smoke\",\"from_role\":\"merchant\",\"message\":\"Yes please go ahead\",\"turn_number\":2}" 200)
check "$body" "d['action'] in ('send','wait','end') and d['rationale']" reply; ok
step "reply with only conversation_id + message"
body=$(post /v1/reply '{"conversation_id":"conv_min","message":"hello?"}' 200); check "$body" "d['action'] in ('send','wait','end')" reply-min; ok
step "healthz counts 1/1/0/1"; body=$(get /v1/healthz)
check "$body" "d['contexts_loaded']=={'category':1,'merchant':1,'customer':0,'trigger':1}" counts; ok
step "teardown -> 0/0/0/0"; post /v1/teardown '{}' 200 >/dev/null; body=$(get /v1/healthz)
check "$body" "set(d['contexts_loaded'].values())=={0}" zero; ok
echo "All smoke checks passed."
