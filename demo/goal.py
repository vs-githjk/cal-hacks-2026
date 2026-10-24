"""Beat 1: Joe's goal and ownership memory. SIM stand-in for Lane A's agents/buyer/goal.py (not merged).

Same shapes as Lane A's Goal, OwnedPart and Need (contracts: Goal and OwnedPart are pending copies under
demo/contracts_pending/). The persona is SIM: nothing here is a real buyer. The one derived fact that is NOT
invented comes from real code: the PSU the RTX 5070 Ti needs is read from data.fit_checker.tables.GPU_POWER.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from demo.common import SIM, money, utc_iso, validate
from data.fit_checker.tables import GPU_POWER

BUYER_ID = "joe"
GOAL_TEXT = "RTX 5070 Ti that fits my case, under $900, by Friday, new or open-box"
ALLOWED_CONDITIONS = ("new", "open-box", "refurbished", "used")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def joe_owned_parts(now: datetime) -> list[dict]:
    """What Joe told the agent earlier (SIM persona). Attrs are SpecCard attrs the fit checker reads."""
    when = utc_iso(now - timedelta(days=9))
    told = lambda text: f"'{text}', told on {when[:10]}"
    parts = [
        ("owned-psu", "psu 750w", "750 W PSU", {"wattage": 750, "form_factor": "ATX", "pcie_16pin": 1},
         told("I have a 750 W PSU with a native 16-pin cable")),
        ("owned-ram", "memory ddr5 32gb", "32 GB DDR5", {"type": "DDR5", "modules": 2, "module_gb": 16},
         told("I already have 32 GB of DDR5")),
        ("owned-case", "case mid-tower", "mid-tower case", {"max_gpu_length_mm": 305},
         told("my case takes cards up to 305 mm")),
    ]
    return [validate("OwnedPart", {"id": pid, "buyer_id": BUYER_ID, "sku_spec": sku, "item_name": name,
                                   "condition": "unknown", "acquired_on": "", "source": "told_by_user",
                                   "attrs": attrs, "notes": note}) for pid, sku, name, attrs, note in parts]


def _next_weekday(now: datetime, name: str) -> str:
    ahead = (WEEKDAYS.index(name) - now.weekday()) % 7 or 7
    return f"{(now + timedelta(days=ahead)).date().isoformat()}T23:59:00Z"


def parse_goal(text: str, now: datetime) -> dict:
    """Buyer words to Goal fields: cap, deadline weekday and allowed conditions. Plain rules, no model."""
    cap = re.search(r"(?:under|below|max|up to|less than)\s*\$?\s*(\d[\d,]*(?:\.\d+)?)", text, re.I)
    if not cap:
        raise ValueError("a goal needs a cap, for example 'under $900'")
    day = next((d for d in WEEKDAYS if re.search(rf"\b{d}\b", text, re.I)), None)
    deadline = _next_weekday(now, day) if day else utc_iso(now + timedelta(days=7))
    conds = [c for c in ALLOWED_CONDITIONS if re.search(rf"\b{c.replace('-', '[- ]')}\b", text, re.I)] or ["new"]
    chip = re.search(r"rtx\s*(\d{4})\s*(ti|super)?", text, re.I)
    if not chip:
        raise ValueError("this demo parses RTX cards only")
    sku = f"rtx {chip.group(1)}{' ' + chip.group(2).lower() if chip.group(2) else ''}"
    return {"cap": float(cap.group(1).replace(",", "")), "deadline": deadline, "allowed_conditions": conds, "sku_spec": sku}


def required_psu_watts(chipset: str) -> int:
    """The maker-recommended PSU for this GPU, from the real fit tables (data.fit_checker.tables)."""
    return int(GPU_POWER[chipset]["rec_psu_w"])


def build_goal(text: str, owned: list[dict], now: datetime) -> dict:
    p = parse_goal(text, now)
    chipset = " ".join(w.upper() if w == "rtx" else w.capitalize() for w in p["sku_spec"].split())  # "RTX 5070 Ti"
    need_w = required_psu_watts(chipset)
    psu_line = {"part": "psu", "sku_spec": f"psu {need_w}w", "condition": "new", "variant": "retail", "quantity": 1,
                "note": f"derived: {chipset} needs a {need_w} W PSU (maker recommendation, data.fit_checker.tables)"}
    mine = next((o for o in owned if o["sku_spec"].startswith("psu ")), None)
    if mine and mine["attrs"].get("wattage", 0) >= need_w and not re.search(r"\b(upgrade|replace)\b", text, re.I):
        psu_line["skipped_owned_part_id"] = mine["id"]
    gpu_line = {"part": "gpu", "sku_spec": p["sku_spec"], "condition": p["allowed_conditions"][0],
                "allowed_conditions": p["allowed_conditions"], "variant": "retail", "quantity": 1}
    goal = {"id": "goal-joe-5070ti", "buyer_id": BUYER_ID, "type": "part_by_date", "items": [gpu_line, psu_line],
            "cap": p["cap"], "deadline": p["deadline"], "state": "ACTIVE", "reserved_amount": 0,
            "created_at": utc_iso(now), "notes": f"'{text}'"}
    return validate("Goal", goal)


def need_from_goal(goal: dict, auction_window_s: int = 12) -> dict:
    """The Need sellers see. Sealed: the cap stays with the buyer agent in `spend_limit`, which the market
    strips before bids open (Lane B redaction). Owned lines are dropped."""
    items = [{"sku_spec": i["sku_spec"], "grade": i["condition"], "pack_size": i["variant"], "quantity": i["quantity"],
              "unit": "each", "condition": i["condition"], "allowed_conditions": i.get("allowed_conditions", [i["condition"]]),
              "variant": i["variant"]} for i in goal["items"] if not i.get("skipped_owned_part_id")]
    return validate("Need", {"id": "need-joe-5070ti", "buyer_id": goal["buyer_id"], "items": items,
                             "delivery_window": f"by {goal['deadline']}", "spend_limit": goal["cap"], "consent": True,
                             "auction_window_s": auction_window_s, "source": "simulated"})


def joe_allowance(now: datetime) -> dict:
    """SIM: what Joe may spend without a call. A brand new buyer starts at 0; Joe has two clean receiving checks."""
    return validate("Allowance", {"buyer_id": BUYER_ID, "currency": "USD", "per_purchase_limit": 250.0, "period_limit": 500.0,
                           "period": "month", "spent_this_period": 120.0, "ladder_step": 1,
                              "updated_at": utc_iso(now)})


def needs_call(allowance: dict, amount: float) -> tuple[bool, str]:
    """One rule: above the allowance the agent calls. Both the per-purchase and the period room count."""
    room = allowance["period_limit"] - allowance["spent_this_period"]
    if amount > allowance["per_purchase_limit"]:
        return True, f"{money(amount)} is over the {money(allowance['per_purchase_limit'])} per-purchase allowance"
    if amount > room:
        return True, f"{money(amount)} is over the {money(room)} left this {allowance['period']}"
    return False, "within allowance"


def skip_lines(goal: dict, owned: list[dict]) -> list[str]:
    by_id = {o["id"]: o for o in owned}
    return [f"skipped {i['part'].upper()} line ({i['sku_spec']}): Joe already owns {by_id[i['skipped_owned_part_id']]['item_name']}, "
            f"entry {i['skipped_owned_part_id']}, {by_id[i['skipped_owned_part_id']]['notes']}"
            for i in goal["items"] if i.get("skipped_owned_part_id") in by_id]


def run_beat1(now: datetime, say) -> dict:
    owned = joe_owned_parts(now)
    goal = build_goal(GOAL_TEXT, owned, now)
    need = need_from_goal(goal)
    allowance = joe_allowance(now)
    say.header(1, "Joe sets a goal", "SIM stand-in for agents/buyer/goal.py (Lane A, not merged); PSU need read from real data.fit_checker.tables")
    say.line(SIM, f'Joe: "{GOAL_TEXT}"')
    say.line(SIM, f"Goal {goal['id']}: {goal['type']}, cap {money(goal['cap'])}, deadline {goal['deadline']}, "
                  f"conditions {'/'.join(goal['items'][0]['allowed_conditions'])}, state {goal['state']}")
    say.line(SIM, "Ownership memory (told by Joe, persona is SIM):")
    for o in owned:
        say.line(SIM, f"{o['id']}: {o['item_name']}  attrs {o['attrs']}", 1)
    for s in skip_lines(goal, owned):
        say.line(SIM, s)
    say.line(SIM, f"Need sent to sellers: {len(need['items'])} line(s), cap withheld (sealed). Lines: "
                  + ", ".join(i["sku_spec"] for i in need["items"]))
    say.line(SIM, f"Allowance: {money(allowance['per_purchase_limit'])} per purchase, "
                  f"{money(allowance['period_limit'] - allowance['spent_this_period'])} left this {allowance['period']}")
    return {"goal_text": GOAL_TEXT, "owned_parts": owned, "goal": goal, "need": need, "allowance": allowance,
            "skip_lines": skip_lines(goal, owned), "origin": SIM}
