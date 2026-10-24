import common
from advocate import checks, mock_data

TH = "chicken thigh, USDA Grade A, 40lb case"
TOM = "roma tomato, US No. 1, 25lb case"
URL = mock_data.USDA_URL
BASELINE = {TH: {"unit_price": 2.10, "source_url": URL}, TOM: {"unit_price": 1.20, "source_url": URL}}
SIGNALS = {s: {"supplier_id": s, "stability": st, "checked_at": "", "source": "simulated", "source_url": mock_data.CRS_URL}
           for s, st in [("sup-golden", "verified_stable"), ("sup-bargain", "caution"), ("sup-newco", "not_verified")]}
NEED = {"id": "need-1", "buyer_id": "r-1", "delivery_window": "Mon 6-8am", "spend_limit": 500, "consent": True,
        "auction_window_s": 60, "source": "simulated",
        "items": [{"sku_spec": TH, "grade": "USDA Grade A", "pack_size": "40lb case", "quantity": 100, "unit": "lb"},
                  {"sku_spec": TOM, "grade": "US No. 1", "pack_size": "25lb case", "quantity": 50, "unit": "lb"}]}


def bid(bid_id, supplier, lines, total, floor=True, trace=""):
    return {"id": bid_id, "need_id": "need-1", "supplier_id": supplier, "persona": "p",
            "lines": [{"sku_spec": s, "unit_price": p, "quantity": q} for s, p, q in lines],
            "total_landed_price": total, "perks": [], "claims": [], "floor_check_passed": floor,
            "mirror_snapshot_id": "m", "decision_trace": trace, "expires_at": "", "source": "simulated"}


def run(bids, recalls=()):
    return checks.advise(NEED, bids, BASELINE, SIGNALS, list(recalls))


def test_cheapest_grade_swap_vetoed_next_best_wins():
    cheap = bid("b1", "sup-golden", [("chicken thigh, USDA Grade B, 40lb case", 1.50, 100), (TOM, 1.0, 50)], 200)
    good = bid("b2", "sup-golden", [(TH, 2.0, 100), (TOM, 1.1, 50)], 255)
    pricey = bid("b3", "sup-golden", [(TH, 2.1, 100), (TOM, 1.2, 50)], 270)
    bids = [cheap, good, pricey]
    cards = run(bids)
    assert cards[0]["recommendation"] == "veto"
    assert cards[1]["recommendation"] == "buy"
    assert checks.best_bid(bids, cards)["id"] == "b2"


def test_swap_in_decision_trace_vetoed():
    b = bid("b1", "sup-golden", [(TH, 2.0, 100)], 200, trace="Substituted 30lb case for availability")
    assert run([b])[0]["recommendation"] == "veto"


def test_overpay_dollar_impact():
    b = bid("b1", "sup-golden", [(TH, 2.50, 100), (TOM, 1.2, 50)], 310)  # baseline 2.10, +19%
    card = run([b])[0]
    assert card["recommendation"] == "caution"
    [w] = card["warnings"]
    assert w["kind"] == "price" and w["dollar_impact"] == 40.0
    assert w["source_url"] == mock_data.USDA_URL


def test_within_tolerance_no_warning():
    b = bid("b1", "sup-golden", [(TH, 2.30, 100)], 230)  # +9.5%
    assert run([b])[0]["warnings"] == []


def test_max_three_warnings_sorted():
    b = bid("b1", "sup-bargain", [("chicken thigh, USDA Grade B, 40lb case", 3.0, 100), (TOM, 2.0, 50)],
            400, floor=False)
    card = run([b], recalls=["roma tomato"])[0]
    impacts = [w["dollar_impact"] for w in card["warnings"]]
    assert len(impacts) == 3 and impacts == sorted(impacts, reverse=True)
    assert card["recommendation"] == "veto"


def test_crs_caution_and_not_verified_warn():
    for sup in ("sup-bargain", "sup-newco"):
        card = run([bid("b1", sup, [(TH, 2.0, 100)], 200)])[0]
        assert [w["kind"] for w in card["warnings"]] == ["stability"]
        assert card["recommendation"] == "caution"
        assert card["warnings"][0]["source_url"]


def test_recall_vetoes():
    card = run([bid("b1", "sup-golden", [(TOM, 1.0, 50)], 50)], recalls=["roma tomato"])[0]
    assert card["recommendation"] == "veto"


def test_no_winner_when_all_vetoed():
    bids = [bid("b1", "sup-golden", [("thigh, grade B", 1.0, 100)], 100)]
    assert checks.best_bid(bids, run(bids)) is None


def test_cards_validate_and_have_sources():
    bids = [bid("b1", "sup-bargain", [("chicken thigh, USDA Grade B, 40lb case", 3.0, 100), (TOM, 2.0, 50)],
                400, floor=False),
            bid("b2", "sup-golden", [(TH, 2.0, 100), (TOM, 1.1, 50)], 255)]
    for card in run(bids, recalls=["roma tomato"]):
        common.validate("AdvocateCard", card)
        assert all(w["source_url"] for w in card["warnings"])
