"""SIM: the 6-part build story through the real planner and fit checker. Scripted offers, no network, no model, no Stripe.

python -m agents.buyer.build_plan_demo   prints each step line as the chat and the Fetch tile would show it.
"""
from agents.buyer.planner import plan, resolve

OWNED = {"psu": {"name": "750 W PSU", "wattage": 750, "form_factor": "ATX", "pcie_16pin": 1},
         "case": {"name": "Owned case", "max_gpu_length_mm": 305, "max_cooler_height_mm": 160,
                  "motherboard_form_factors": ["ATX", "Micro ATX"], "psu_form_factors": ["ATX"]}}
AM5 = {"socket": "AM5", "memory_type": "DDR5", "memory_form": "DIMM", "memory_slots": 4, "form_factor": "ATX", "m2_slots": 2}


def offer(seller, dollars, **spec):
    return {"seller": seller, "price_cents": dollars * 100, "spec": spec}


def offers(boards=None):
    return {
        "gpu": [offer("Best Buy", 1199, name="RTX 5070 Ti long", chipset="RTX 5070 Ti", length_mm=336),
                offer("Central Computers", 1249, name="RTX 5070 Ti", chipset="RTX 5070 Ti", length_mm=304)],
        "cpu": [offer("Best Buy", 279, name="Ryzen 7 7700X", socket="AM5", tdp_w=105, vendor="AMD")],
        "motherboard": boards or [offer("B&H", 169, name="B650 board", **AM5)],
        "memory": [offer("Amazon", 99, name="32 GB DDR5", type="DDR5", form="DIMM", modules=2)],
        "storage": [offer("Best Buy", 119, name="2 TB NVMe", interface="M.2 PCIe NVMe")],
        "cooler": [offer("Amazon", 45, name="Tall cooler", height_mm=165, sockets=["AM5"]),
                   offer("Central Computers", 53, name="Low cooler", height_mm=155, sockets=["AM5"])],
    }


CLASH_BOARDS = [offer("B&H", 149, name="B760 board", **{**AM5, "socket": "LGA1700"}), offer("B&H", 189, name="B650 board", **AM5)]


def run():
    """The demo run: a GPU too long, a cooler too tall, a socket clash that swaps the board and moves budget."""
    return resolve(plan(200_000, OWNED), offers(CLASH_BOARDS))


if __name__ == "__main__":
    for step in run()["steps"]:
        print(f"SIM {step['kind']}: {step['line']}")
