import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from common import validate
from goal import OWNED, apply_owned, clarification_question, demo_goal_fields, need_from_goal, owned_attrs, parse_goal, remember, skip_lines
from logic import sealed

DEMO = ("a new GPU for 1440p that fits my case and PSU, under $800, by Friday. "
        "I already own a 750 W PSU and a mid-tower with 330 mm GPU clearance")
NOW = datetime(2026, 10, 23, 21, 58, tzinfo=timezone.utc)  # a Friday


def demo():
    goal, owned = parse_goal(DEMO, "buyer-1", now=NOW)
    return apply_owned(goal, owned), owned


def test_demo_goal_buys_only_the_gpu():
    goal, owned = demo()
    assert goal["cap"] == 800 and goal["type"] == "part_by_date" and goal["state"] == "ACTIVE"
    assert goal["deadline"] == "2026-10-30T23:59:00Z"  # next Friday, not today
    need = need_from_goal(goal)
    assert [i["sku_spec"] for i in need["items"]] == ["rtx 4070 super 12gb"]
    assert need["spend_limit"] == 800


def test_owned_parts_are_skipped_and_cited():
    goal, owned = demo()
    by_kind = {o["sku_spec"].split()[0]: o for o in owned}
    assert by_kind["psu"]["attrs"] == {"wattage": 750}
    assert by_kind["case"]["attrs"] == {"max_gpu_length_mm": 330}
    skipped = {i["part"]: i["skipped_owned_part_id"] for i in goal["items"] if i.get("skipped_owned_part_id")}
    assert skipped == {"psu": by_kind["psu"]["id"], "case": by_kind["case"]["id"]}
    lines = skip_lines(goal, owned)
    assert lines[0].startswith("Skipped PSU: you already own it (your note: 'I already own a 750 W PSU")
    assert lines[0].endswith(f", {NOW.astimezone().strftime('%H:%M')})")  # shown in local time
    assert owned_attrs(owned) == {"psu": {"wattage": 750}, "case": {"max_gpu_length_mm": 330}}


def test_upgrade_does_not_skip():
    goal, owned = parse_goal("Upgrade my PSU, new, under $150 by Monday. I have a 550 W PSU.", "b", now=NOW)
    goal = apply_owned(goal, owned)
    assert owned[0]["attrs"] == {"wattage": 550}
    assert not any(i.get("skipped_owned_part_id") for i in goal["items"])
    assert [i["sku_spec"] for i in need_from_goal(goal)["items"]] == ["psu 750w"]


def test_build_expands_and_budget_cap_type():
    goal, _ = parse_goal("I want to build a PC, new, budget $1,500 by Friday", "b", now=NOW)
    assert [i["sku_spec"] for i in goal["items"]] == ["rtx 4070 super 12gb", "psu 750w", "case"] and goal["type"] == "build_by_date"
    goal, _ = parse_goal("a GPU, new, under $500 by Friday", "b", now=NOW)
    assert goal["type"] == "part_by_date" and goal["cap"] == 500


def test_need_items_validate_with_new_and_legacy_fields():
    need = validate("Need", need_from_goal(demo()[0]))
    item = need["items"][0]
    assert item == {"sku_spec": "rtx 4070 super 12gb", "condition": "new", "variant": "retail", "quantity": 1,
                    "unit": "each", "grade": "new", "pack_size": "retail"}


def test_seller_bound_need_has_no_spend_limit():
    need = need_from_goal(demo()[0])
    assert "spend_limit" not in sealed(need)
    assert "800" not in str(sealed(need))


def test_memory_remembers_across_goals():
    OWNED.clear()
    _, owned = parse_goal(DEMO, "b", now=NOW)
    remember("b", owned)
    goal, new = parse_goal("a new GPU and PSU under $900 by Friday", "b", now=NOW)
    goal = apply_owned(goal, remember("b", new))
    assert [i["sku_spec"] for i in need_from_goal(goal)["items"]] == ["rtx 4070 super 12gb"]


def test_missing_budget_or_part_raises():
    with pytest.raises(ValueError):
        parse_goal("a GPU by Friday", "b")
    with pytest.raises(ValueError):
        parse_goal("something nice under $50", "b")


def test_psu_850_sku():
    goal, _ = parse_goal("an 850 W PSU, new, under $200 by Friday", "b", now=NOW)
    assert [i["sku_spec"] for i in need_from_goal(goal)["items"]] == ["psu 850w"]


def test_explicit_5070_ti_stays_canonical_and_keeps_the_cap():
    goal, _ = parse_goal("RTX 5070 Ti GPU, new, under $800 by Friday", "b", now=NOW)
    need = need_from_goal(goal)
    assert goal["cap"] == 800
    assert [item["sku_spec"] for item in need["items"]] == ["rtx 5070 ti"]


def test_unsupported_gpu_model_is_not_substituted():
    with pytest.raises(ValueError, match="Which GPU model"):
        parse_goal("RTX 5080 GPU, new, under $1200 by Friday", "b", now=NOW)


