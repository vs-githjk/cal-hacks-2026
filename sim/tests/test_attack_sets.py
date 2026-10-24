"""c8: the held-out and voice sets stay well formed (this test never scores Shield)."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "attacks"


def rows(name):
    return [json.loads(line) for line in (HERE / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_held_out_has_20_attacks_and_10_clean():
    r = rows("held_out.jsonl")
    assert sum(x["label"] == "attack" for x in r) == 20 and sum(x["label"] == "clean" for x in r) == 10
    assert len({x["id"] for x in r}) == 30
    for x in r:
        assert {"id", "category", "label", "message", "context", "expect_rule", "source"} <= x.keys()
        assert x["expect_rule"] is None, "held-out cases must not name Shield rules"
        assert x["origin"] == "SIM"


def test_voice_has_the_10_kickoff_cases_and_never_approves():
    r = rows("voice.jsonl")
    assert [x["case"] for x in r] == ["wrong_code", "replayed_code", "yes_without_code", "other_amount", "silence",
                                      "injected_why_answer", "noisy_audio", "second_approval", "expired_code", "other_deals_code"]
    assert all(x["expect"]["approved"] is False and x["expect"]["result"] in ("deny", "no_answer", "expired") for x in r)


def test_test_identities_only():
    text = (HERE / "held_out.jsonl").read_text() + (HERE / "voice.jsonl").read_text()
    for addr in re.findall(r"[\w.+-]+@[\w.-]+", text):
        assert addr.rstrip(".").endswith(".test"), addr
    assert not re.search(r"\+?\d[\d\s().-]{9,}\d", re.sub(r"[\d,.]+\s?(mm|W|GB|%)|\$[\d,.]+", "", text)), "no phone numbers"
