import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from common import validate
from goal import OWNED, apply_owned, clarification_question, need_from_goal, owned_attrs, parse_goal, remember, skip_lines
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


# ---- #449 RT-6: a goal can arrive over several chat messages ----

from datetime import timedelta  # noqa: E402

from goal import DRAFT_MAX, DRAFT_TTL_S, forget_draft, parse_goal_draft  # noqa: E402

FIRST = "find me an RTX 5070 Ti under $1300"


def _draft_flow(drafts, sender, texts, start=NOW, step=timedelta(seconds=30)):
    """Send texts one by one; return the (goal, owned) the last one parsed, or the ValueError text of each failed one."""
    out = []
    for i, text in enumerate(texts):
        try:
            out.append(parse_goal_draft(text, sender, now=start + i * step, drafts=drafts))
        except ValueError as e:
            out.append(str(e))
    return out


def test_rt6_budget_then_condition_then_deadline_in_three_messages_ends_in_a_parsed_goal():
    drafts = {}
    first, second, (goal, owned) = _draft_flow(drafts, "s1", [FIRST, "new", "by Friday"])
    assert "condition" in first
    assert "deadline" in second and "budget" not in second          # "new" alone used to ask for the budget again
    assert goal["cap"] == 1300 and goal["items"][0]["sku_spec"] == "rtx 5070 ti" and goal["items"][0]["condition"] == "new"
    assert goal["deadline"] == "2026-10-30T23:59:00Z" and owned == []
    assert "s1" not in drafts                                        # cleared on success


def test_rt6_a_reply_that_completes_the_goal_in_one_go_also_merges():
    drafts = {}
    first, (goal, _) = _draft_flow(drafts, "s1", [FIRST, "new, by Friday"])
    assert "condition" in first and goal["cap"] == 1300 and "s1" not in drafts


def test_rt6_a_message_that_is_a_whole_goal_ignores_and_clears_the_old_draft():
    drafts = {}
    _draft_flow(drafts, "s1", [FIRST])
    goal, _ = parse_goal_draft("a new 750 W PSU under $150 by Friday", "s1", now=NOW, drafts=drafts)
    assert goal["cap"] == 150 and [i["part"] for i in goal["items"]] == ["psu"] and "s1" not in drafts


def test_rt6_another_senders_partial_is_never_merged():
    drafts = {}
    _draft_flow(drafts, "s1", [FIRST])
    other = _draft_flow(drafts, "s2", ["new by Friday"])
    assert "budget" in other[0]                                      # s2 never sees s1's $1300 or GPU
    assert set(drafts) == {"s1"}                                     # and "new by Friday" is not kept as anyone's draft
    goal, _ = parse_goal_draft("new, by Friday", "s1", now=NOW, drafts=drafts)
    assert goal["buyer_id"] == "s1" and goal["cap"] == 1300


def test_rt6_the_latest_reply_wins_on_a_conflict():
    drafts = {}
    _, (goal, _) = _draft_flow(drafts, "s1", [FIRST, "new, under $900, by Friday"])
    assert goal["cap"] == 900
    drafts = {}
    _, (goal, _) = _draft_flow(drafts, "s1", ["an open-box RTX 5070 Ti under $1300", "new by Friday"])
    assert goal["items"][0]["condition"] == "new" and "allowed_conditions" not in goal["items"][0]
    drafts = {}
    _, (goal, _) = _draft_flow(drafts, "s1", ["an RTX 5070 Ti under $1300 by Monday", "new, Wednesday"])      # Monday sorts first, so only "latest wins" gives Wednesday
    assert goal["deadline"] == "2026-10-28T23:59:00Z"


def test_rt6_a_draft_expires_after_ten_minutes_but_not_before():
    drafts = {}
    _draft_flow(drafts, "s1", [FIRST])
    late = _draft_flow(drafts, "s1", ["new by Friday"], start=NOW + timedelta(seconds=DRAFT_TTL_S + 1))
    assert "budget" in late[0] and "s1" not in drafts
    drafts = {}
    _draft_flow(drafts, "s1", [FIRST])
    (goal, _), = _draft_flow(drafts, "s1", ["new by Friday"], start=NOW + timedelta(seconds=DRAFT_TTL_S - 1))
    assert goal["cap"] == 1300
    assert DRAFT_TTL_S == 600


def test_rt6_each_answer_restarts_the_ten_minutes():
    drafts = {}
    texts = [FIRST, "new", "by Friday"]
    res = _draft_flow(drafts, "s1", texts, step=timedelta(minutes=8))          # 16 minutes in all, never 10 between messages
    assert isinstance(res[-1], tuple) and res[-1][0]["cap"] == 1300


def test_rt6_cancel_clears_the_draft_and_small_talk_is_not_kept():
    drafts = {}
    _draft_flow(drafts, "s1", [FIRST, "hello", "thanks!"])
    assert "s1" in drafts and forget_draft("s1", drafts=drafts) is True and forget_draft("s1", drafts=drafts) is False
    assert _draft_flow(drafts, "s1", ["new by Friday"])[0].startswith("What is your maximum budget")
    _draft_flow(drafts, "s3", ["hello"])
    assert "s3" not in drafts


def test_rt6_errors_that_are_not_questions_drop_the_draft():
    drafts = {}
    _draft_flow(drafts, "s1", ["find me an RTX 5090 under $1300"])            # a question first, so it is kept
    res = _draft_flow(drafts, "s1", ["new by Friday"])
    assert "Which GPU model" in res[0] and "s1" not in drafts                  # a dead end is reported once and dropped


def test_rt6_the_draft_store_is_bounded_and_text_is_capped():
    drafts = {}
    for i in range(DRAFT_MAX + 20):
        _draft_flow(drafts, f"s{i}", [FIRST], start=NOW + timedelta(seconds=i))
    assert len(drafts) == DRAFT_MAX and f"s{DRAFT_MAX + 19}" in drafts and "s0" not in drafts
    _draft_flow(drafts, "long", [FIRST + " " + "x" * 5000])
    assert "long" not in drafts


def test_rt6_a_complete_message_never_touches_the_store():
    drafts = {}
    parse_goal_draft("a new GPU under $800 by Friday", "s1", now=NOW, drafts=drafts)
    assert drafts == {}
