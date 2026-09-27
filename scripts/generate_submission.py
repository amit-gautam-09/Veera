"""Generate submission.jsonl: one line per canonical test pair, produced by bot.compose (challenge brief §7.2).

Usage: python scripts/generate_submission.py [--out submission.jsonl]
Uses the LLM composer when ANTHROPIC_API_KEY is set (outputs cached, so reruns are identical), otherwise the
deterministic composer. Exits 1 if any pair produced no message.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot import compose  # noqa: E402

EXPANDED = ROOT / "reference" / "challenge" / "expanded"
FIELDS = ("body", "cta", "send_as", "suppression_key", "rationale")


def read(folder: str, name: str) -> dict:
    return json.loads((EXPANDED / folder / f"{name}.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "submission.jsonl"))
    args = parser.parse_args()
    pairs = json.loads((EXPANDED / "test_pairs.json").read_text(encoding="utf-8"))["pairs"]
    lines, missing = [], []
    for pair in pairs:
        trigger = read("triggers", pair["trigger_id"])
        merchant = read("merchants", pair["merchant_id"])
        category = read("categories", merchant["category_slug"])
        customer = read("customers", pair["customer_id"]) if pair.get("customer_id") else None
        out = compose(category, merchant, trigger, customer)
        if out.get("skipped"):
            missing.append(pair["test_id"])
        lines.append(json.dumps({"test_id": pair["test_id"], **{k: out[k] for k in FIELDS}}, ensure_ascii=False))
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(lines)} lines to {args.out}" + (f"; no message for {missing}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
