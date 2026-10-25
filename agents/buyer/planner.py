"""Build planner: split a build goal into parts with a budget each, then resolve one round's offers per part.

plan(cap_cents, owned) -> {"cap_cents", "owned", "parts": [{"part", "budget_cents"}], "rules": [rule_id], "steps": [step]}
Owned parts (the buyer's PSU and case) get no round; they still count in every fit rule. Fit is decided by
data.fit_checker.build_check, never guessed here. Every step is {"kind", "line"} so the chat and the Fetch tile
can show it as is.
"""
from data.fit_checker.build_check import RULE_PARTS, check_build

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
    line = "Plan: " + ", ".join(f"{NAMES[p]} ~${round(budgets[p] / 100):,}" for p in parts) + "."
    if owned:
        line += " Your " + " and ".join(NAMES.get(p, p) for p in owned) + " stay."
    return {"cap_cents": cap_cents, "owned": owned, "parts": [{"part": p, "budget_cents": budgets[p]} for p in parts],
            "rules": rules, "steps": [{"kind": "plan", "line": line}]}


def _spec(part, offer):
    spec = dict(offer.get("spec") or {})
    spec.setdefault("name", offer.get("name") or f"{offer.get('seller', '?')} {part}")
    return spec


def _checks(build):
    """The fit checks (check_build()["checks"]) for the parts picked so far plus the owned ones."""
    return check_build({k: ([v] if k == "storage" else v) for k, v in build.items()})["checks"]


def _fit_fails(build, part, spec):
    """Failing fit checks that involve this part, given the parts already picked plus the owned ones."""
    return [c for c in _checks({**build, part: spec})
            if c["verdict"] == "fail" and part in RULE_PARTS.get(c["rule_id"], ())]


def _good_price(offer):
    price = offer.get("price_cents")
    return isinstance(price, int) and not isinstance(price, bool) and price > 0


def _origin(offer):
    """LIVE, MIRROR or SIM as the offer says; anything missing or unknown is SIM, never upgraded to LIVE."""
    o = offer.get("origin")
    return o if o in ("LIVE", "MIRROR", "SIM") else "SIM"


def _early(offer):
    """The early knockout for an offer as (rule_id, reason), or None: bad price, not orderable, no spec."""
    if not _good_price(offer):
        return ("offer.bad_price", "has no real price")
    if offer.get("orderable") is False:
        return ("offer.not_orderable", "cannot be ordered")
    if not offer.get("spec"):
        return ("offer.no_spec", "has no part details to check")
    return None


