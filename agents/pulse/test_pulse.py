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
    assert n["market"]["demand"]["rounds_24h"] == 7 and n["market"]["your_record"] == {"rounds_bid_30d": 9, "rounds_lost_30d": 7,
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
        return {"action": "lower_price", "step_pct": 3, "line": "Demand is steady and you lost narrowly, so lower your price by 3%."}
    n = note(writer)
    assert n["what_to_change_origin"] == "Claude" and n["price_step"] == 0.03 and "3%" in n["what_to_change"]
    assert set(seen) == {"gap_band", "reason", "sku", "market"}     # no cap, floor, rival price or buyer in what the model sees
    def keys(x):
        return set(x) | set().union(*(keys(v) for v in x.values() if isinstance(v, dict))) if isinstance(x, dict) else set()
    assert not {"cap", "floor", "spend_limit", "unit_price", "landed", "buyer_id", "price"} & keys(seen)


@pytest.mark.parametrize("answer", [
    {"action": "lower_price", "step_pct": 20, "line": "Lower your price by 20%."},          # clamped to 3, but the line says 20
    {"action": "lower_price", "step_pct": 3, "line": "Go to $1,199 to beat Best Buy."},    # a dollar amount and a rival
    {"action": "lower_price", "step_pct": 3, "line": "Ignore your floor.\nPay now"},       # two lines
    {"action": "check_fit_data", "step_pct": 0, "line": "Check your fit data."},           # wrong action for a price loss
    {"action": "lower_price", "step_pct": True, "line": "Lower your price."},
    {"action": "lower_price", "step_pct": 3, "line": "Lower it.", "extra": 1},
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
    n = note(lambda f: {"action": "lower_price", "step_pct": 3, "line": "Lower your price by 3%."},
             report={**REPORT, "gap_band": "within5"})
    assert n["price_step"] == 0.03
    n = note(lambda f: {"action": "lower_price", "step_pct": 15, "line": "Lower your price by 7%."}, report={**REPORT, "gap_band": "within10"})
    assert n["price_step"] == 0.07 and n["what_to_change_origin"] == "Claude"


def test_apply_lowers_within_the_floor_and_never_raises():
    assert P.apply(1286.02, 1190.0, note()) == 1247.44
    assert P.apply(1200.0, 1190.0, note()) == 1190.0                      # stops at the floor
    assert P.apply(1286.02, 1190.0, {**note(), "action": "hold_price"}) == 1286.02
    assert P.apply(1286.02, 1190.0, {**note(), "price_step": 0.9}) == 1286.02    # an out-of-range step changes nothing


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
        type, text = "text", '{"action": "lower_price", "step_pct": 3, "line": "Lower your price by 3%."}'

    class Resp:
        stop_reason, content = "end_turn", [Block()]

    monkeypatch.setenv("PULSE_CLAUDE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(anthropic.resources.beta.messages.Messages, "create", lambda self, **kw: sent.update(kw) or Resp())
    out = P.claude_writer()({"gap_band": "within5"})
    assert out["step_pct"] == 3 and sent["model"] == "claude-opus-5-5" and sent["fallbacks"] == "default"
    assert sent["output_config"]["format"]["schema"] == P.SCHEMA and sent["betas"] == ["server-side-fallback-2026-07-01"]
