"""Provider selection (ADR-012) and the customer-facing sender rule V18."""

from __future__ import annotations

import pytest

from tests.unit.test_compose_rules import _sheet
from vera.compose.validator import validate
from vera.config import Settings, load_settings
from vera.llm.gateway import AnthropicGateway, OpenAICompatibleGateway, make_gateway


def test_make_gateway_by_provider() -> None:
    assert make_gateway(Settings()) is None  # no key: deterministic mode
    assert isinstance(make_gateway(Settings(anthropic_api_key="x")), AnthropicGateway)
    gem = make_gateway(Settings(llm_provider="gemini", llm_api_key="x", composer_model="gemini-3.5-flash-lite"))
    assert isinstance(gem, OpenAICompatibleGateway) and gem.model == "gemini-3.5-flash-lite"
    assert make_gateway(Settings(llm_provider="gemini", llm_api_key="x", llm_enabled=False)) is None


def test_gemini_defaults_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("VERA_COMPOSER_MODEL", "VERA_LLM_EFFORT", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("VERA_LLM_ENABLED", "true")
    monkeypatch.setenv("VERA_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("VERA_LLM_API_KEY", "k")
    s = load_settings()
    assert (s.composer_model, s.llm_effort, s.llm_active) == ("gemini-3.5-flash-lite", "low", True)


def test_v18_customer_message_names_the_business() -> None:
    ok = validate(
        "Hi Priya,",
        "Dr. Meera's clinic se: aapki cleaning due hai.",
        "Kya slot book kar dein?",
        _sheet(),
        language="hinglish",
        salutation_name="Priya",
        business_name="Dr. Meera's Dental Clinic",
    )
    assert not any(v.startswith("V18") for v in ok.violations)
    bad = validate(
        "Hi Priya,",
        "Aapki cleaning due hai aur slots khaali hain.",
        "Kya slot book kar dein?",
        _sheet(),
        language="hinglish",
        salutation_name="Priya",
        business_name="Dr. Meera's Dental Clinic",
    )
    assert any(v.startswith("V18") for v in bad.violations)