def resolve(p, offers):
    """Pick one offer per part, cheapest first, from each round's offers {part: [{seller, price_cents, spec, source?}]}.

    An offer that breaks a fit rule is knocked out with the reason; a clash with a part already picked (a CPU socket
    against the board) is a red line, and the next offer that fits is the swap. An offer over its part's budget is
    taken when the cap still covers the cheapest offer of every open part (the overage moves from those parts),
    otherwise it is knocked out. After each pick the rest of the cap is split again over the open parts.
    """
    owned = p["owned"]
    budgets = {x["part"]: x["budget_cents"] for x in p["parts"]}
    build = {k: _spec(k, {"spec": v}) for k, v in owned.items()}
    picks, knockouts, steps, spent = {}, [], list(p["steps"]), 0
    parts = list(budgets)
    if not parts:
        steps.append({"kind": "blocked", "line": "Nothing to buy: every part is already yours."})
        return {"status": "blocked", "picks": picks, "knockouts": knockouts, "budgets": budgets, "total_cents": 0,
                "steps": steps, "checks": []}
    for part in parts:
        clashed = None
        for offer in sorted(offers.get(part) or [], key=lambda o: o["price_cents"] if _good_price(o) else 0):
            spec, price, seller = _spec(part, offer), offer.get("price_cents"), offer.get("seller", "?")
            origin = _origin(offer)
            early = _early(offer)
            if early:
                knockouts.append({"part": part, "seller": seller, "rule_id": early[0], "reason": early[1], "origin": origin})
                steps.append({"kind": "knockout", "part": part, "rule_id": early[0],
                              "line": f"{NAMES[part]}: {seller} out, {early[1]}."})
                continue
            later = parts[parts.index(part) + 1:]
            floor = sum(min((o["price_cents"] for o in offers.get(k) or [] if not _early(o)), default=0) for k in later)
            if price > budgets[part] and spent + price + floor > p["cap_cents"]:
                reason = f"{dollars(price)} is over the {dollars(budgets[part])} {NAMES[part]} budget and the cap leaves no room"
                knockouts.append({"part": part, "seller": seller, "rule_id": "budget.over", "reason": reason, "origin": origin})
                steps.append({"kind": "knockout", "part": part, "line": f"{NAMES[part]}: {seller} out, {reason}."})
                continue
            fails = _fit_fails(build, part, spec)
            if fails:
                c = fails[0]
                knockouts.append({"part": part, "seller": seller, "rule_id": c["rule_id"], "reason": c["reason"],
                                  "sources": c.get("sources", []), "origin": origin})
                other = [k for k in RULE_PARTS[c["rule_id"]] if k != part and k in picks]
                if other:
                    clashed = c["rule_id"]
                    steps.append({"kind": "clash", "part": part, "with": other, "rule_id": c["rule_id"],
                                  "line": f"Clash: {spec['name']} vs your {NAMES[other[0]]}: {c['reason']}."})
                else:
                    steps.append({"kind": "knockout", "part": part, "rule_id": c["rule_id"],
                                  "line": f"{NAMES[part]}: {seller} out, {c['reason']}."})
                continue
            over = price - budgets[part]
            picks[part] = {"seller": seller, "price_cents": price, "spec": spec, "source": offer.get("source", ""),
                           "origin": origin}
            build[part] = spec
            kind = "swap" if clashed else "pick"
            step = {"kind": kind, "part": part, "line": (f"Swapped the {NAMES[part]} to {spec['name']} "
                    if clashed else f"{NAMES[part]}: {spec['name']} ") + f"from {seller}, {dollars(price)}."}
            if clashed:
                step["checks"] = _checks(build)  # fresh, so the UI can turn the red line green
            steps.append(step)
            if over > 0:
                src = "from the parts still open" if later else "out of what is left of the cap, as no parts are still open"
                steps.append({"kind": "reallocate", "part": part, "line": f"{NAMES[part]} is {dollars(over)} over its "
                              f"{dollars(budgets[part])} budget; moved {dollars(over)} {src}."})
            spent += price
            budgets.update(split(p["cap_cents"] - spent, later))  # savings and overage both move to the open parts
            break
        else:
            steps.append({"kind": "blocked", "part": part, "line": f"No {NAMES[part]} offer fits and stays in budget. Nothing was paid."})
            return {"status": "blocked", "picks": picks, "knockouts": knockouts, "budgets": budgets,
                    "total_cents": sum(x["price_cents"] for x in picks.values()), "steps": steps,
                    "checks": _checks(build) if len(build) > len(owned) else []}
    total = sum(x["price_cents"] for x in picks.values())
    sellers = sorted({x["seller"] for x in picks.values()})
    checks = _checks(build)
    unsure = [c for c in checks if c["verdict"] == "uncertain" and any(k in picks for k in RULE_PARTS.get(c["rule_id"], ()))]
    if unsure:  # an unknown spec never locks a build; nothing is swapped over it
        c = unsure[0]
        who = next(NAMES[k] for k in RULE_PARTS[c["rule_id"]] if k in picks)
        steps.append({"kind": "needs_check", "line": f"Needs a check: the {who} fit ({c['rule_id'].removeprefix('fit.').replace('_', ' ')}) "
                      f"is not confirmed, {c['reason']}."})
        status = "needs_check"
    else:
        steps.append({"kind": "locked", "line": f"Build locked: {len(picks)} parts, {len(sellers)} sellers, {dollars(total)}."})
        status = "locked"
    return {"status": status, "picks": picks, "knockouts": knockouts, "budgets": budgets, "total_cents": total,
            "sellers": sellers, "steps": steps, "checks": checks}
