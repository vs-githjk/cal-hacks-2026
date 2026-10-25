"""The Trickster (FlashDeal Frankie, seller_3): rotates tricks, learns which got caught, and every trick is caught by a
real checker (Advocate, claim check or Smell Test)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # agents/, for advocate.checks and common

from advocate import checks as advocate  # noqa: E402
import common  # noqa: E402
from agents.sellers import trickster  # noqa: E402
from agents.sellers.policy import make_bid, seller as load_seller  # noqa: E402
from data.claim_check import check_claim  # noqa: E402
from shield.core import screen  # noqa: E402

TI = "rtx 5070 ti"
MARKET_ID = "seller-c"


def need(nid="need-1"):
    return {"id": nid, "source": "sim", "items": [{"sku_spec": TI, "condition": "new", "allowed_conditions": ["new"],
                                                    "variant": "retail", "quantity": 1}], "owned": {}}


def frankie_bid(nid="need-1"):
    return make_bid(need(nid), load_seller("seller_3"))


def loss(rid, round_id, reason="price", band="within5"):
    return {"id": rid, "round_id": round_id, "seller_id": MARKET_ID, "won": False, "gap_band": band, "reason": reason,
            "source_url": "https://shop.example/x", "created_at": "2026-10-25T01:00:00Z"}


# ---- rotation and learning -------------------------------------------------

def test_every_caught_trick_rotates_out_and_all_four_are_used_before_any_repeats():
    st = trickster.fresh()
    seen = []
    for n in range(1, 5):
        seen.append(trickster.choose(st, f"need-{n}"))
        trickster.observe_report(st, loss(f"l{n}", f"round-need-{n}", "advocate_veto"), MARKET_ID)
    assert seen == list(trickster.TRICKS) and len(set(seen)) == 4
    assert trickster.choose(st, "need-5") == trickster.TRICKS[0]   # all caught once: round robin starts over


def test_a_trick_that_survived_is_preferred_over_one_that_was_caught():
    st = trickster.fresh()
    for n in range(1, 5):                               # try each once; only the hidden fee survives (lost on price)
        t = trickster.choose(st, f"need-{n}")
        trickster.observe_report(st, loss(f"l{n}", f"round-need-{n}", "price" if t == "hidden_fee" else "advocate_veto"),
                                 MARKET_ID)
    assert trickster.choose(st, "need-5") == "hidden_fee"
    assert st["caught"]["hidden_fee"] == 0 and st["caught"]["condition_lie"] == 1


def test_silence_counts_as_caught_and_the_same_round_keeps_its_trick():
    st = trickster.fresh()
    first = trickster.choose(st, "need-1")
    assert trickster.choose(st, "need-1") == first and st["tried"][first] == 1
    second = trickster.choose(st, "need-2")              # nothing came back for round 1
    assert second != first and st["caught"][first] == 1
    assert st["history"][-1] == {"need_id": "need-1", "trick": first, "outcome": "caught", "presumed": True}


def test_reports_for_other_rounds_duplicates_and_foreign_reports_do_not_move_it():
    st = trickster.fresh()
    trickster.choose(st, "need-1")
    assert trickster.observe_report(st, loss("a", "round-other", "advocate_veto"), MARKET_ID)
    assert st["current"]["outcome"] is None
    assert trickster.observe_report(st, loss("b", "round-need-1", "advocate_veto"), MARKET_ID)
    assert not trickster.observe_report(st, loss("b", "round-need-1", "advocate_veto"), MARKET_ID)
    assert st["caught"]["condition_lie"] == 1
    with pytest.raises(ValueError):
        trickster.observe_report(st, {**loss("c", "round-need-1"), "seller_id": "seller-a"}, MARKET_ID)


def test_state_check_rejects_a_corrupt_row():
    assert trickster.check(trickster.fresh())
    with pytest.raises(ValueError):
        trickster.check({"v": 1, "current": None, "tried": {}, "caught": {}, "history": [], "seen": []})


# ---- every trick is caught -------------------------------------------------

def _fetch(pages):
    return lambda url: pages[url]


def test_condition_lie_is_vetoed_by_the_advocate_with_the_listing_as_source():
    bid, pages = trickster.apply("condition_lie", frankie_bid())
    line = bid["lines"][0]
    assert line["offered_condition"] == "new" and line["page_condition"] == "open-box"
    cards = advocate.advise(need(), [bid], {}, {}, [], owned={})
    assert cards[0]["recommendation"] == "veto" and cards[0]["rule_id"] == "advocate.condition"
    assert cards[0]["source_url"] == line["listing_url"]
    claim = trickster.claim_for("condition_lie", bid)
    got = check_claim(claim, fetch=_fetch(pages))
    assert got["result"] == "false" and "open-box" in got["reason"]


def test_hidden_fee_is_caught_by_the_claim_check_against_the_listing_page():
    bid, pages = trickster.apply("hidden_fee", frankie_bid())
    assert bid["lines"][0]["offered_condition"] == bid["lines"][0]["page_condition"] == "new"   # the only lie is the fee
    assert "no fees" in " ".join(bid["claims"])
    got = check_claim(trickster.claim_for("hidden_fee", bid), fetch=_fetch(pages))
    assert got["result"] == "false"
    assert "differs from the listing" in got["reason"]
    unit = bid["lines"][0]["unit_price"]
    assert f"${unit:,.2f}" in got["reason"] and f"${unit + trickster._fee(unit):,.2f}" in got["reason"]
    assert common.validate("Claim", {"id": "c1", "bid_id": bid["id"], "text": "all-in price", "kind": "fees",
                                     "check": got["result"], "evidence_url": got["evidence_url"],
                                     "checked_at": got["checked_at"], "method": got["method"],
                                     "evidence_hash": got["evidence_hash"], "source": "simulated",
                                     "origin": "SIM", "reason": got["reason"]})
    assert advocate.advise(need(), [bid], {}, {}, [], owned={})[0]["recommendation"] != "veto"   # only the claim check sees this one


def test_fake_warranty_is_caught_by_the_claim_check_against_the_listing_page():
    bid, pages = trickster.apply("fake_warranty", frankie_bid())
    assert "3-year warranty included" in bid["claims"]
    got = check_claim(trickster.claim_for("fake_warranty", bid), fetch=_fetch(pages))
    assert got["result"] == "false"
    assert "36 months" in got["reason"] and "1 months" in got["reason"]


def test_prompt_injection_is_blocked_by_the_smell_test_before_the_bid_is_ranked():
    bid, _ = trickster.apply("prompt_injection", frankie_bid())
    assert trickster.INJECTION in bid["claims"]
    verdict = screen(json.dumps(bid) + "\n" + trickster.lie_line("prompt_injection"), {"sender_role": "seller"})
    assert verdict["verdict"] == "block"
    assert "shield.override.instruction" in verdict["rule_ids"]


@pytest.mark.parametrize("trick", trickster.TRICKS)
def test_each_trick_bid_is_valid_floor_safe_and_hides_nothing_in_its_own_fields(trick):
    base = frankie_bid()
    bid, pages = trickster.apply(trick, base)
    common.validate("Bid", bid)
    assert bid["floor_check_passed"] and bid["lines"][0]["unit_price"] == base["lines"][0]["unit_price"]
    assert bid["total_landed_price"] == base["total_landed_price"]       # the lie is never in the money the market ranks
    assert "trick" not in json.dumps(bid).lower()                       # the bid never names the trick
    assert set(pages) == {l["listing_url"] for l in bid["lines"]}
    assert base["claims"] == load_seller("seller_3")["claims"]           # apply never mutates the input


def test_an_honest_seller_passes_the_same_checks_the_trickster_fails():
    s = load_seller("seller_1")
    from agents.sellers import listing_pages
    bid = make_bid({**need(), "items": [dict(need()["items"][0], sku_spec="rtx 5070 ti")]}, s)
    line = bid["lines"][0]
    page = listing_pages.render(listing_pages.facts_for_line(line, seller_id="byte-bros", warranty_months=12, return_days=30), "x")
    ok = check_claim({"text": "brand new, sealed", "evidence_url": line["listing_url"]}, fetch=lambda u: page)
    assert ok["result"] == "verified"
    assert advocate.advise(need(), [bid], {}, {}, [], owned={})[0]["recommendation"] != "veto"
