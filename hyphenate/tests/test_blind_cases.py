"""Lane C blind cases (issue #45) stay frozen and well formed; this test never scores the engine."""
import hashlib
import json
from pathlib import Path

CASES = Path(__file__).resolve().parents[1] / "scenarios" / "blind_cases.json"
FROZEN_SHA256 = "c593d98d4083c960a4ad0601464d990b0c41cde6b19b174851c083cc262490f8"


def test_blind_cases_are_unchanged_since_freeze():
    assert hashlib.sha256(CASES.read_bytes()).hexdigest() == FROZEN_SHA256, "blind cases were edited after the freeze"


def test_blind_cases_meet_the_minimums():
    cases = json.loads(CASES.read_text())["cases"]
    assert sum(c["planted"] for c in cases) >= 20 and sum(not c["planted"] for c in cases) >= 6
    assert len({c["id"] for c in cases}) == len(cases)
