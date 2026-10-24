"""#252 Lows from #232: a boot question passes; the credential sent to the seller blocks with no ask verb."""
import pytest

from shield.core import screen

SELLER = {"sender_role": "seller"}


# Round 1 showed "Does your screen show two words on boot?" differs from the honest laptop question by one word, so a
# boot question about a code on the buyer's device stays blocked (fail closed); a code with no buyer device passes.
@pytest.mark.parametrize("text", ["Will your PC display an error code at boot?", "Does the BIOS show a code?"])
def test_a_boot_question_with_no_buyer_screen_passes(text):
    out = screen(text, SELLER, classifier=None)
    assert out["verdict"] == "allow", (text, out["rule_ids"])


@pytest.mark.parametrize("text", [
    "Does your laptop show a code on boot?", "Does your screen show two words on boot?", "Does your phone show a code on boot?",
    "Did you get two words on your screen at BIOS?", "At boot, does your screen show a pair of words?",
])
def test_a_boot_question_about_the_buyers_screen_blocks(text):
    assert screen(text, SELLER, classifier=None)["verdict"] == "block", text


@pytest.mark.parametrize("text", [
    "Our site does not use verification codes.", "Verification codes are not used on this site.",
    "Our box ships with a verification code card.", "Sellers must not request the two words in the order notes.",
])
def test_review_1_honest_lines_pass(text):
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
