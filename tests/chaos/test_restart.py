"""Restart recovery with a real server process (docs/10 §10, ADR-003). Marked slow: run with `-m slow`."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import ROOT, load_dir

pytestmark = pytest.mark.slow
BOOT_TIMEOUT_S = 20


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start(db: Path, port: int, window: int = 7200) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "PORT": str(port),
        "VERA_DB_PATH": str(db),
        "VERA_RESTORE_WINDOW_S": str(window),
        "ANTHROPIC_API_KEY": "",
        "PYTHONUTF8": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "vera.main"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/v1/healthz", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("server did not boot")


def _push(base: str, scope: str, cid: str, payload: dict[str, Any]) -> None:
    r = httpx.post(f"{base}/v1/context", json={"scope": scope, "context_id": cid, "version": 1, "payload": payload})
    assert r.status_code == 200


def test_state_survives_kill_inside_window_and_is_wiped_outside(tmp_path: Path) -> None:
    db, port = tmp_path / "vera.db", _free_port()
    base = f"http://127.0.0.1:{port}"
    proc = _start(db, port)
    try:
        for cat in load_dir("categories"):
            _push(base, "category", cat["slug"], cat)
        for m in load_dir("merchants")[:10]:
            _push(base, "merchant", m["merchant_id"], m)
        trig = json.loads(
            (ROOT / "reference/challenge/expanded/triggers/trg_004_perf_dip_bharat.json").read_text("utf-8")
        )
        _push(base, "trigger", trig["id"], trig)
        tick = httpx.post(f"{base}/v1/tick", json={"now": "2026-04-26T10:00:00Z", "available_triggers": [trig["id"]]})
        assert len(tick.json()["actions"]) == 1
        canned = {
            "conversation_id": "c_auto",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "message": "Thank you for contacting us! Our team will respond shortly.",
            "turn_number": 2,
        }
        assert httpx.post(f"{base}/v1/reply", json=canned).json()["action"] == "send"
    finally:
        proc.kill()
        proc.wait()

    proc = _start(db, port)  # restart inside the window
    try:
        counts = httpx.get(f"{base}/v1/healthz").json()["contexts_loaded"]
        assert counts == {"category": 5, "merchant": 10, "customer": 0, "trigger": 1}
        again = httpx.post(f"{base}/v1/tick", json={"now": "2026-04-26T10:05:00Z", "available_triggers": [trig["id"]]})
        assert again.json()["actions"] == []  # suppression survived
        canned["conversation_id"] = "c_auto_2"
        assert httpx.post(f"{base}/v1/reply", json=canned).json()["action"] == "wait"  # auto-reply ladder survived
    finally:
        proc.kill()
        proc.wait()

    proc = _start(db, port, window=0)  # boot outside the window: wiped
    try:
        counts = httpx.get(f"{base}/v1/healthz").json()["contexts_loaded"]
        assert counts == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    finally:
        proc.kill()
        proc.wait()
