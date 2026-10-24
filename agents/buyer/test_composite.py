import os
import sys
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import composite
from composite import plan_build


def card(category, **attrs):
    defaults = {
        "gpu": {"chipset": "RTX 5070 Ti", "length_mm": 300, "board_power_w": 300,
                "rec_psu_w": 750, "power_connector": ["8pin", 2]},
        "psu": {"wattage": 850, "form_factor": "ATX", "pcie_8pin": 2},
        "case": {"type": "ATX Mid Tower", "motherboard_form_factors": ["ATX"],
                 "psu_form_factors": ["ATX"], "max_gpu_length_mm": 330},
    }
    return {"id": f"{category}-card", "category": category, "name": category,
            "attrs": {**defaults[category], **attrs}, "origin": "SIM", "source": "fixture:build"}


def build_goal(cap=1000, items=None):
    return {"id": "goal-build", "buyer_id": "buyer-1", "type": "build_by_date", "cap": cap, "items": items or [
        {"part": part, "sku_spec": f"{part}-sku", "condition": "new", "quantity": 1}
        for part in ("gpu", "psu", "case")
    ]}


def selected_for(goal, amounts=None, specs=None, *, unit_prices=None, shipping=None, taxes=None, bid_total=999999):
    amounts = amounts or {"gpu": 30000, "psu": 12000, "case": 9000}
    specs = specs or {part: card(part) for part in ("gpu", "psu", "case")}
    unit_prices = unit_prices or {"gpu": 300, "psu": 120, "case": 90}
    shipping = shipping or {part: 0 for part in ("gpu", "psu", "case")}
    taxes = taxes or {part: 0 for part in ("gpu", "psu", "case")}
    selected = {}
    for item in goal["items"]:
        part = item["part"]
        line = {"sku_spec": item["sku_spec"], "condition": item["condition"],
                "qty_available": 1, "unit_price": unit_prices[part]}
        bid = {"id": f"bid-{part}", "source": "https://example.test/listing", "origin": "MIRROR",
               "mirror_snapshot_id": "snap-1", "total_landed_price": bid_total, "lines": [line]}
        selected[part] = {
            "bid": bid, "line_index": 0, "line": line, "spec_card": specs[part],
            "quote": {"bid_id": bid["id"], "line_index": 0, "sku_spec": line["sku_spec"],
                      "condition": line["condition"], "quantity": 1, "shipping_cents": shipping[part],
                      "tax_cents": taxes[part], "landed_total_cents": amounts[part],
                      "spec_card_id": specs[part]["id"], "currency": "USD"},
        }
    return selected


def test_three_selected_parts_are_plan_ready_when_real_fit_and_landed_cap_pass():
    goal = build_goal(cap=600)
    out = plan_build(goal, selected_for(goal), [], {}, 600)
    assert out["status"] == "plan_ready"
    assert out["planned_total_cents"] == 51000
    assert out["fit"]["verdict"] == "pass"
    assert [p["part"] for p in out["parts"]] == ["gpu", "psu", "case"]


def test_shipping_inclusive_landed_cost_blocks_cheap_unit_price_over_cap():
    goal = build_goal(cap=620)
    selected = selected_for(goal, amounts={"gpu": 48000, "psu": 12000, "case": 9000},
                            unit_prices={"gpu": 400, "psu": 120, "case": 90},
                            shipping={"gpu": 8000, "psu": 0, "case": 0})
    out = plan_build(goal, selected, [], {}, 620)
    assert out["status"] == "blocked"
    assert out["planned_total_cents"] == 60000
    assert "cap" in str(out["blocked_reasons"]).lower()


def test_unknown_shipping_or_tax_blocks_instead_of_assuming_zero():
    goal = build_goal()
    selected = selected_for(goal)
    selected["gpu"]["quote"]["shipping_cents"] = None
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"
    selected = selected_for(goal)
    selected["psu"]["quote"]["tax_cents"] = None
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"


def test_bundled_bid_total_is_not_used_as_part_price():
    goal = build_goal(cap=600)
    selected = selected_for(goal, bid_total=1)
    gpu = selected["gpu"]
    gpu["bid"]["lines"].insert(0, {"sku_spec": "alternate-gpu", "condition": "new",
                                    "qty_available": 1, "unit_price": 1})
    gpu["line_index"] = 1
    gpu["quote"]["line_index"] = 1
    out = plan_build(goal, selected, [], {}, 600)
    assert out["status"] == "plan_ready"
    assert out["planned_total_cents"] == 51000


def test_landed_quote_must_match_selected_bid_line_and_components():
    goal = build_goal()
    selected = selected_for(goal)
    selected["gpu"]["quote"]["line_index"] = 1
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"
    selected = selected_for(goal)
    selected["gpu"]["quote"]["landed_total_cents"] += 1
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"
    selected = selected_for(goal)
    selected["gpu"]["quote"]["spec_card_id"] = "unrelated-card"
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"


def test_missing_landed_total_blocks():
    goal = build_goal()
    selected = selected_for(goal)
    del selected["gpu"]["quote"]["landed_total_cents"]
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"


