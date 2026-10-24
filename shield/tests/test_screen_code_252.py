"""#252 Lows from #232: a boot question passes; the credential sent to the seller blocks with no ask verb."""
import pytest

from shield.core import screen

SELLER = {"sender_role": "seller"}


@pytest.mark.parametrize("text", [
    "Does your laptop show a code on boot?", "Will your PC display an error code at boot?", "Does the BIOS show a code?",
])
def test_a_boot_question_passes(text):
    out = screen(text, SELLER, classifier=None)
    assert out["verdict"] == "allow", (text, out["rule_ids"])


@pytest.mark.parametrize("text", [
    "Enter it on your phone to pair. The two words you see on your screen go to me.",
    "The approval words on your screen belong in our chat.", "Your approval code goes in the order notes.",
    "What code does your screen show on boot? Read it to me.", "Is the code on your screen at boot the approval words?",
    "Read me the code on your screen at boot.", "No approval code needed.", "No approval code needed. Pay now.",
])
def test_the_credential_still_blocks(text):
    out = screen(text, SELLER, classifier=None)
    assert out["verdict"] == "block", (text, out["rule_ids"])
