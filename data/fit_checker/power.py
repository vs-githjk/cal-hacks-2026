"""Does the buyer's owned PSU power this GPU? (issue #125). Maker spec per SKU, chipset reference when the model is unknown.

    check_power(gpu_title_or_url, owned_psu) -> {status, reason, source, rec_psu_w, connector}
owned_psu: {"wattage", "pcie_16pin", "pcie_8pin"}; a missing key is unknown, never zero.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .tables import GPU_POWER

HERE = Path(__file__).resolve().parent
TABLE = HERE / "gpu_power.json"
OWNED_PSU = HERE / "owned_psu_sim.json"
ORDER = ["pass", "caution", "uncertain", "fail"]


def _row(text: str) -> dict | None:
    return next((r for r in json.loads(TABLE.read_text())["models"] if re.search(r["match"], text, re.I)), None)


def _adapter_count(row, ref) -> int:
    m = re.match(r"\s*(\d+)x", (row or {}).get("adapter_in_box") or "")
    return int(m.group(1)) if m else ref["connector"][1]


def check_power(gpu_title_or_url: str, owned_psu: dict) -> dict:
    ref = GPU_POWER["RTX 5070 Ti"]
    row = _row(gpu_title_or_url)
    rec = row["rec_psu_w"] if row else ref["rec_psu_w"]
    source = row["source"] if row else "nvidia.com chipset reference (RTX 5070 Ti)"
    where = f"the maker lists {rec} W" if row else f"the chipset reference is {rec} W (model not identified)"
    reasons, states = [], []

    watts = owned_psu.get("wattage")
    if watts is None:
        states.append("uncertain"); reasons.append(f"PSU wattage unknown; {where}")
    elif watts < rec:
        states.append("fail"); reasons.append(f"PSU is {watts} W; {where}")
    else:
        states.append("pass"); reasons.append(f"PSU is {watts} W; {where}")

    p16, p8 = owned_psu.get("pcie_16pin"), owned_psu.get("pcie_8pin")
    n = _adapter_count(row, ref)
    if p16:
        states.append("pass"); reasons.append("native 12V-2x6 cable")
    elif p16 is None and p8 is None:
        states.append("uncertain"); reasons.append("PSU connector counts unknown")
    elif p8 is not None and p8 >= n:
        states.append("caution"); reasons.append(f"uses the card's adapter from {n}x 8-pin; seat it fully")
    elif p8 is None:
        states.append("uncertain"); reasons.append("PSU 8-pin count unknown")
    else:
        states.append("fail"); reasons.append(f"card's adapter needs {n}x 8-pin; PSU has {p8} and no 16-pin")

    return {"status": max(states, key=ORDER.index), "reason": "; ".join(reasons), "source": source,
            "rec_psu_w": rec, "connector": (row or {}).get("connector") or "16-pin 12V-2x6 (chipset reference)"}