def test_non_usd_or_missing_quote_currency_blocks_without_fx():
    goal = build_goal()
    selected = selected_for(goal)
    selected["gpu"]["quote"]["currency"] = "CAD"
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"
    selected = selected_for(goal)
    selected["gpu"]["bid"]["currency"] = "EUR"
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"
    selected = selected_for(goal)
    del selected["case"]["quote"]["currency"]
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"


def test_real_fit_blocks_too_long_gpu_even_after_all_parts_are_present():
    goal = build_goal()
    specs = {part: card(part) for part in ("gpu", "psu", "case")}
    specs["gpu"] = card("gpu", length_mm=400)
    out = plan_build(goal, selected_for(goal, specs=specs), [], {}, 1000)
    assert out["status"] == "blocked"
    assert out["fit"]["verdict"] == "fail"
    assert out["fit"]["rule_id"] == "fit.gpu_length"


def test_real_fit_uncertainty_never_marks_complete_plan_ready():
    goal = build_goal()
    specs = {part: card(part) for part in ("gpu", "psu", "case")}
    specs["psu"] = card("psu", wattage=None)
    out = plan_build(goal, selected_for(goal, specs=specs), [], {}, 1000)
    assert out["status"] == "blocked"
    assert out["fit"]["verdict"] == "uncertain"


def test_owned_psu_is_skipped_only_for_matching_owned_record_and_card():
    goal = build_goal()
    owned = {"id": "owned-psu", "buyer_id": "buyer-1", "sku_spec": "psu 850w", "attrs": {"wattage": 850}}
    goal["items"][1]["skipped_owned_part_id"] = "owned-psu"
    cards = {"owned-psu": card("psu")}
    selected = selected_for(goal)
    selected.pop("psu")
    out = plan_build(goal, selected, [owned], cards, 1000)
    assert out["status"] == "plan_ready"
    assert out["planned_total_cents"] == 39000
    assert next(p for p in out["parts"] if p["part"] == "psu")["owned_part_id"] == "owned-psu"
    assert plan_build(goal, selected, [], cards, 1000)["status"] == "blocked"
    wrong_kind = [{**owned, "sku_spec": "gpu sku"}]
    assert plan_build(goal, selected, wrong_kind, cards, 1000)["status"] == "blocked"
    wrong_attrs = {"owned-psu": card("psu", wattage=650)}
    assert plan_build(goal, selected, [owned], wrong_attrs, 1000)["status"] == "blocked"
    other_buyer = [{**owned, "buyer_id": "buyer-2"}]
    assert plan_build(goal, selected, other_buyer, cards, 1000)["status"] == "blocked"
    goal["items"][1]["skipped_owned_part_id"] = ""
    assert plan_build(goal, selected, [owned], cards, 1000)["status"] == "blocked"


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, 1.001])
def test_invalid_cap_money_is_blocked(bad):
    goal = build_goal(cap=bad)
    assert plan_build(goal, selected_for(goal), [], {}, 1000)["status"] == "blocked"


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, 1.001])
def test_invalid_landed_component_money_is_blocked(bad):
    goal = build_goal()
    selected = selected_for(goal)
    selected["gpu"]["quote"]["shipping_cents"] = bad
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"


def test_selected_line_must_match_exact_goal_sku_and_quantity():
    goal = build_goal()
    selected = selected_for(goal)
    selected["gpu"]["line"]["sku_spec"] = "different-sku"
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"
    selected = selected_for(goal)
    selected["case"]["line"]["qty_available"] = 0
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"


def test_incomplete_duplicate_and_extra_goals_are_blocked():
    goal = build_goal(items=build_goal()["items"][:2])
    assert plan_build(goal, selected_for(goal), [], {}, 1000)["status"] == "blocked"
    goal = build_goal()
    goal["items"].append(deepcopy(goal["items"][0]))
    assert plan_build(goal, selected_for(goal), [], {}, 1000)["status"] == "blocked"


def test_goal_needs_identity_and_malformed_inputs_fail_closed(monkeypatch):
    goal = build_goal()
    del goal["buyer_id"]
    assert plan_build(goal, selected_for(goal), [], {}, 1000)["status"] == "blocked"
    goal = build_goal()
    del goal["id"]
    assert plan_build(goal, selected_for(goal), [], {}, 1000)["status"] == "blocked"
    goal = build_goal()
    assert plan_build(goal, selected_for(goal), "not-owned-parts", {}, 1000)["status"] == "blocked"
    selected = selected_for(goal)
    selected["gpu"]["bid"]["origin"] = ["SIM"]
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"
    selected = selected_for(goal)
    selected["gpu"]["spec_card"]["origin"] = ["SIM"]
    assert plan_build(goal, selected, [], {}, 1000)["status"] == "blocked"
    monkeypatch.setattr(composite, "check_fit", lambda cards: None)
    assert plan_build(goal, selected_for(goal), [], {}, 1000)["status"] == "blocked"
    monkeypatch.setattr(composite, "check_fit", lambda cards: {"verdict": []})
    assert plan_build(goal, selected_for(goal), [], {}, 1000)["status"] == "blocked"


def test_nonfinite_spec_attrs_block_even_if_fit_checker_would_pass():
    goal = build_goal()
    specs = {part: card(part) for part in ("gpu", "psu", "case")}
    specs["gpu"]["attrs"]["length_mm"] = float("nan")
    assert plan_build(goal, selected_for(goal, specs=specs), [], {}, 1000)["status"] == "blocked"
