"""#216: the buyer name, round 1's loss reports and the Fetch tile lines go through the market's own reducers, and the
spoken condition is the line the market picked. A fake client records calls; no network."""
import pytest

from demo import bridge, stage
from demo.common import Narrator
from demo.run_demo import run_all

ADDR = {"buyer": "agent1q" + "b" * 58, "advocate": "agent1q" + "a" * 58, "shield": "agent1q" + "s" * 58}


@pytest.fixture(scope="module")
def run():
    return run_all(say=Narrator(False))


class Fake:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def call(self, reducer, **args):
        self.log.append((self.name, reducer, args))


def executed(run, **kw):
    steps = bridge.plan(run, delay=0, rounds=1, **kw)
    log = []
    names = {s.actor for s in steps} | {"buyer", "referee"}
    approved = {"step": "approval_call", "approved": True, "reason": None, "call_id": "c", "voice_approval_id": "apr_test"}   # #251: no scripted approval
    bridge.execute(steps, {n: Fake(log, n) for n in names}, delay=0, say=lambda s: None, sleep=lambda x: None, clock=lambda: 0.0,
                   approver=lambda step: approved)
    return log


def test_the_buyer_name_goes_through_set_buyer_profile_as_the_referee(run):
    calls = [(who, a) for who, r, a in executed(run) if r == "set_buyer_profile"]
    assert calls == [("referee", {"buyer_id": "vidyut", "display_name": "Vidyut"})]


def test_every_round_one_loss_report_is_recorded_as_sim_with_its_band_reason_and_source(run):
    reports = run["beats"]["5"]["round1_loss_reports"]
    calls = [a for who, r, a in executed(run) if r == "record_loss_report" and who == "referee"]
    assert [c["id"] for c in calls] == [r["id"] for r in reports] and len(calls) >= 1
    for c, r in zip(calls, reports):
        assert (c["gap_band"], c["reason"], c["source_url"], c["round_id"]) == (r["gap_band"], r["reason"], r["source_url"], "round-1")
        assert c["origin"] == "SIM" and c["won"] is False
        assert c["gap_band"] in {"within5", "within10", "within20", "over20"}
        assert c["reason"] in {"price", "fit", "condition", "delivery", "record", "advocate_veto"}


def test_only_the_learner_carries_the_strategy_step_and_what_to_change(run):
    b5 = run["beats"]["5"]
    calls = {a["seller_id"]: a for _, r, a in executed(run) if r == "record_loss_report"}
    learner = calls[b5["learning_seller"]]
    assert learner["strategy_diff"] == [{"key": "price_step", "from": "0.0", "to": "0.03"}]
    assert learner["what_to_change"] == b5["what_to_change"] and learner["what_to_change_origin"] == "SIM"
    assert all(a["strategy_diff"] == [] and a["what_to_change"] == "" for s, a in calls.items() if s != b5["learning_seller"])


def test_no_loss_report_carries_a_price_threshold_or_floor(run):
    for _, r, a in executed(run):
        if r == "record_loss_report":
            assert "$" not in a["what_to_change"] and "floor" not in a["reason"]


def test_the_fetch_tile_gets_one_sim_line_per_agent_with_its_address_and_no_cap(run):
    cap = str(int(run["beats"]["1"]["goal"]["cap"]))
    calls = [(who, a) for who, r, a in executed(run, agent_addresses=ADDR) if r == "record_agent_event"]
    assert [a["agent_name"] for _, a in calls] == ["Tech Bazaar Buyer", "Bazaar Advocate", "Bazaar Shield"]
    for who, a in calls:
        assert who == "referee" and a["origin"] == "SIM" and a["address"] == ADDR[{v: k for k, v in bridge.AGENT_NAMES.items()}[a["agent_name"]]]
        assert cap not in a["text"] and "1,300" not in a["text"] and len(a["text"]) <= 280


def test_without_agent_addresses_there_are_no_fetch_rows_and_the_stage_says_so(run, capsys):
    assert not [r for _, r, _ in executed(run) if r == "record_agent_event"]
    code = stage.main(["--dry-run"], agent_addresses=lambda: {})
    assert code == 0 and "Fetch tile: no agent rows" in capsys.readouterr().out


def test_the_agent_lines_land_in_their_beats(run):
    beats = stage.assign_beats(bridge.plan(run, delay=0, rounds=1, agent_addresses=ADDR))
    where = {s.args["agent_name"]: n for n, steps in beats.items() for s in steps if s.reducer == "record_agent_event"}
    assert where == {"Tech Bazaar Buyer": 1, "Bazaar Advocate": 2, "Bazaar Shield": 3}


# ---------------------------------------------------------------- item 4: the spoken condition is the market's picked line

def _gate_with(run, picked_lines):
    gate = bridge.DealGate(run)
    b2 = run["beats"]["2"]
    grove = next(b for b in b2["bids"] if b["seller_id"] == "gadget-grove")
    gate.winner = {"bid_id": grove["id"], "seller_id": "gadget-grove", "persona": grove["persona"], "landed": 1.0, "lines": picked_lines}
    return gate, grove


@pytest.mark.parametrize("shape", ["array", "object"])
def test_facts_take_the_condition_from_the_line_the_market_picked(run, shape):
    gate, grove = _gate_with(run, [])
    by_cond = {l["offered_condition"]: l for l in grove["lines"]}
    assert len(by_cond) >= 2
    for cond, line in by_cond.items():
        cell = (["rtx 5070 ti", "", cond, line["unit_price"], 1.0] if shape == "array"
                else {"skuSpec": "rtx 5070 ti", "offeredSpec": "", "offeredCondition": cond, "unitPrice": line["unit_price"], "quantity": 1.0})
        gate.winner["lines"] = [cell]
        assert gate.facts()["condition"] == cond


@pytest.mark.parametrize("lines", [[], [["x"]], [{"offeredCondition": "refurbished", "unitPrice": 1.0}], ["junk"]])
def test_an_unreadable_or_unmatched_picked_line_falls_back_to_the_demos_line(run, lines):
    gate, grove = _gate_with(run, lines)
    expected = grove["lines"][min(gate.lines.get("gadget-grove", 0), len(grove["lines"]) - 1)]["offered_condition"]
    assert gate.facts()["condition"] == expected


def test_market_winner_reads_the_picked_lines_column():
    row = (1, "round-1", "bid-1", "best-buy", "Best Buy", 1, 1299.99, [], [["rtx 5070 ti", "", "new", 1299.99, 1.0]], "MIRROR", "demo")
    assert bridge.market_winner([row])["lines"] == [["rtx 5070 ti", "", "new", 1299.99, 1.0]]
    assert bridge.market_winner([row[:8]])["lines"] == []


def test_the_agent_addresses_load_when_the_stage_runs_as_a_script():
    """`python demo/stage.py` puts demo/ first on sys.path, where demo/common.py is a top-level "common" (#316 review)."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    out = subprocess.run([sys.executable, str(root / "demo" / "stage.py"), "--dry-run"], capture_output=True, text=True, timeout=180,
                         cwd=root)
    assert out.returncode == 0 and out.stdout.count("record_agent_event") == 3, out.stdout[-500:]
    assert "Fetch tile: no agent rows" not in out.stdout
