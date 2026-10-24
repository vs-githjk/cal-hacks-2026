"""Build planner: split a build goal into parts with a budget each, then resolve one round's offers per part.

plan(cap_cents, owned) -> {"cap_cents", "owned", "parts": [{"part", "budget_cents"}], "rules": [rule_id], "steps": [step]}
Owned parts (the buyer's PSU and case) get no round; they still count in every fit rule. Fit is decided by
data.fit_checker.build_check, never guessed here. Every step is {"kind", "line"} so the chat and the Fetch tile
can show it as is.
"""
from data.fit_checker.build_check import RULE_PARTS

PARTS = ("gpu", "cpu", "motherboard", "memory", "storage", "cooler")
# ponytail: fixed 1440p gaming split (GPU ~$1,250, CPU ~$280 of $2,000); per-goal weights when a second goal type lands
WEIGHTS = {"gpu": 1250, "cpu": 280, "motherboard": 170, "memory": 100, "storage": 120, "cooler": 55}
NAMES = {"gpu": "GPU", "cpu": "CPU", "motherboard": "board", "memory": "RAM", "storage": "SSD", "cooler": "cooler",
         "psu": "power supply", "case": "case"}


def dollars(cents):
    return f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def split(cents, parts):
    """Integer cents by WEIGHTS; the rounding remainder goes to the first part, so the budgets sum to cents."""
    total = sum(WEIGHTS[p] for p in parts)
    out = {p: cents * WEIGHTS[p] // total for p in parts}
    if parts:
        out[parts[0]] += cents - sum(out.values())
    return out


def plan(cap_cents, owned=None):
    if isinstance(cap_cents, bool) or not isinstance(cap_cents, int) or cap_cents <= 0:
        raise ValueError("cap_cents must be a positive whole number of cents")
    owned = dict(owned or {})
    parts = [p for p in PARTS if p not in owned]
    budgets = split(cap_cents, parts)
    have = set(parts) | set(owned)
    rules = [r for r, need in RULE_PARTS.items() if set(need) <= have]
    line = "Plan: " + ", ".join(f"{NAMES[p]} ~{dollars(budgets[p])}" for p in parts) + "."
    if owned:
        line += " Your " + " and ".join(NAMES.get(p, p) for p in owned) + " stay."
    return {"cap_cents": cap_cents, "owned": owned, "parts": [{"part": p, "budget_cents": budgets[p]} for p in parts],
            "rules": rules, "steps": [{"kind": "plan", "line": line}]}