def test_bare_supported_gpu_alias_is_canonical():
    goal, _ = parse_goal("5070 Ti GPU, new, under $800 by Friday", "b", now=NOW)
    assert goal["items"][0]["sku_spec"] == "rtx 5070 ti"


def test_multiple_explicit_gpu_models_are_rejected_as_ambiguous():
    with pytest.raises(ValueError, match="one GPU model"):
        parse_goal("RTX 5070 Ti or RTX 4070 Super GPU, new, under $900 by Friday", "b", now=NOW)


def test_bare_unsupported_model_does_not_fall_back_to_legacy_gpu():
    with pytest.raises(ValueError, match="Which GPU model"):
        parse_goal("5080 GPU, new, under $1200 by Friday", "b", now=NOW)


def test_allowed_new_and_open_box_and_distinct_parts_are_preserved():
    goal, _ = parse_goal("Build with an RTX 5070 Ti GPU and 850 W PSU, new or open-box, under $1500 by Friday", "b", now=NOW)
    need = need_from_goal(goal)
    assert [item["sku_spec"] for item in need["items"]] == ["rtx 5070 ti", "psu 850w", "case"]
    assert need["items"][0]["allowed_conditions"] == ["new", "open-box"]


def test_clarification_order_and_complete_goal_gate():
    assert clarification_question("GPU") == "What is your maximum budget?"
    assert clarification_question("GPU under $800") == "What condition do you want: new or open-box?"
    assert clarification_question("GPU, new, under $800") == "When is your deadline? Give a date, weekday, or tomorrow."
    assert clarification_question("GPU, new, under $800 by Friday") is None


@pytest.mark.parametrize("text", ["GPU, new, by Friday", "GPU, under $800, by Friday", "GPU, new, under $800"])
def test_parse_goal_refuses_each_missing_required_detail(text):
    with pytest.raises(ValueError, match="(budget|condition|deadline)"):
        parse_goal(text, "b", now=NOW)


def test_parse_goal_rejects_nonpositive_cap_and_past_deadline():
    with pytest.raises(ValueError, match="positive"):
        parse_goal("GPU, new, under $0 by Friday", "b", now=NOW)
    with pytest.raises(ValueError, match="past"):
        parse_goal("GPU, new, under $800 by 2026-10-22", "b", now=NOW)


FRIDAY_GOAL = "RTX 5070 Ti that fits my case, under $1,300, by Friday, new or open-box"
CASE_TOLD = "I have a mid-tower case that takes cards up to 305 mm."


def test_demo_5070_ti_goal_parses_all_fields_and_case_limit():
    goal, owned = parse_goal(f"{FRIDAY_GOAL}. {CASE_TOLD}", "buyer-1", now=NOW)
    goal = apply_owned(goal, owned)
    assert goal["cap"] == 1300 and goal["deadline"] == "2026-10-30T23:59:00Z"
    need = need_from_goal(goal)
    assert [i["sku_spec"] for i in need["items"]] == ["rtx 5070 ti"]
    assert need["items"][0]["allowed_conditions"] == ["new", "open-box"]
    assert owned_attrs(owned)["case"]["max_gpu_length_mm"] == 305


def test_fits_my_case_is_a_constraint_not_a_case_to_buy():
    goal, _ = parse_goal(FRIDAY_GOAL, "buyer-1", now=NOW)
    assert [i["part"] for i in goal["items"]] == ["gpu"]


def test_goal_without_a_cap_asks_the_budget_question():
    text = "RTX 5070 Ti that fits my case, by Friday, new or open-box"
    assert clarification_question(text) == "What is your maximum budget?"
    with pytest.raises(ValueError, match="What is your maximum budget"):
        parse_goal(text, "b", now=NOW)


def test_used_is_not_an_allowed_condition():
    # Rule: only new and open-box are recognised; a used-only goal has no condition and is asked about.
    text = "RTX 5070 Ti, used, under $900 by Friday"
    assert clarification_question(text) == "What condition do you want: new or open-box?"
    with pytest.raises(ValueError, match="new or open-box"):
        parse_goal(text, "b", now=NOW)
    goal, _ = parse_goal("RTX 5070 Ti, new or used, under $900 by Friday", "b", now=NOW)
    assert goal["items"][0]["condition"] == "new" and "allowed_conditions" not in goal["items"][0]


def test_two_digit_cap_is_read():
    goal, _ = parse_goal("a new GPU under $85 by Friday", "b", now=NOW)
    assert goal["cap"] == 85


def test_demo_goal_fields_match_lane_d_stand_in_shape():
    assert demo_goal_fields(FRIDAY_GOAL, NOW) == {
        "cap": 1300.0, "deadline": "2026-10-30T23:59:00Z",
        "allowed_conditions": ["new", "open-box"], "sku_spec": "rtx 5070 ti"}
    with pytest.raises(ValueError, match="maximum budget"):
        demo_goal_fields("RTX 5070 Ti, by Friday, new", NOW)
