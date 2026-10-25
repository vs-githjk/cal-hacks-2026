"""Lot Wall (T6, Lane D). SIM: one pooled lot of RTX 5070 Ti orders as a seller would see it.

    python3 -m sim.lot_wall            # writes web/public/lot.json (the /lot page reads it)

Exactly one order is REAL: the buyer's, read from demo/out/sample-run.json. The other 37 are SIM builders from the
wind tunnel's own generator (sim.wind_tunnel.make_builders), deterministic with a seed. Every order carries its label.
Nothing here is a market result: it shows demand a seller would see, not a sale.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from sim.wind_tunnel import make_builders

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RUN = ROOT / "demo" / "out" / "sample-run.json"
LOT_JSON = ROOT / "web" / "public" / "lot.json"
LOT_SIZE = 38
SEED = 7
STAGE_LINE = "This is one scripted demo request, the buyer's (SIM). When many requests pool, this is what a seller sees."
PRICE_POINTS = (1200, 1250, 1300, 1350, 1400, 1450, 1500)


def _real_order() -> dict:
    """The buyer's order, taken field for field from the sample run's need and owned parts."""
    art = json.loads(SAMPLE_RUN.read_text())["artifacts"]
    need = art["need"]
    item = need["items"][0]
    owned = {p["id"]: p for p in art["owned_parts"]}
    return {
        "id": "vidyut-5070ti", "label": "REAL", "origin": "SIM", "name": "the buyer", "buyer_id": need["buyer_id"],
        "need_id": need["id"], "sku_spec": item["sku_spec"], "quantity": item["quantity"], "cap": float(need["spend_limit"]),
        "conditions": list(item["allowed_conditions"]), "archetype": "real",
        "case_max_gpu_mm": owned["owned-case"]["attrs"]["max_gpu_length_mm"],
        "psu_watts": owned["owned-psu"]["attrs"]["wattage"], "deadline": need["delivery_window"],
    }


def _sim_order(b: dict) -> dict:
    return {
        "id": b["id"], "label": "SIM", "origin": "SIM", "name": f"Builder {b['id'].split('-')[-1]}", "buyer_id": b["id"],
        "need_id": f"need-{b['id']}", "sku_spec": "rtx 5070 ti", "quantity": 1, "cap": b["cap"],
        "conditions": list(b["conditions"]), "archetype": b["archetype"],
        "case_max_gpu_mm": b["case"]["max_gpu_length_mm"], "psu_watts": b["psu"]["wattage"], "deadline": "by Friday",
    }


def summarize(orders: list[dict]) -> dict:
    caps = sorted(o["cap"] for o in orders)
    mid = len(caps) // 2
    median = caps[mid] if len(caps) % 2 else (caps[mid - 1] + caps[mid]) / 2
    return {
        "orders": len(orders), "cap_min": caps[0], "cap_max": caps[-1], "cap_median": median,
        "by_archetype": dict(sorted(Counter(o["archetype"] for o in orders).items())),
        "open_box_ok": sum(1 for o in orders if "open-box" in o["conditions"]),
        "demand_at": [[p, sum(1 for c in caps if c >= p)] for p in PRICE_POINTS],
    }


def build_lot(seed: int = SEED, n: int = LOT_SIZE) -> dict:
    """The pooled lot: n orders, one REAL. The REAL brick's slot comes from the seed so it is not always first."""
    sim = [_sim_order(b) for b in make_builders(n - 1, seed)]
    orders = list(sim)
    orders.insert(random.Random(seed).randrange(n), _real_order())
    return {
        "schema": "tech-bazaar-lot/1", "origin": "SIM", "seed": seed, "sku_spec": "rtx 5070 ti",
        "stage_line": STAGE_LINE, "real_count": 1, "sim_count": n - 1, "orders": orders, "summary": summarize(orders),
        "source": "REAL order: demo/out/sample-run.json. SIM orders: sim.wind_tunnel.make_builders. Demand only, not a market result.",
    }


def main() -> None:
    LOT_JSON.parent.mkdir(parents=True, exist_ok=True)
    LOT_JSON.write_text(json.dumps(build_lot(), indent=1) + "\n")
    print(f"wrote {LOT_JSON}")


if __name__ == "__main__":
    main()
