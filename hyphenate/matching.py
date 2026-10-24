"""Three-way match: PO (what we agreed) against the seller's invoice and claim (what they say) against the receiving check
(what arrived). Pure functions: the same inputs always give the same findings, so every hold can be re-derived.

A finding is a hold unless its code is in IMMATERIAL. Credit amounts are what a credit memo request would ask for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hyphenate.org import Policy

IMMATERIAL = {"price_variance_immaterial"}


@dataclass(frozen=True)
class Finding:
    code: str
    sku: str
    detail: str
    credit: int = 0  # cents the vendor should credit

    @property
    def hold(self) -> bool:
        return self.code not in IMMATERIAL

    def to_dict(self) -> dict:
        return {"code": self.code, "sku": self.sku, "detail": self.detail, "credit": self.credit, "hold": self.hold}


def line_tolerance(po_line_total: int, policy: Policy, strict: bool) -> int:
    """Cents of price difference on one line that count as immaterial. A strict vendor gets none."""
    if strict:
        return 0
    return max(policy.price_tol_abs, round(po_line_total * policy.price_tol_pct))


def match_lines(po_lines: list, inv_lines: list, policy: Policy, *, strict: bool) -> list:
    """po_lines: [{sku, qty, unit, condition, allowed, accepted, rejected, billed, accepted_conditions}]
    inv_lines: [{sku, qty, unit, condition}]. `accepted`/`billed` are cumulative before this invoice."""
    out: list[Finding] = []
    by_sku = {l["sku"]: l for l in po_lines}
    for il in inv_lines:
        pl = by_sku.get(il["sku"])
        if pl is None:
            out.append(Finding("sku_not_on_po", il["sku"], f"invoice bills {il['sku']}, which is not on the PO", il["qty"] * il["unit"]))
            continue
        billed_after = pl["billed"] + il["qty"]
        if billed_after > pl["qty"]:
            over = billed_after - pl["qty"]
            out.append(Finding("qty_over_po", il["sku"], f"billed {billed_after} units against a PO for {pl['qty']}", over * il["unit"]))
        if billed_after > pl["accepted"]:
            gap = billed_after - max(pl["accepted"], pl["billed"])
            if pl["accepted"] + pl["rejected"] == 0:
                out.append(Finding("billed_before_receipt", il["sku"], "nothing received yet for this line"))
            else:
                why = f"{pl['accepted']} accepted" + (f", {pl['rejected']} rejected" if pl["rejected"] else "")
                out.append(Finding("qty_short", il["sku"], f"billed {billed_after} units, received {why}", gap * il["unit"]))
        # price: the contract (PO) is the reference; the invoice only asks
        diff = (il["unit"] - pl["unit"]) * il["qty"]
        if diff != 0:
            tol = line_tolerance(pl["unit"] * il["qty"], policy, strict)
            if abs(diff) <= tol:
                out.append(Finding("price_variance_immaterial", il["sku"], f"{diff:+d} cents on the line, inside the {tol} cent tolerance"))
            else:
                out.append(Finding("price_variance", il["sku"], f"{diff:+d} cents on the line against a {tol} cent tolerance",
                                   max(diff, 0)))
        # condition: what we inspected beats what they claim; the PO says what we bought
        got = pl["accepted_conditions"]
        bad = [c for c in got if c != il["condition"]]
        if bad:
            out.append(Finding("condition_mismatch", il["sku"], f"invoice says {il['condition']}, receiving found {sorted(set(bad))[0]}",
                               len(bad) * il["unit"]))
        elif il["condition"] != pl["condition"]:
            out.append(Finding("condition_mismatch", il["sku"], f"invoice says {il['condition']}, PO bought {pl['condition']}", il["qty"] * il["unit"]))
    return out
