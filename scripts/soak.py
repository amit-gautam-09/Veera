"""Soak test: mixed traffic at a fixed request rate against a running bot (docs/10 §10).

Usage: python scripts/soak.py [--bot-url URL] [--minutes 45] [--rps 10]
Pass criteria: zero 5xx, zero timeouts, zero invalid bodies, healthz counts intact at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
EXPANDED = ROOT / "reference" / "challenge" / "expanded"
BUDGET_S = {"/v1/healthz": 0.2, "/v1/context": 0.2, "/v1/tick": 8.0, "/v1/reply": 6.0}
REPLIES = [
    "Yes please go ahead",
    "Thank you for contacting us! Our team will respond shortly.",
    "busy, call later",
    "What will it cost?",
    "haan theek hai",
    "Not interested",
    "Can you help with GST?",
    "2",
]
SEED = 7


def load(folder: str) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((EXPANDED / folder).glob("*.json"))]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bot-url", default=os.getenv("BOT_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--minutes", type=float, default=45.0)
    parser.add_argument("--rps", type=float, default=10.0)
    args = parser.parse_args()
    rnd = random.Random(SEED)
    cats, merchants, customers, triggers = load("categories"), load("merchants"), load("customers"), load("triggers")
    stats: dict[str, list[float]] = {}
    failures: list[str] = []
    version = {"v": 1}

    async with httpx.AsyncClient(base_url=args.bot_url, timeout=30) as client:
        await client.post("/v1/teardown")
        for scope, items, key in (
            ("category", cats, "slug"),
            ("merchant", merchants, "merchant_id"),
            ("customer", customers, "customer_id"),
            ("trigger", triggers, "id"),
        ):
            for item in items:
                await client.post(
                    "/v1/context", json={"scope": scope, "context_id": item[key], "version": 1, "payload": item}
                )

        async def op(path: str, method: str = "POST", body: dict[str, Any] | None = None) -> None:
            started = time.monotonic()
            try:
                r = await (client.get(path) if method == "GET" else client.post(path, json=body))
                elapsed = time.monotonic() - started
                stats.setdefault(path, []).append(elapsed)
                if r.status_code >= 500 or elapsed > BUDGET_S[path]:
                    failures.append(f"{path} {r.status_code} {elapsed:.2f}s")
                r.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                failures.append(f"{path} {type(exc).__name__}")

        def next_op() -> Any:
            roll = rnd.random()
            if roll < 0.4:
                return op("/v1/healthz", "GET")
            if roll < 0.6:
                ids = [t["id"] for t in rnd.sample(triggers, 5)]
                return op("/v1/tick", body={"now": "2026-04-26T10:00:00Z", "available_triggers": ids})
            if roll < 0.85:
                m = rnd.choice(merchants)
                return op(
                    "/v1/reply",
                    body={
                        "conversation_id": f"soak_{rnd.randint(1, 300)}",
                        "merchant_id": m["merchant_id"],
                        "message": rnd.choice(REPLIES),
                        "turn_number": rnd.randint(2, 6),
                    },
                )
            version["v"] += 1
            m = rnd.choice(merchants)
            return op(
                "/v1/context",
                body={"scope": "merchant", "context_id": m["merchant_id"], "version": version["v"], "payload": m},
            )

        end, interval, tasks = time.monotonic() + args.minutes * 60, 1 / args.rps, []
        while time.monotonic() < end:
            tasks.append(asyncio.create_task(next_op()))
            await asyncio.sleep(interval)
        await asyncio.gather(*tasks)
        health = (await client.get("/v1/healthz")).json()

    for path, values in sorted(stats.items()):
        values.sort()
        print(
            f"{path:14} n={len(values):5} p50={values[len(values) // 2]:.3f}s p99={values[int(len(values) * 0.99) - 1]:.3f}s"
        )
    counts = health.get("contexts_loaded", {})
    print(f"healthz at end: {counts}")
    print(f"failures: {len(failures)}" + (f" e.g. {failures[:5]}" if failures else ""))
    intact = counts.get("category") == 5 and counts.get("merchant") == 50 and counts.get("customer") == 200
    return 0 if not failures and intact else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
