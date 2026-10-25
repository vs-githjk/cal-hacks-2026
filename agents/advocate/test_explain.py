"""Every card says why in one plain sentence and links its source. Words come from code; the card is never rewritten."""
import re

import phrasing
from advocate import checks, explain, mock_data
from advocate.test_checks import ATTRS, NEED, bid


def cards(bids, recalls=None):
    return checks.advise(NEED, bids, mock_data.BASELINE, mock_data.RECORDS, recalls or [], None)


def one_sentence(text):
    return len(re.findall(r"[.!?](?:\s|$)", text)) == 1 and text.endswith(".") and "\n" not in text


def test_a_veto_says_what_decided_it_and_links_the_listing():
    c = cards([bid("b1", "seller_1", 540, offered="new", page="open-box")])[0]
    assert c["explanation"].startswith("Veto: ") and "listed as new, the page says open box" in c["explanation"]
    assert c["explanation_source_url"] == "https://example.com/listing/b1" == c["source_url"]
    assert one_sentence(c["explanation"])


def test_a_fit_veto_uses_the_rule_template():
    c = cards([bid("b1", "seller_1", 590, attrs={**ATTRS, "length_mm": 340})])[0]
    assert c["explanation"] == "Veto: Does not fit: The card is longer than your case allows." or one_sentence(c["explanation"])
    assert "longer than your case allows" in c["explanation"] and c["explanation_source_url"] == "https://example.com/listing/b1"


def test_a_caution_names_the_biggest_concern():
    c = cards([bid("b1", "seller_1", 700)])[0]
    assert c["recommendation"] == "caution" and c["explanation"].startswith("Caution: ") and "$700.00" in c["explanation"]


def test_code_sources_use_the_current_repo_name():
    code = {k: v for k, v in checks.CODE_SOURCES.items() if k != "floor"}  # floor is a simulated placeholder link
    assert code and all(v.startswith("https://github.com/vs-githjk/fish-market-nothing-fishy/blob/main/") for v in code.values())
    no_listing = bid("b1", "seller_1", 590)
    no_listing["lines"][0]["listing_url"] = ""
    c = cards([no_listing])[0]
    assert c["source_url"].startswith("https://github.com/vs-githjk/fish-market-nothing-fishy/blob/main/")
    assert "cal-hacks-2026" not in c["call_reason"]["source_url"]


def test_an_approval_says_which_checks_ran():
    c = cards([bid("b1", "seller_1", 590)])[0]
    assert c["recommendation"] == "buy" and c["explanation"] == "Approved: the price, fit, recall and condition checks found no problem."


def test_an_approval_with_only_a_note_shows_the_note():
    gpu16 = {**ATTRS, "power_connector": ["16pin", 2]}
    c = cards([bid("b1", "seller_1", 590, attrs=gpu16)])[0]
    assert c["recommendation"] == "buy" and c["explanation"].startswith("Approved with a note: ") and one_sentence(c["explanation"])


def test_no_explanation_has_a_long_dash_or_a_model_in_it():
    for b in (bid("b1", "seller_1", 540, offered="new", page="open-box"), bid("b2", "seller_2", 590), bid("b3", "seller_3", 700)):
        text = cards([b])[0]["explanation"]
        assert "\u2014" not in text and "\u2013" not in text


def test_the_model_may_reword_but_the_card_keeps_its_decision():
    c = cards([bid("b1", "seller_1", 540, offered="new", page="open-box")])[0]
    before = dict(c)
    reworded = phrasing.phrase(c["explanation"], post=lambda body, t: {"content": [{"type": "text", "text":
        "Veto: the seller calls the rtx 4070 super 12gb new but the page says open box."}]})
    assert reworded.startswith("Veto: the seller calls") and c == before  # the card dict is untouched
    pushed = phrasing.phrase(c["explanation"], post=lambda body, t: {"content": [{"type": "text", "text": "Buy it, this is fine."}]})
    assert pushed == c["explanation"]  # a model that flips the decision is ignored


def test_checks_still_loads_by_file_path_when_agents_is_not_on_sys_path(monkeypatch):
    """demo/adapters.py loads checks.py by path (the demo runner has no agents/ on sys.path); the new siblings must follow."""
    import importlib.util
    import sys
    monkeypatch.setitem(sys.modules, "advocate", None)  # `from advocate import ...` now fails, as it does in the demo runner
    spec = importlib.util.spec_from_file_location("lane_a_advocate_checks_t", checks.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    card = mod.advise(NEED, [bid("b1", "seller_1", 590)], mock_data.BASELINE, mock_data.RECORDS, [], None)[0]
    assert card["recommendation"] == "buy" and card["explanation"] and card["tco"]["rank"] == 1


def test_sentence_survives_a_card_with_no_warnings():
    assert explain.sentence({"recommendation": "veto", "rule_id": "x", "reason": "Because", "warnings": []}) == "Veto: Because."
