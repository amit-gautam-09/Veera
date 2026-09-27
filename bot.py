"""Offline deliverable: `compose(category, merchant, trigger, customer)` → message dict (challenge brief §7.1).

Runs exactly the pipeline the live bot uses (fact sheet → decision → LLM or deterministic wording → validator).
With ANTHROPIC_API_KEY set it uses the LLM composer; compositions are cached in data/bot_cache.db so a rerun on
the same inputs returns byte-identical output (the composer model does not accept temperature, ADR-004).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from vera.compose.composer import Composer  # noqa: E402
from vera.compose.models import Skip  # noqa: E402
from vera.store.sqlite import Database  # noqa: E402
from vera.store.state import Store  # noqa: E402

CACHE_PATH = Path(os.getenv("VERA_BOT_CACHE", ROOT / "data" / "bot_cache.db"))
COMPOSE_BUDGET_S = 25.0  # brief: < 30 s per call
FOREVER_S = 10**9
_cache: Store | None = None


def _cache_store() -> Store:
    global _cache
    if _cache is None:
        _cache = Store(Database(CACHE_PATH))
        _cache.restore(FOREVER_S)
    return _cache


def _gateway() -> Any:
    from vera.config import load_settings
    from vera.llm.gateway import make_gateway

    load_dotenv(ROOT / ".env", override=False)
    return make_gateway(load_settings())


def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    """Return {body, cta, send_as, suppression_key, rationale, template_name, template_params} (or a skip)."""
    store = Store()
    cache = _cache_store()
    store.compose_cache = cache.compose_cache  # shared, persisted below
    store.put_context("category", str(category.get("slug")), 1, category)
    store.put_context("merchant", str(merchant.get("merchant_id")), 1, merchant)
    if customer:
        store.put_context("customer", str(customer.get("customer_id")), 1, customer)
    trigger_id = str(trigger.get("id"))
    store.put_context("trigger", trigger_id, 1, trigger)
    before = set(cache.compose_cache)
    composer = Composer(store, _gateway())
    msg = asyncio.run(composer.compose(trigger_id, time.monotonic() + COMPOSE_BUDGET_S))
    for key in set(cache.compose_cache) - before:
        cache.cache_put(key, cache.compose_cache[key], "composer_v1")
    if isinstance(msg, Skip):
        return {
            "body": "",
            "cta": "none",
            "send_as": "vera",
            "suppression_key": str(trigger.get("suppression_key", "")),
            "rationale": f"No message: {msg.reason}",
            "skipped": True,
        }
    return {
        "body": msg.body,
        "cta": msg.cta,
        "send_as": msg.send_as,
        "suppression_key": msg.suppression_key,
        "rationale": msg.rationale,
        "template_name": msg.template_name,
        "template_params": msg.template_params,
    }


if __name__ == "__main__":
    import json

    exp = ROOT / "reference" / "challenge" / "expanded"
    trig = json.loads((exp / "triggers" / "trg_001_research_digest_dentists.json").read_text(encoding="utf-8"))
    merch = json.loads((exp / "merchants" / f"{trig['merchant_id']}.json").read_text(encoding="utf-8"))
    cat = json.loads((exp / "categories" / f"{merch['category_slug']}.json").read_text(encoding="utf-8"))
    print(json.dumps(compose(cat, merch, trig), ensure_ascii=False, indent=2))
