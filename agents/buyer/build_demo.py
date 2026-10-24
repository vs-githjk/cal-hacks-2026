"""SIM demo: a scripted 3-part build (GPU, PSU, case) planned with the real fit checker. No network, no model, no Stripe."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root for data/ and pay/

from agents.buyer.composite import plan_build

SPECS = {
    "gpu": {"chipset": "RTX 5070 Ti", "length_mm": 300, "board_power_w": 300, "rec_psu_w": 750, "power_connector": ["8pin", 2]},
    "psu": {"wattage": 850, "form_factor": "ATX", "pcie_8pin": 2},
    "case": {"type": "ATX Mid Tower", "motherboard_form_factors": ["ATX"], "psu_form_factors": ["ATX"], "max_gpu_length_mm": 330},
}
CENTS = {"gpu": 30000, "psu": 12000, "case": 9000}


def pick(part, **attrs):
    sku = f"{part}-sku"
    line = {"sku_spec": sku, "condition": "new", "qty_available": 1, "unit_price": CENTS[part] // 100}
    bid = {"id": f"bid-{part}", "source": "sim:build-demo", "origin": "SIM", "lines": [line]}
    spec = {"id": f"{part}-card", "category": part, "name": part, "attrs": {**SPECS[part], **attrs},
            "origin": "SIM", "source": "sim:build-demo"}
    quote = {"bid_id": bid["id"], "line_index": 0, "sku_spec": sku, "condition": "new", "quantity": 1,
             "shipping_cents": 0, "tax_cents": 0, "landed_total_cents": CENTS[part],
             "spec_card_id": spec["id"], "currency": "USD"}
    return {"bid": bid, "line_index": 0, "line": line, "spec_card": spec, "quote": quote}


def run(title, gpu_attrs, cap=600):
    goal = {"id": "goal-demo", "buyer_id": "buyer-demo", "type": "build_by_date", "cap": cap,
            "items": [{"part": p, "sku_spec": f"{p}-sku", "condition": "new", "quantity": 1} for p in SPECS]}
    out = plan_build(goal, {"gpu": pick("gpu", **gpu_attrs), "psu": pick("psu"), "case": pick("case")}, [], {}, cap)
    print(f"[SIM scripted data] {title} (cap ${cap})")
    for p in out["parts"]:
        print(f"  SIM {p['part']}: landed ${p['amount_cents'] / 100:.2f}")
    print(f"  SIM fit: {out['fit']['verdict']} ({out['fit'].get('rule_id')})")
    print(f"  SIM total ${out['planned_total_cents'] / 100:.2f} of ${out['cap_cents'] / 100:.2f} cap")
    print("  SIM plan ready" if out["status"] == "plan_ready" else f"  SIM refused: {out['blocked_reasons'][0]}")
    return out


def main():
    run("Run 1: parts that fit", {})
    run("Run 2: GPU too long for the case", {"length_mm": 400})


if __name__ == "__main__":
    main()
