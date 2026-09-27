"""Extended evaluation harness (docs/10 §12): drives a running bot over HTTP with the EXPANDED dataset.

Offline checks always run: action shape, grounding audit, case-study similarity, repetition, latency.
With JUDGE_LLM_API_KEY set: an LLM judge scores every action on the 5-dimension rubric with FULL context
visible, and LLM personas play up to --reply-turns merchant/customer replies per conversation.

Usage:
  python -m eval.harness --bot-url http://127.0.0.1:8080 [--reply-turns 3] [--limit 38]
Env (or .env): BOT_URL, JUDGE_LLM_API_KEY, JUDGE_LLM_MODEL (default claude-sonnet-5),
               PERSONA_LLM_MODEL (default claude-haiku-4-5-20251001)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from dotenv import load_dotenv

from eval.grounding import audit
from vera.compose.validator import plagiarism_ratio
from vera.domain.ids import text_hash

ROOT = Path(__file__).resolve().parents[1]
EXPANDED = ROOT / "reference" / "challenge" / "expanded"
RESULTS = ROOT / "eval" / "results"
EXTRA = [
    "trg_001_research_digest_dentists",
    "trg_005_renewal_due_bharat",
    "trg_011_review_theme_late_delivery",
    "trg_014_seasonal_acquisition_dip_powerhouse",
    "trg_018_supply_atorvastatin_recall",
    "trg_017_kids_yoga_trial_followup_karthik",
    "trg_007_bridal_followup_kavya",
    "trg_009_winback_glamour",
]
FIELDS = {
    "conversation_id",
    "merchant_id",
    "customer_id",
    "send_as",
    "trigger_id",
    "template_name",
    "template_params",
    "body",
    "cta",
    "suppression_key",
    "rationale",
}
PERSONAS = ["engaged", "auto_reply", "hard_no", "curveball", "hindi_switch"]
TICK_BATCH = 5
REQUEST_TIMEOUT_S = 30

JUDGE_SYSTEM = """You are a strict judge for the magicpin AI Challenge. Score one WhatsApp message that a bot \
("Vera") composed for a merchant, or for a merchant's customer, from the contexts below. 5 is average, 7 good, \
9+ excellent. Dimensions (0-10 each):
1. specificity: verifiable facts from the context (numbers, dates, prices, sources), not generic claims.
2. category_fit: voice and vocabulary right for the business type; no hype in clinical categories.
3. merchant_fit: personalised to this merchant/customer (their name, numbers, offers, history, language).
4. decision_quality: picks the single best signal for this trigger and makes "why now" clear.
5. engagement_compulsion: a real reason to reply now with one low-effort call to action.
Also list any fabricated fact (anything not supported by the contexts) and any exposed internal jargon.
Reply ONLY with JSON: {"specificity": n, "category_fit": n, "merchant_fit": n, "decision_quality": n,
"engagement_compulsion": n, "fabrications": [..], "jargon": [..], "note": "one sentence"}"""

PERSONA_PROMPTS = {
    "engaged": "You are the busy owner. Reply briefly and positively, maybe asking one practical follow-up.",
    "auto_reply": "Reply ONLY with this WhatsApp Business auto-reply, word for word: "
    "'Thank you for contacting us! Our team will get back to you shortly.'",
    "hard_no": "You are not interested and a bit annoyed. Say so in one short line.",
    "curveball": "Ask an unrelated question in one line (for example about GST filing or a bank loan).",
    "hindi_switch": "Reply in casual Hinglish (Roman script), agreeing to go ahead.",
}


KEYS = {"categories": "slug", "merchants": "merchant_id", "customers": "customer_id", "triggers": "id"}


def load(folder: str) -> dict[str, dict[str, Any]]:
    items = (json.loads(p.read_text(encoding="utf-8")) for p in sorted((EXPANDED / folder).glob("*.json")))
    return {d[KEYS[folder]]: d for d in items}


class Bot:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.latency: dict[str, list[float]] = {}

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urlrequest.Request(
            self.base + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        started = time.monotonic()
        try:
            with urlrequest.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                status, payload = resp.status, json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as exc:
            status, payload = exc.code, json.loads(exc.read().decode("utf-8") or "{}")
        self.latency.setdefault(path, []).append(time.monotonic() - started)
        return status, payload

    def push(self, scope: str, cid: str, payload: dict[str, Any], version: int = 1) -> int:
        return self.call(
            "POST",
            "/v1/context",
            {
                "scope": scope,
                "context_id": cid,
                "version": version,
                "payload": payload,
                "delivered_at": "2026-04-26T09:45:00Z",
            },
        )[0]


def make_llm(model_env: str, default: str) -> Any:
    key = os.getenv("JUDGE_LLM_API_KEY")
    if not key:
        return None
    import anthropic

    client, model = anthropic.Anthropic(api_key=key, max_retries=2), os.getenv(model_env) or default

    def complete(system: str, prompt: str, max_tokens: int = 600) -> str:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "disabled"},
        )
        return next((b.text for b in resp.content if b.type == "text"), "")

    return complete


def judge(llm: Any, action: dict[str, Any], contexts: dict[str, Any]) -> dict[str, Any] | None:
    if llm is None:
        return None
    prompt = (
        "CONTEXTS (JSON):\n"
        + json.dumps(contexts, ensure_ascii=False)[:24000]
        + "\n\nMESSAGE:\n"
        + json.dumps({k: action[k] for k in ("body", "cta", "send_as", "rationale")}, ensure_ascii=False)
    )
    text = llm(JUDGE_SYSTEM, prompt)
    try:
        return json.loads(text[text.index("{") : text.rindex("}") + 1])
    except ValueError:
        return {"error": text[:200]}


def converse(bot: Bot, llm: Any, action: dict[str, Any], persona: str, turns: int) -> list[dict[str, Any]]:
    if llm is None or turns <= 0:
        return []
    transcript, last = [], action["body"]
    role = "customer" if action["send_as"] == "merchant_on_behalf" else "merchant"
    for turn in range(2, 2 + turns):
        inbound = llm(
            f"You are role-playing a {role} of an Indian local business on WhatsApp. "
            f"{PERSONA_PROMPTS[persona]} Output only the message text.",
            f"Their last message:\n{last}",
            200,
        )
        status, out = bot.call(
            "POST",
            "/v1/reply",
            {
                "conversation_id": action["conversation_id"],
                "merchant_id": action["merchant_id"],
                "customer_id": action["customer_id"],
                "from_role": role,
                "message": inbound.strip(),
                "received_at": "2026-04-26T10:50:00Z",
                "turn_number": turn,
            },
        )
        transcript.append({"turn": turn, "inbound": inbound.strip(), "status": status, "response": out})
        if out.get("action") != "send":
            break
        last = out.get("body", "")
    return transcript


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bot-url", default=os.getenv("BOT_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--reply-turns", type=int, default=3, help="persona reply turns per conversation (needs key)")
    parser.add_argument("--limit", type=int, default=38, help="number of cases (30 pairs + 8 extra kinds)")
    args = parser.parse_args()

    cats, merchants, customers, triggers = load("categories"), load("merchants"), load("customers"), load("triggers")
    pairs = json.loads((EXPANDED / "test_pairs.json").read_text(encoding="utf-8"))["pairs"]
    case_ids = ([p["trigger_id"] for p in pairs] + EXTRA)[: args.limit]
    bot, judge_llm = Bot(args.bot_url), make_llm("JUDGE_LLM_MODEL", "claude-sonnet-5")
    persona_llm = make_llm("PERSONA_LLM_MODEL", "claude-haiku-4-5-20251001")

    bot.call("POST", "/v1/teardown", {})
    for scope, items in (("category", cats), ("merchant", merchants), ("customer", customers)):
        for cid, payload in items.items():
            assert bot.push(scope, cid, payload) == 200, (scope, cid)
    _, health = bot.call("GET", "/v1/healthz")
    print(f"[harness] warmup counts: {health.get('contexts_loaded')}", file=sys.stderr)

    actions: list[dict[str, Any]] = []
    for i in range(0, len(case_ids), TICK_BATCH):
        batch = case_ids[i : i + TICK_BATCH]
        for tid in batch:
            bot.push("trigger", tid, triggers[tid])
        _, out = bot.call("POST", "/v1/tick", {"now": f"2026-04-26T10:{i:02d}:00Z", "available_triggers": batch})
        actions += out.get("actions", [])

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    seen_bodies: set[str] = set()
    rows, scores = [], []
    for idx, action in enumerate(actions):
        trig = triggers.get(action["trigger_id"], {})
        merchant = merchants.get(action["merchant_id"], {})
        ctx = {
            "trigger": trig,
            "merchant": merchant,
            "category": cats.get(merchant.get("category_slug", ""), {}),
            "customer": customers.get(action.get("customer_id") or "", {}),
        }
        findings = audit(action["body"], list(ctx.values())).findings
        repeat = text_hash(action["body"]) in seen_bodies
        seen_bodies.add(text_hash(action["body"]))
        score = judge(judge_llm, action, ctx)
        if score and "error" not in score:
            scores.append(
                sum(
                    int(score.get(k, 0))
                    for k in (
                        "specificity",
                        "category_fit",
                        "merchant_fit",
                        "decision_quality",
                        "engagement_compulsion",
                    )
                )
            )
        transcript = converse(bot, persona_llm, action, PERSONAS[idx % len(PERSONAS)], args.reply_turns)
        rows.append(
            {
                "trigger_id": action["trigger_id"],
                "shape_ok": set(action) == FIELDS,
                "body": action["body"],
                "findings": [(f.kind, f.token) for f in findings],
                "similarity": round(plagiarism_ratio(action["body"]), 3),
                "repeat": repeat,
                "url": "http" in action["body"],
                "score": score,
                "transcript": transcript,
            }
        )
    (out_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    tick_lat = bot.latency.get("/v1/tick", [])
    summary = {
        "cases": len(case_ids),
        "actions": len(actions),
        "shape_errors": sum(not r["shape_ok"] for r in rows),
        "grounding_findings": sum(len(r["findings"]) for r in rows),
        "max_similarity": max((r["similarity"] for r in rows), default=0),
        "repeats": sum(r["repeat"] for r in rows),
        "urls": sum(r["url"] for r in rows),
        "judge_avg": round(statistics.mean(scores), 1) if scores else None,
        "judged": len(scores),
        "tick_p50_s": round(pct(tick_lat, 0.5), 2),
        "tick_p99_s": round(pct(tick_lat, 0.99), 2),
        "reply_p99_s": round(pct(bot.latency.get("/v1/reply", []), 0.99), 2),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"[harness] results in {out_dir}", file=sys.stderr)
    return 0 if summary["shape_errors"] == summary["grounding_findings"] == summary["urls"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
