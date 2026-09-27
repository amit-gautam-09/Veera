"""Unit tests: numbers, validator rules, salutation, language, consent gate (docs/10 §2)."""

from __future__ import annotations

import pytest

from vera.compose.customer_kinds import consent_gate
from vera.compose.facts import Ctx, build_fact_sheet, signal_label
from vera.compose.numbers import dates_in_text, numbers_in_text, renderings
from vera.compose.validator import validate
from vera.domain.language import customer_language, detect_language, merchant_language
from vera.domain.salutation import customer_name, merchant_opener

CATEGORY = {
    "slug": "dentists",
    "voice": {"vocab_taboo": ["guaranteed", "best price (without supporting data)"]},
    "digest": [{"id": "d1", "source": "JIDA Oct 2026, p.14", "title": "Recall study"}],
    "peer_stats": {"avg_ctr": 0.030},
}
MERCHANT = {
    "merchant_id": "m_1",
    "category_slug": "dentists",
    "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera", "languages": ["en", "hi"]},
    "performance": {"ctr": 0.021, "views": 2410},
    "customer_aggregate": {"lapsed_180d_plus": 78},
}
TRIGGER = {
    "id": "t1",
    "kind": "research_digest",
    "merchant_id": "m_1",
    "payload": {"deadline_iso": "2026-12-15", "top_item_id": "d1"},
}


def _sheet():  # type: ignore[no-untyped-def]
    return build_fact_sheet(Ctx("t1", TRIGGER, MERCHANT, CATEGORY, None), [])


def _check(middle: str, ask: str = "Kya main checklist bana doon?", **kw):  # type: ignore[no-untyped-def]
    params = {"language": "hinglish", "salutation_name": "Meera"} | kw
    return validate("Dr. Meera,", middle, ask, _sheet(), **params)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2,410 views", ["2410"]),
        ("₹1,499 and Rs 299", ["1499", "299"]),
        ("3.0% vs 2.10%", ["3", "2.1"]),
        ("1.2 lakh", ["120000"]),
        ("AT2024-1102", ["2024", "1102"]),
        ("−60%", ["60"]),
    ],
)
def test_numbers_in_text(text: str, expected: list[str]) -> None:
    assert numbers_in_text(text) == expected


def test_renderings_of_fractions() -> None:
    assert {"2.1", "2", "0.021"} <= renderings(0.021)
    assert "50" in renderings(-0.5)
    assert {"19", "7", "30"} <= renderings("2026-04-26T19:30:00+05:30")


def test_dates_in_text() -> None:
    assert dates_in_text("due 15 Dec 2026, or Dec 5, or 2026-11-04") == {(15, 12), (5, 12), (4, 11)}


def test_validator_accepts_grounded_hinglish() -> None:
    check = _check(
        "Aapke 78 patients 180 din se nahi aaye hain; CTR 2.1% hai (JIDA Oct 2026, p.14 study ke hisaab se)."
    )
    assert check.ok, check.violations


@pytest.mark.parametrize(
    ("middle", "code"),
    [
        ("Aapke 31 patients wapas nahi aaye hain.", "V6"),
        ("Deadline 12 Oct hai, aap dhyan dein.", "V7"),
        ("Aapka result guaranteed hai.", "V4"),
        ("Yeh best price hai aapke liye.", "V4"),
        ("Aapka ctr_below_peer_median signal hai.", "V5"),
        ("Details yahan hain: www.example.com dekhiye.", "V3"),
        ("Dr. Sharma ne bhi yeh kiya hai.", "V10"),
        ("Ek Lancet study kehti hai ki yeh kaam karta hai.", "V11"),
        ("FDAX ne approve kiya hai aapke liye.", "V9"),
        ("Kya aap free hain? Main bata doon.", "V1"),
    ],
)
def test_validator_rejects(middle: str, code: str) -> None:
    check = _check(middle)
    assert any(v.startswith(code) for v in check.violations), check.violations


