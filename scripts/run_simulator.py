"""Run the official judge_simulator.py against a bot URL without editing the vendor file.

Config comes from env vars (then `.env`), then CLI flags:
  BOT_URL, JUDGE_LLM_PROVIDER, JUDGE_LLM_API_KEY, JUDGE_LLM_MODEL, JUDGE_SCENARIO

What the wrapper fixes (docs/12 R-21..R-25):
  * re-runs itself in UTF-8 mode (the simulator opens files without an encoding)
  * patches the Anthropic provider to read the first *text* block (newer models can lead with thinking)
  * calls POST /v1/teardown first so warmup starts from zero (skip with --no-teardown)
  * scenarios that do not score (warmup, all, auto_reply_hell, intent_transition, hostile) run without a key
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SIM_PATH = ROOT / "reference" / "challenge" / "judge_simulator.py"
SCORING_SCENARIOS = {"phase2_short", "full_evaluation"}
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
LLM_TIMEOUT_S = 60
JUDGE_RETRIES = 5
JUDGE_RETRY_BASE_S = 8.0
JUDGE_RETRY_MAX_S = 60.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--scenario",
        default=os.getenv("JUDGE_SCENARIO", "all"),
        help="warmup | phase2_short | auto_reply_hell | intent_transition | hostile | all | "
        "full_evaluation (default: $JUDGE_SCENARIO or 'all')",
    )
    parser.add_argument(
        "--bot-url",
        default=os.getenv("BOT_URL", "http://127.0.0.1:8080"),
        help="bot base URL (default: $BOT_URL or http://127.0.0.1:8080)",
    )
    parser.add_argument("--no-teardown", action="store_true", help="do not wipe bot state before running")
    return parser.parse_args()


def load_simulator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("judge_simulator", SIM_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {SIM_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_anthropic(sim: ModuleType) -> None:
    def complete(self: object, prompt: str, system: str | None = None) -> str:
        body = {"model": self.model, "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        req = urlrequest.Request(
            ANTHROPIC_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
        )
        with urlrequest.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return next(block["text"] for block in data["content"] if block.get("type") == "text")

    sim.AnthropicProvider.complete = complete


def patch_retries(sim: ModuleType) -> None:
    """Free-tier judges return 429/503 under load; the vendor code then silently scores by counting digits.
    Retry each judge call with exponential backoff so every message gets a real LLM score."""
    for provider in (
        sim.AnthropicProvider,
        sim.GeminiProvider,
        sim.OpenAIProvider,
        sim.GroqProvider,
        sim.OpenRouterProvider,
        sim.DeepSeekProvider,
    ):
        original = provider.complete

        def complete(self: object, prompt: str, system: str | None = None, _orig: Any = original) -> str:
            delay = JUDGE_RETRY_BASE_S
            for attempt in range(JUDGE_RETRIES + 1):
                try:
                    return str(_orig(self, prompt, system))
                except urlerror.HTTPError as exc:
                    if exc.code not in (429, 500, 503) or attempt == JUDGE_RETRIES:
                        raise
                    print(f"[wrapper] judge HTTP {exc.code}; retry {attempt + 1} in {delay:.0f}s", file=sys.stderr)
                    time.sleep(delay)
                    delay = min(delay * 2, JUDGE_RETRY_MAX_S)
            raise RuntimeError("unreachable")

        provider.complete = complete


def patch_verbose(sim: ModuleType) -> None:
    """full_evaluation hides the judge's reasons; show them (they are the useful part)."""
    original = sim.JudgeSimulator._score_and_display

    def show(self: object, action: dict[str, Any], verbose: bool = True) -> None:
        original(self, action, verbose=True)

    sim.JudgeSimulator._score_and_display = show


def make_null_provider(sim: ModuleType) -> object:
    class NullProvider(sim.LLMProvider):
        def complete(self, prompt: str, system: str | None = None) -> str:
            raise RuntimeError("this scenario needs JUDGE_LLM_API_KEY")

        def name(self) -> str:
            return "none (non-scoring scenario)"

    return NullProvider()


def teardown(bot_url: str) -> None:
    req = urlrequest.Request(
        f"{bot_url.rstrip('/')}/v1/teardown", data=b"{}", method="POST", headers={"Content-Type": "application/json"}
    )
    with urlrequest.urlopen(req, timeout=10) as resp:
        print(f"[wrapper] teardown -> {resp.status} {resp.read().decode('utf-8')}", file=sys.stderr)


def main() -> int:
    if not sys.flags.utf8_mode:  # the vendor file needs UTF-8 mode on Windows
        return subprocess.call([sys.executable, "-X", "utf8", __file__, *sys.argv[1:]])
    load_dotenv(ROOT / ".env", override=False)
    args = parse_args()
    sim = load_simulator()
    sim.BOT_URL = args.bot_url
    sim.TEST_SCENARIO = args.scenario
    sim.LLM_PROVIDER = os.getenv("JUDGE_LLM_PROVIDER", "anthropic")
    sim.LLM_API_KEY = os.getenv("JUDGE_LLM_API_KEY", "")
    sim.LLM_MODEL = os.getenv("JUDGE_LLM_MODEL", "claude-sonnet-5")
    patch_anthropic(sim)
    patch_retries(sim)
    patch_verbose(sim)

    if sim.LLM_API_KEY:
        llm = sim.create_provider()
    elif args.scenario in SCORING_SCENARIOS:
        print("[wrapper] scenario scores messages; set JUDGE_LLM_API_KEY", file=sys.stderr)
        return 1
    else:
        llm = make_null_provider(sim)

    try:
        if not args.no_teardown:
            teardown(args.bot_url)
        ok = sim.JudgeSimulator(llm).run(args.scenario)
    except Exception as exc:  # noqa: BLE001 - report and exit non-zero
        print(f"[wrapper] simulator failed: {exc!r}", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
