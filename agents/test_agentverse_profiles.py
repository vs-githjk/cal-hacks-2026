"""Agentverse profile text for the agents this lane owns: the Fish Market name, complete-goal starter prompts, keywords (RT-8, PL-28).
Offline: reads the README files only."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
PROFILES = {"buyer/AGENTVERSE.md": "Fish Market Buyer", "caller/AGENTVERSE.md": "Fish Market Caller",
            "pulse/AGENTVERSE.md": "Market Pulse", "SHIELD_AGENTVERSE.md": "Fish Market Smell Test"}


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"no '## {heading}' section"
    return m.group(1)


@pytest.mark.parametrize("rel,title", PROFILES.items())
def test_the_profile_has_its_name_badges_and_the_fish_market_name(rel, title):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert text.startswith(f"# {title}\n")
    assert "tag:innovationlab" in text and "tag:hackathon" in text
    assert "Fish Market" in section(text, "Summary") if "## Summary" in text else "Fish Market" in text


@pytest.mark.parametrize("rel", PROFILES)
def test_starter_prompts_are_complete_goals_not_fragments(rel):
    prompts = re.findall(r'^- "(.+)"', section((ROOT / rel).read_text(encoding="utf-8"), "Starter prompts"), re.M)
    assert len(prompts) >= 3, rel
    for p in prompts:
        assert len(p.split()) >= 15, f"{rel}: too short to be a goal: {p!r}"
        assert p[-1] in ".?'", f"{rel}: a goal ends like a sentence: {p!r}"
    assert len(set(prompts)) == len(prompts)


@pytest.mark.parametrize("rel", PROFILES)
def test_keywords_are_a_short_unique_list_that_names_fish_market(rel):
    body = section((ROOT / rel).read_text(encoding="utf-8"), "Keywords").strip()
    words = [w.strip() for w in body.split(",")]
    assert 8 <= len(words) <= 16 and all(words), rel
    assert len({w.lower() for w in words}) == len(words), f"{rel}: repeated keyword"
    assert "Fish Market" in words


@pytest.mark.parametrize("rel", PROFILES)
def test_no_dash_characters_and_no_claim_the_code_cannot_back(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert chr(0x2014) not in text and chr(0x2013) not in text
    for banned in ("not wired yet", "2FA", "biometric authentication", "unhackable", "guaranteed safe"):
        assert banned not in text, banned


def test_the_caller_profile_says_what_it_is_and_why_the_buyer_cannot_approve_alone():
    text = (ROOT / "caller/AGENTVERSE.md").read_text(encoding="utf-8")
    assert "second-factor agent" in text and "cannot approve its own spend" in text
    assert "expires_at" in text and "Web buyers" in text and "BUYER_DELEGATE_CALL=1" in text


def test_the_pulse_profile_names_the_fair_band_the_coaching_numbers_and_the_going_price():
    text = (ROOT / "pulse/AGENTVERSE.md").read_text(encoding="utf-8")
    assert "fair-price band" in text and "you lost by less than 5 percent" in text and "3.1%" not in text and "going price" in text.lower()
    assert "PulseBandRequest" in text and "SIM" in text and "MIRROR" in text and "SANDBOX" in text
    for q in ("How did RTX 5070 Ti prices move this week?", "Which seller won the most GPU rounds", "Is Byte Bros CRS verified?"):
        assert q in text, q                                                  # the phase 2 (cited retrieval) starter prompts
