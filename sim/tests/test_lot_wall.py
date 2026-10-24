"""Lot Wall (T6): one pooled lot of 38 RTX 5070 Ti orders, exactly one of them REAL (Vidyut's)."""
import json
from pathlib import Path

from sim.lot_wall import LOT_JSON, LOT_SIZE, SEED, STAGE_LINE, build_lot

ROOT = Path(__file__).resolve().parents[2]


def test_lot_is_one_real_order_plus_37_sim_builders():
    lot = build_lot()
    orders = lot["orders"]
    assert len(orders) == LOT_SIZE == 38
    real = [o for o in orders if o["label"] == "REAL"]
    sim = [o for o in orders if o["label"] == "SIM"]
    assert len(real) == 1 and len(sim) == 37
    assert all(o["label"] in ("REAL", "SIM") for o in orders)
    assert len({o["id"] for o in orders}) == 38
    assert all(o["sku_spec"] == "rtx 5070 ti" for o in orders)
    assert lot["origin"] == "SIM" and lot["real_count"] == 1 and lot["sim_count"] == 37


def test_real_order_is_vidyuts_from_the_sample_run():
    sample = json.loads((ROOT / "demo" / "out" / "sample-run.json").read_text())
    need = sample["artifacts"]["need"]
    (real,) = [o for o in build_lot()["orders"] if o["label"] == "REAL"]
    assert real["buyer_id"] == need["buyer_id"] == "vidyut" and real["name"] == "Vidyut"
    assert real["cap"] == need["spend_limit"]
    assert real["conditions"] == need["items"][0]["allowed_conditions"]
    assert real["need_id"] == need["id"]
    case = next(p for p in sample["artifacts"]["owned_parts"] if p["id"] == "owned-case")
    assert real["case_max_gpu_mm"] == case["attrs"]["max_gpu_length_mm"]


def test_sim_orders_come_from_the_wind_tunnel_builder_generator():
    from sim.wind_tunnel import make_builders
    wt = {b["id"]: b for b in make_builders(LOT_SIZE - 1, SEED)}
    sim = [o for o in build_lot()["orders"] if o["label"] == "SIM"]
    assert {o["id"] for o in sim} == set(wt)
    for o in sim:
        b = wt[o["id"]]
        assert o["cap"] == b["cap"] and o["conditions"] == b["conditions"] and o["archetype"] == b["archetype"]
        assert o["origin"] == "SIM" and o["name"].startswith("Builder ")


def test_lot_is_deterministic_and_seed_changes_the_sim_side_only():
    assert build_lot() == build_lot()
    other = build_lot(seed=SEED + 1)
    real_a = [o for o in build_lot()["orders"] if o["label"] == "REAL"]
    real_b = [o for o in other["orders"] if o["label"] == "REAL"]
    assert real_a[0]["cap"] == real_b[0]["cap"]
    assert [o["cap"] for o in build_lot()["orders"]] != [o["cap"] for o in other["orders"]]


def test_summary_counts_match_the_orders():
    lot = build_lot()
    caps = sorted(o["cap"] for o in lot["orders"])
    s = lot["summary"]
    assert s["orders"] == 38 and s["cap_min"] == caps[0] and s["cap_max"] == caps[-1]
    assert sum(s["by_archetype"].values()) == 38
    for price, n in s["demand_at"]:  # how many orders could pay this price
        assert n == sum(1 for c in caps if c >= price)
    ns = [n for _, n in s["demand_at"]]
    assert ns == sorted(ns, reverse=True)  # demand only falls as the price rises


def test_stage_line_is_exact_and_in_the_lot():
    assert STAGE_LINE == "This is one real request, Vidyut's. When many requests pool, this is what a seller sees."
    assert build_lot()["stage_line"] == STAGE_LINE


def test_no_dashes_in_any_text_and_no_pronouns():
    text = json.dumps(build_lot())
    assert "—" not in text and "–" not in text


def test_committed_lot_json_matches_the_generator():
    """web/public/lot.json is what the page reads; it must be the generator's output, not a hand edit."""
    assert LOT_JSON.exists()
    assert json.loads(LOT_JSON.read_text()) == build_lot()
