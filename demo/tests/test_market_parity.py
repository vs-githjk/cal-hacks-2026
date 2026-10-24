"""Parity between the Python market stand-in (demo/standins/market.py) and Lane B's TypeScript scoring rules.

node is not installed, so market/rules/scoring.test.ts cannot run here. Instead this test READS that file, pulls out
the literal fixtures of five rankBids cases (prices, perks, tie-break inputs, rejections, an open-box trap) and
asserts the stand-in produces the same ranking the TypeScript test expects. If the file changes shape so that a
case can no longer be read, the test fails and names the case; it never silently passes.

Not covered (so not claimed): the quantity 0/-1/NaN cases (the stand-in's referee, check_floor, handles those, see
test_run_demo.py), the fast-check fee property (the stand-in never reads a fee), and checkLineSpec on its own
(it assumes one condition per need line; the stand-in implements the LOCKED alternatives model instead).
"""
import re
from pathlib import Path

import pytest

from demo.standins import market

TS = Path(__file__).resolve().parents[2] / "market" / "rules" / "scoring.test.ts"
GOOD_SELLER = {"shipping": 0.0, "returns_days": 30, "record": "good"}   # neutral: no quality adjustment
ITEM = {"sku_spec": "gpu-rtx5070ti-retail", "condition": "new", "allowed_conditions": ["new"], "variant": "retail", "quantity": 1}


def _case(name: str) -> str:
    text = TS.read_text(encoding="utf-8")
    m = re.search(r'it\("' + re.escape(name) + r'".*?\n  \}\);', text, re.S)
    assert m, f"scoring.test.ts case not found: {name}"
    return m.group(0)


def _bids(block: str) -> dict:
    """const <var> = mk("seller-x", PRICE, { ... }) in order of creation; sealed_at is the creation counter."""
    out = {}
    for n, m in enumerate(re.finditer(r'const (\w+) = mk\("([\w-]+)", (\d+)(?:, (\{.*?\}))?\);', block), 1):
        var, seller, price, extra = m.group(1), m.group(2), float(m.group(3)), m.group(4) or ""
        cond = re.search(r'offered_condition: "([\w-]+)"', extra)
        out[var] = {"bid": {"id": var, "seller_id": seller, "lines": [{
            "sku_spec": ITEM["sku_spec"], "unit_price": price, "quantity": 1, "offered_condition": cond.group(1) if cond else "new"}]},
            "perks": bool(re.search(r'perks: \["', extra)), "sealed_at": n}
    assert out, "no mk(...) bids parsed"
    return out


def _expected(block: str) -> list[str]:
    m = re.search(r"toEqual\(\[([\w, .]+)\]\)", block)
    assert m, "no expected order parsed"
    return [x.strip().removesuffix(".id") for x in m.group(1).split(",")]


def _rank(bids: dict, perks_value=0.0, verified=None, rejections=None) -> dict:
    meta = {b["bid"]["seller_id"]: GOOD_SELLER for b in bids.values()}
    return market.rank_bids([b["bid"] for b in bids.values()], ITEM, 1e9, meta, {k: b["sealed_at"] for k, b in bids.items()},
                            rejections=rejections, verified=verified,
                            perks_value={k: perks_value for k, b in bids.items() if b["perks"]})


def test_ranks_by_landed_price_minus_perks_value():
    block = _case("ranks by landed price minus perks value, lowest first")
    value = float(re.search(r"bid\.perks\.length \? (\d+) : 0", block).group(1))
    got = [r["bid_id"] for r in _rank(_bids(block), perks_value=value)["ranked"]]
    assert got == _expected(block) and got[0] == "c"


def test_open_box_trap_against_a_new_goal_is_disqualified():
    block = _case("disqualifies the cheapest bid when it is open-box against a new goal")
    res = _rank(_bids(block))
    assert [r["bid_id"] for r in res["ranked"]] == _expected(block)
    assert [d["bid_id"] for d in res["disqualified"]] == ["trap"] and "condition" in res["disqualified"][0]["reasons"][0]


def test_rejections_from_other_checks_are_applied():
    block = _case("applies rejections from other checks (floor, CPSC recall, claim check, Shield)")
    bids = _bids(block)
    reason = re.search(r'\["(recall: [^"]+)"\]', block).group(1)
    res = _rank(bids, rejections={"a": [reason]})
    assert [r["bid_id"] for r in res["ranked"]] == _expected(block)
    assert res["disqualified"][0]["reasons"] == [reason]


def test_ties_break_by_more_verified_claims_then_earlier_sealed_time():
    block = _case("breaks ties by more verified claims, then earlier sealed time")
    bids = _bids(block)
    winner = re.search(r"bid\.id === (\w+)\.id \? (\d+) : 0", block)
    got = [r["bid_id"] for r in _rank(bids, verified={winner.group(1): int(winner.group(2))})["ranked"]]
    # the TypeScript test creates early, late, verified in that order but passes [late, early, verified] to rankBids
    assert got == _expected(block) == ["verified", "early", "late"]


def test_landed_price_comes_from_the_lines_not_a_stated_total():
    block = _case("computes landed price from the lines, not the seller's stated total")
    bids = _bids(block)
    for v in bids.values():
        v["bid"]["total_landed_price"] = 1 if v["bid"]["seller_id"] == "seller-a" else v["bid"]["lines"][0]["unit_price"]
    res = _rank(bids)
    assert res["ranked"][0]["bid_id"] == "honest" and res["ranked"][1]["landed"] == 780.0
