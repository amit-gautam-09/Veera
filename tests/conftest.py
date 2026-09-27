from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vera.app import create_app
from vera.config import Settings

ROOT = Path(__file__).resolve().parents[1]
EXPANDED = ROOT / "reference" / "challenge" / "expanded"
SEED = ROOT / "reference" / "challenge" / "dataset"


def load_dir(name: str) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((EXPANDED / name).glob("*.json"))]


def push(client: TestClient, scope: str, context_id: str, payload: dict[str, Any], version: int = 1) -> Any:
    return client.post(
        "/v1/context",
        json={
            "scope": scope,
            "context_id": context_id,
            "version": version,
            "payload": payload,
            "delivered_at": "2026-04-26T09:45:00Z",
        },
    )


def push_base_dataset(client: TestClient) -> None:
    for cat in load_dir("categories"):
        assert push(client, "category", cat["slug"], cat).status_code == 200
    for m in load_dir("merchants"):
        assert push(client, "merchant", m["merchant_id"], m).status_code == 200
    for c in load_dir("customers"):
        assert push(client, "customer", c["customer_id"], c).status_code == 200


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never call a real LLM (a local .env may configure one); subprocesses inherit this too."""
    monkeypatch.setenv("VERA_LLM_ENABLED", "false")


@pytest.fixture
def settings() -> Settings:
    return Settings(db_path=None, anthropic_api_key=None, contact_email="test@example.com")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def triggers() -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in load_dir("triggers")}
