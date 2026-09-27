import json
from pathlib import Path

import vera

EXPANDED = Path(__file__).resolve().parents[1] / "reference" / "challenge" / "expanded"
EXPECTED_COUNTS = {"categories": 5, "merchants": 50, "customers": 200, "triggers": 100}
EXPECTED_TEST_PAIRS = 30


def test_package_imports() -> None:
    assert vera.__version__


def test_expanded_dataset_counts() -> None:
    for folder, expected in EXPECTED_COUNTS.items():
        assert len(list((EXPANDED / folder).glob("*.json"))) == expected, folder
    pairs = json.loads((EXPANDED / "test_pairs.json").read_text(encoding="utf-8"))["pairs"]
    assert len(pairs) == EXPECTED_TEST_PAIRS