def test_validator_language_and_salutation() -> None:
    assert any(v.startswith("V15") for v in _check("Your CTR is 2.1% this month.", ask="Want a checklist?").violations)
    wrong = validate(
        "Hi Priya,",
        "Aapka CTR 2.1% hai.",
        "Kya main bata doon?",
        _sheet(),
        language="hinglish",
        salutation_name="Meera",
    )
    assert any(v.startswith("V16") for v in wrong.violations)
    action = _check("Yeh raha aapka draft.", ask="Would you like me to change it?", action_mode=True)
    assert any(v.startswith("V17") for v in action.violations)


def test_salutation_rules() -> None:
    dentist = {"identity": {"owner_first_name": "Dr. Asha", "name": "Asha Dental Care"}}
    assert merchant_opener(dentist, "dentists", "english") == "Dr. Asha,"
    pharmacy = {"identity": {"owner_first_name": "Ramesh"}}
    assert merchant_opener(pharmacy, "pharmacies", "hinglish") == "Ramesh ji,"
    assert merchant_opener({"identity": {"name": "Studio Cuts"}}, "salons", "english") == "Studio Cuts team,"
    child = customer_name({"identity": {"name": "Aanya (parent: Sneha)"}})
    assert (child.addressee, child.subject) == ("Sneha", "Aanya")
    assert customer_name({"identity": {"name": "(walk-in, no profile)"}}).walk_in
    senior = customer_name({"identity": {"name": "Mr. Sharma", "senior_citizen": True}})
    assert senior.addressee is None and senior.subject == "Sharma" and senior.senior


def test_language_policy() -> None:
    assert merchant_language({"identity": {"languages": ["en", "hi"]}}, {}) == "hinglish"
    assert merchant_language({"identity": {"languages": ["en", "hi", "ta"]}}, {}) == "english_light_hindi"
    assert merchant_language({"identity": {"languages": ["en", "hi", "mr"]}}, {}) == "hinglish"
    gyms = {"voice": {"code_mix": "english_primary_some_hindi"}}
    assert merchant_language({"identity": {"languages": ["en", "hi"]}}, gyms) == "english_light_hindi"
    assert customer_language({"identity": {"language_pref": "hi-en mix"}}) == "hinglish"
    assert customer_language({"identity": {"language_pref": "te-en mix"}}) == "english"
    assert detect_language("haan theek hai, bhej do") == "hinglish"
    assert detect_language("हाँ ठीक है") == "hinglish"
    assert detect_language("Yes please send it") == "english"


def test_consent_gate() -> None:
    trigger = {"id": "t", "kind": "recall_due", "merchant_id": "m_1", "customer_id": "c", "payload": {}}
    ok = {
        "customer_id": "c",
        "merchant_id": "m_1",
        "identity": {"name": "Priya", "phone_redacted": "<phone>"},
        "consent": {"opted_in_at": "2025-11-04", "scope": ["promotional_offers"]},
        "preferences": {},
    }
    assert consent_gate(Ctx("t", trigger, MERCHANT, CATEGORY, ok)) is None
    assert consent_gate(Ctx("t", trigger, MERCHANT, CATEGORY, None)) == "customer_missing"
    no_consent = ok | {"consent": {"opted_in_at": None, "scope": []}}
    assert consent_gate(Ctx("t", trigger, MERCHANT, CATEGORY, no_consent)) == "no_consent"
    opted_out = ok | {"preferences": {"reminder_opt_in": False}}
    assert consent_gate(Ctx("t", trigger, MERCHANT, CATEGORY, opted_out)) == "reminder_opt_out"
    walk_in = ok | {"identity": {"name": "(walk-in, no profile)", "phone_redacted": "<p>"}}
    assert consent_gate(Ctx("t", trigger, MERCHANT, CATEGORY, walk_in)) == "walk_in"


def test_signal_labels_are_plain_language() -> None:
    assert signal_label("stale_posts:22d") == "last Google post was 22 days ago"
    assert signal_label("dormant_with_vera_14d") == "no reply to Vera in 14 days"
    assert "_" not in signal_label("some_unknown_signal")
