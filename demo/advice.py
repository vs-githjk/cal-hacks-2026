"""The advocate step of a round: Lane A's REAL agents/advocate/checks.py decides fit, condition mismatch, price
history, recall and seller record; this glue feeds it one bid at a time and adds what it does not read yet.

What the runner adds around the real code (each is noted on the card, none changes a check):
  - the bid handed to checks.advise carries only the line the market picked (lines are alternatives, so the
    unpicked condition line must not be fit-checked as a second GPU);
  - the need item's condition is the picked line's condition when the goal allows it, so an allowed open-box
    line is not flagged as "you asked for new" (checks.py compares to one condition, not allowed_conditions);
  - false claims from Lane C's claim check become warnings (checks.py does not read claim results yet);
  - the price-history baseline, seller records and CPSC recall list are empty here: Lane A's mock_data covers
    other SKUs, and the real feeds need the network.
"""
from __future__ import annotations

from data.fit_checker import check_fit

from demo.adapters import advocate_checks

# claim kind -> (warning kind, rule id); a false claim of any other kind is shown as an info note, never a veto
CLAIM_RULE = {"spec": ("condition", "advocate.condition"), "condition": ("condition", "advocate.condition"),
              "price": ("price", "advocate.price")}


def _claim_warning(claim: dict, landed: float):
    kind, rule = CLAIM_RULE.get(claim["kind"], ("note", "advocate.unsourced"))
    return {"kind": kind, "rule_id": rule, "text": f"\"{claim['text']}\": {claim['reason']}.", "source_url": claim["evidence_url"],
            "dollar_impact": round(float(landed), 2), "evidence_hash": claim["evidence_hash"], "checked_at": claim["checked_at"]}


def fit_display(bid: dict, owned_attrs: dict) -> dict:
    """The fit checks the real advocate ran, shown for the console (same cards, same rule filter)."""
    mod, _ = advocate_checks()
    cards = mod._spec_cards(bid, owned_attrs)
    bid_parts = {c["category"] for c in cards if not c["id"].startswith("owned-")}
    fit = check_fit(cards)
    checks = [c for c in fit["checks"] if mod.RULE_PARTS.get(c["rule_id"], bid_parts) & bid_parts]
    verdict = "fail" if any(c["verdict"] == "fail" for c in checks) else "uncertain" if any(c["verdict"] == "uncertain" for c in checks) else "pass"
    return {"verdict": verdict, "checks": checks}


def advise(need: dict, bid: dict, entry: dict, claims: list[dict], owned_attrs: dict) -> dict:
    """One AdvocateCard for a bid, judged on the line the market picked (`entry`, from market.rank_bids)."""
    mod, _ = advocate_checks()
    sel = bid["lines"][entry["line"]]
    one = {**bid, "lines": [sel], "supplier_id": bid["seller_id"], "total_landed_price": entry["landed"]}
    item = dict(need["items"][0])
    if sel["offered_condition"] in (item.get("allowed_conditions") or []):
        item["condition"] = sel["offered_condition"]
    card = mod.advise({**need, "items": [item]}, [one], {}, {}, [], owned=owned_attrs)[0]
    have_condition = any(w["kind"] == "condition" for w in card["warnings"])
    extra = [_claim_warning(c, entry["landed"]) for c in claims if c["check"] == "false"]
    extra = [w for w in extra if not (w["kind"] == "condition" and have_condition)]
    warnings = sorted(card["warnings"] + extra, key=lambda w: -w["dollar_impact"])
    kinds = {w["kind"] for w in warnings}
    rec = "veto" if kinds & mod.VETO_KINDS else "caution" if kinds - mod.INFO_KINDS else "buy"
    reason = mod.call_reason(warnings, one)
    card = {**card, "warnings": warnings[:mod.MAX_WARNINGS], "recommendation": rec, "call_reason": reason,
            "rule_id": reason["rule_id"], "reason": reason["summary"], "source_url": reason["source_url"],
            "line": entry["line"], "fit": fit_display(one, owned_attrs), "judged_condition": sel["offered_condition"]}
    return card
