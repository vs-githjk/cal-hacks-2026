"""ReNew Refurb (seller_5), the honest refurbisher.

One bid carries a refurbished line and an open-box line of the same part. Each line is labelled with its condition, and
the bid explains the tradeoff in plain words ("$78.40 less, a 90-day warranty instead of 1 year"). Every number in those
words comes from the bid's own lines and from TERMS below, which are also what its listing pages show, so the claim
check verifies them (agents/sellers/test_mind_refurb.py). Nothing here is a model: the words are code, so they can
never drift from the price. SIM terms: this is a simulated seller.
"""
from __future__ import annotations

import copy

from agents.sellers import listing_pages

SELLER_ID = "seller_5"
# Per condition: warranty and return window, and what the condition means. The same numbers go on the listing pages.
TERMS = {"refurbished": {"warranty_months": 3, "returns_days": 14,
                         "wear": "tested and cleaned, may show light cosmetic wear"},
         "open-box": {"warranty_months": 12, "returns_days": 14,
                      "wear": "opened once and tested, in the original packaging"}}


def warranty_words(months: int) -> str:
    """Plain words for a warranty term: 3 months reads 90-day, 12 months reads 1-year."""
    return {3: "90-day", 12: "1-year"}.get(months, f"{months}-month")


def _by_sku(lines: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for line in lines:
        out.setdefault(line["sku_spec"], []).append(line)
    return {sku: sorted(group, key=lambda l: l["unit_price"]) for sku, group in out.items()}


def tradeoffs(bid: dict) -> list[str]:
    """One plain sentence per part: the cheapest line against the next one, or the single line's terms."""
    out = []
    for sku, group in _by_sku(bid["lines"]).items():
        cheap = group[0]
        t = TERMS[cheap["offered_condition"]]
        if len(group) == 1:
            out.append(f"{sku}: {cheap['offered_condition']} at ${cheap['unit_price']:,.2f}, {t['wear']}, "
                       f"{warranty_words(t['warranty_months'])} warranty, {t['returns_days']}-day returns.")
            continue
        other = group[1]
        o = TERMS[other["offered_condition"]]
        out.append(f"{sku}: the {cheap['offered_condition']} line is ${other['unit_price'] - cheap['unit_price']:,.2f} less "
                   f"than my {other['offered_condition']} line, with a {warranty_words(t['warranty_months'])} warranty "
                   f"instead of {warranty_words(o['warranty_months'])}.")
    return out


def line_claims(bid: dict) -> list[str]:
    """One truthful, checkable claim per condition on the bid (the claim check reads the months and the days)."""
    seen, out = [], []
    for line in bid["lines"]:
        cond = line["offered_condition"]
        if cond in seen:
            continue
        seen.append(cond)
        t = TERMS[cond]
        out.append(f"{cond}: {t['warranty_months']}-month warranty, {t['returns_days']}-day returns")
    return out


def claim_for_line(line: dict) -> dict:
    """The claim to check for one line, citing that line's own listing page."""
    t = TERMS[line["offered_condition"]]
    return {"text": f"{line['offered_condition']}: {t['warranty_months']}-month warranty, {t['returns_days']}-day returns",
            "evidence_url": line["listing_url"]}


def pages_for(bid: dict) -> dict[str, str]:
    """What each line's listing page truly shows: its condition, its price, its warranty and returns."""
    pages = {}
    for line in bid["lines"]:
        t = TERMS[line["offered_condition"]]
        facts = listing_pages.facts_for_line(line, seller_id="renew-refurb", warranty_months=t["warranty_months"],
                                             return_days=t["returns_days"], extra={"condition_note": t["wear"]})
        pages[line["listing_url"]] = listing_pages.render(facts, f"{line['sku_spec']} ({line['offered_condition']})")
    return pages


def decorate(bid: dict) -> dict:
    """The bid with its truthful per-condition claims, the tradeoff in plain words and the trace line. Prices, lines and
    totals are untouched."""
    out = copy.deepcopy(bid)
    notes = tradeoffs(out)
    out["claims"] = [*out["claims"], *line_claims(out)]
    out["tradeoff"] = notes
    out["decision_trace"] = out["decision_trace"] + " Tradeoff: " + " ".join(notes)
    return out


def persona(bid: dict) -> str:
    """The one floor line: the first part's tradeoff, from the same code."""
    return "ReNew Refurb here. " + tradeoffs(bid)[0]
