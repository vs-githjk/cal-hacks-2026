"""#260 Market Pulse with a fake Tiger and a fake Claude. No network, no key."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_pulse as P  # noqa: E402

REPORT = {"id": "lr-1", "round_id": "round-1", "seller_id": "gadget-grove", "won": False, "gap_band": "within5", "reason": "price",
          "source_url": "https://example.com/sim/gadget-grove/rtx-5070-ti"}
DEMAND = {"status": "ok", "rows": [{"sku": "rtx 5070 ti", "rounds": 4}, {"sku": "rtx 5070 ti", "rounds": 3}, {"sku": "psu 750w", "rounds": 9}]}
COACH = {"status": "ok", "seller_id": "gadget-grove", "rounds_bid": 9, "rounds_lost": 7, "rows": []}


def note(writer=None, report=REPORT, demand=DEMAND, coach=COACH):
    return P.note_for(report, "rtx 5070 ti", demand, coach, writer=writer)


def test_without_claude_the_note_is_the_sim_template_with_tiger_facts():
    n = note()
    assert n["what_to_change_origin"] == "SIM template" and n["action"] == "lower_price" and n["price_step"] == 0.03
    assert n["market"]["demand"]["round_hours_24h"] == 7 and n["market"]["your_record"] == {"rounds_bid_30d": 9, "rounds_lost_30d": 7,
                                                                                        "source": "Tiger Data loss_reports"}


def test_tiger_not_configured_or_failing_says_so_and_invents_nothing():
    n = note(demand={"status": "not_configured", "rows": []}, coach={"status": "error", "rows": []})
    assert n["market"] == {"demand": {"state": "not_configured"}, "your_record": {"state": "error"}}
    notes = P.pulse([REPORT], "rtx 5070 ti", demand=lambda: (_ for _ in ()).throw(OSError()), coach=lambda s: (_ for _ in ()).throw(OSError()))
    assert notes[0]["market"] == {"demand": {"state": "error"}, "your_record": {"state": "error"}}


def test_a_good_claude_answer_is_used_and_labelled_claude():
    seen = {}

    def writer(facts):
        seen.update(facts)
        return {"action": "lower_price", "step_pct": 3, "why": "busy_market"}
    n = note(writer)
    assert n["what_to_change_origin"] == "Claude" and n["price_step"] == 0.03
    assert n["what_to_change"] == "Many sellers are bidding on this part. Lower your price by about 3%, and keep it above your floor."
    assert set(seen) == {"gap_band", "reason", "sku", "market"}     # no cap, floor, rival price or buyer in what the model sees
    def keys(x):
        return set(x) | set().union(*(keys(v) for v in x.values() if isinstance(v, dict))) if isinstance(x, dict) else set()
    assert not {"cap", "floor", "spend_limit", "unit_price", "landed", "buyer_id", "price"} & keys(seen)


@pytest.mark.parametrize("answer", [
    {"action": "lower_price", "step_pct": 3, "line": "Price below your floor by 3%."},      # free text is not in the schema
    {"action": "lower_price", "step_pct": 3, "why": "Match Best Buy."},                    # a why outside the closed list
    {"action": "check_fit_data", "step_pct": 0, "why": "lost_narrowly"},                  # wrong action for a price loss
    {"action": "lower_price", "step_pct": True, "why": "lost_narrowly"},
    {"action": "lower_price", "step_pct": 0, "why": "lost_narrowly"},                     # a price cut of nothing
    {"action": "lower_price", "step_pct": 30, "why": "lost_narrowly"},
    {"action": "lower_price", "step_pct": 3, "why": "lost_narrowly", "line": "Act now"},  # an extra field
    "not json", None,
])
def test_an_unusable_claude_answer_falls_back_to_the_sim_template(answer):
    n = note(lambda facts: answer)
    assert n["what_to_change_origin"].startswith("SIM template") and n["price_step"] == 0.03
    assert n["what_to_change"].startswith("You lost on price by less than 5 percent")


def test_a_failing_claude_call_falls_back_too():
    n = note(lambda facts: (_ for _ in ()).throw(TimeoutError()))
    assert n["what_to_change_origin"] == "SIM template (Claude answer unusable)"


def test_a_bigger_step_is_clamped_to_the_bands_cap():
    n = note(lambda f: {"action": "lower_price", "step_pct": 20, "why": "lost_narrowly"}, report={**REPORT, "gap_band": "within5"})
    assert n["price_step"] == 0.03 and "about 3%" in n["what_to_change"]
    n = note(lambda f: {"action": "lower_price", "step_pct": 15, "why": "lost_narrowly"}, report={**REPORT, "gap_band": "within10"})
    assert n["price_step"] == 0.07 and n["what_to_change_origin"] == "Claude" and "about 7%" in n["what_to_change"]


def test_apply_lowers_within_the_floor_and_never_raises():
    assert P.apply(1286.02, 1190.0, note()) == 1247.44
    assert P.apply(1200.0, 1190.0, note()) == 1190.0                      # stops at the floor
    assert P.apply(1286.02, 1190.0, {**note(), "action": "hold_price"}) == 1286.02
    assert P.apply(1286.02, 1190.0, {**note(), "price_step": 0.9}) == 1286.02    # an out-of-range step changes nothing
    assert P.apply(1000.0, 1190.0, note()) == 1000.0                      # already under its floor: never raised
    for bad in ({"price": float("nan")}, {"floor": float("nan")}, {"price": float("inf")}, {"floor": "x"}):
        args = {"price": 1286.02, "floor": 1190.0, **bad}
        assert P.apply(args["price"], args["floor"], note()) == args["price"] or args["price"] != args["price"]
    assert P.apply(1286.02, 1190.0, {**note(), "price_step": "0.03"}) == 1286.02


def test_winners_get_no_note_and_non_price_losses_move_no_price():
    notes = P.pulse([{**REPORT, "won": True}, {**REPORT, "seller_id": "bargain-bin", "reason": "fit"}], "rtx 5070 ti",
                    demand=lambda: DEMAND, coach=lambda s: COACH)
    assert [n["seller_id"] for n in notes] == ["bargain-bin"] and notes[0]["action"] == "check_fit_data"
    assert P.apply(1199.0, 1100.0, notes[0]) == 1199.0


def test_the_live_writer_is_off_without_the_flag_and_a_key(monkeypatch):
    monkeypatch.delenv("PULSE_CLAUDE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    assert P.claude_writer() is None
    monkeypatch.setenv("PULSE_CLAUDE", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert P.claude_writer() is None


def test_the_live_writer_asks_for_the_closed_schema_with_fallbacks(monkeypatch):
    import anthropic

    sent = {}

    class Block:
        type, text = "text", '{"action": "lower_price", "step_pct": 3, "why": "lost_narrowly"}'

    class Resp:
        stop_reason, content = "end_turn", [Block()]

    monkeypatch.setenv("PULSE_CLAUDE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(anthropic.resources.beta.messages.Messages, "create", lambda self, **kw: sent.update(kw) or Resp())
    out = P.claude_writer()({"gap_band": "within5"})
    assert out["step_pct"] == 3 and sent["model"] == "claude-opus-5-5" and sent["fallbacks"] == "default"
    assert sent["output_config"]["format"]["schema"] == P.SCHEMA and sent["betas"] == ["server-side-fallback-2026-07-01"]


def test_the_step_caps_match_the_demo_learning_rule():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from demo.learning import STEP_BY_BAND
    assert P.STEP_CAP == STEP_BY_BAND


def test_every_closed_choice_renders_a_plain_line_with_no_model_text():
    for action, line in P.ACTION_LINE.items():
        for why in P.WHY:
            text = P._line(action, 0.03, why)
            assert "\n" not in text and "$" not in text and text.startswith(P.WHY[why])


def test_an_unknown_band_or_reason_gets_no_note_instead_of_a_crash():
    notes = P.pulse([{**REPORT, "gap_band": "half"}, {**REPORT, "reason": "vibes"}, REPORT], "rtx 5070 ti",
                    demand=lambda: DEMAND, coach=lambda s: COACH)
    assert len(notes) == 1



# ---------- #323 review 2: the why must be true for the loss ----------

@pytest.mark.parametrize("answer, report", [
    ({"action": "hold_price", "step_pct": 0, "why": "lost_narrowly"}, REPORT),                       # no hold on a price loss
    ({"action": "lower_price", "step_pct": 3, "why": "listing_flagged"}, REPORT),                    # a price loss was not flagged
    ({"action": "lower_price", "step_pct": 3, "why": "lost_widely"}, REPORT),                        # within5 is narrow
    ({"action": "lower_price", "step_pct": 15, "why": "lost_narrowly"}, {**REPORT, "gap_band": "over20"}),
    ({"action": "lower_price", "step_pct": 3, "why": "quiet_market"}, REPORT),                       # 7 round-hours is busy
])
def test_a_why_that_is_not_true_for_the_loss_falls_back(answer, report):
    n = note(lambda f: answer, report=report)
    assert n["what_to_change_origin"].startswith("SIM template"), (answer, report)


def test_busy_or_quiet_only_when_tiger_answered():
    n = note(lambda f: {"action": "lower_price", "step_pct": 3, "why": "busy_market"}, demand={"status": "not_configured", "rows": []})
    assert n["what_to_change_origin"].startswith("SIM template")
    n = note(lambda f: {"action": "check_fit_data", "step_pct": 0, "why": "listing_flagged"}, report={**REPORT, "reason": "fit"})
    assert n["what_to_change_origin"] == "Claude" and n["what_to_change"].startswith("The advocate flagged your listing")
