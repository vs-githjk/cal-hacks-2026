"""ReNew Refurb (seller_5): labelled refurbished and open-box lines, the tradeoff in plain words, all of it checkable."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from advocate import checks as advocate  # noqa: E402
import common  # noqa: E402
from agents.sellers import refurb  # noqa: E402
from agents.sellers.policy import make_bid, seller as load_seller  # noqa: E402
from data.claim_check import check_claim  # noqa: E402

TI, PSU = "rtx 5070 ti", "psu 750w"


def need(*skus, allowed=("refurbished", "open-box")):
    return {"id": "need-1", "source": "sim", "owned": {},
            "items": [{"sku_spec": s, "condition": allowed[0], "allowed_conditions": list(allowed),
                       "variant": "retail", "quantity": 1} for s in skus]}


def renew_bid(*skus):
    return make_bid(need(*skus), load_seller("seller_5"))


def test_one_bid_carries_both_conditions_each_labelled_and_the_tradeoff_is_exact():
    bid = refurb.decorate(renew_bid(TI))
    lines = sorted(bid["lines"], key=lambda l: l["unit_price"])
    assert [l["offered_condition"] for l in lines] == ["refurbished", "open-box"]
    assert all(l["offered_condition"] == l["page_condition"] for l in lines)   # honest: label equals the page
    diff = round(lines[1]["unit_price"] - lines[0]["unit_price"], 2)
    assert bid["tradeoff"] == [f"{TI}: the refurbished line is ${diff:,.2f} less than my open-box line, with a 90-day "
                               "warranty instead of 1-year."]
    assert bid["tradeoff"][0] in bid["decision_trace"]
    assert refurb.persona(bid) == "ReNew Refurb here. " + bid["tradeoff"][0]
    common.validate("Bid", bid)


def test_decorating_never_changes_prices_lines_or_total():
    base = renew_bid(TI, PSU)
    bid = refurb.decorate(base)
    assert bid["lines"] == base["lines"] and bid["total_landed_price"] == base["total_landed_price"]
    assert base["claims"] == load_seller("seller_5")["claims"]            # the input is not mutated
    assert len(bid["tradeoff"]) == 2


def test_a_part_with_one_line_states_its_terms_without_inventing_a_comparison():
    bid = refurb.decorate(make_bid(need("rtx 4070 super 12gb", allowed=("refurbished",)), load_seller("seller_5")))
    assert bid["tradeoff"][0].startswith("rtx 4070 super 12gb: refurbished at $")
    assert "may show light cosmetic wear" in bid["tradeoff"][0] and "instead of" not in bid["tradeoff"][0]


def test_every_number_in_the_words_comes_from_the_bid_or_the_terms():
    bid = refurb.decorate(renew_bid(TI))
    allowed = {f"{l['unit_price'] - min(x['unit_price'] for x in bid['lines']):,.2f}" for l in bid["lines"]} | {"90", "1"}
    spoken = re.findall(r"\d[\d,]*\.?\d*", refurb.persona(bid).replace(TI, "part"))
    assert all(n.rstrip(".") in allowed for n in spoken)


def test_its_claims_are_verified_against_its_own_pages_and_the_advocate_does_not_veto():
    bid = refurb.decorate(renew_bid(TI))
    pages = refurb.pages_for(bid)
    for line in bid["lines"]:
        got = check_claim(refurb.claim_for_line(line), fetch=lambda u: pages[u])
        assert got["result"] == "verified", (line["offered_condition"], got["reason"])
    cards = advocate.advise(need(TI), [bid], {}, {}, [], owned={})
    assert "advocate.condition" not in {w["rule_id"] for w in cards[0]["warnings"]}


def test_a_changed_term_would_be_caught_so_the_check_is_real():
    bid = refurb.decorate(renew_bid(TI))
    pages = refurb.pages_for(bid)
    line = next(l for l in bid["lines"] if l["offered_condition"] == "refurbished")
    claim = {"text": "refurbished: 12-month warranty, 14-day returns", "evidence_url": line["listing_url"]}
    assert check_claim(claim, fetch=lambda u: pages[u])["result"] == "false"
