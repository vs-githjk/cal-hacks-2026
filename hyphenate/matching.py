"""Three-way match: PO (what we agreed) against the seller's invoice and claim (what they say) against the receiving check
(what arrived). Pure functions: the same inputs always give the same findings, so every hold can be re-derived.

A finding is a hold unless its code is in IMMATERIAL. Credit amounts are what a credit memo request would ask for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hyphenate.org import Policy

IMMATERIAL = {"price_variance_immaterial"}
# duplicate_line_sku is informational unless the summed quantities then fail another check
IMMATERIAL.add("duplicate_line_sku")


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
    # Several invoice lines for one SKU are one bill for that SKU: quantities add up before any comparison,
    # otherwise two qty-1 lines each pass "1 <= 1 received" while the bill is for 2.
    groups: dict = {}
    for il in inv_lines:
        g = groups.setdefault(il["sku"], {"qty": 0, "diff_base": 0, "conds": set(), "unit": il["unit"], "lines": []})
        g["qty"] += il["qty"]
        g["conds"].add(il["condition"])
        g["lines"].append(il)
        g["unit"] = max(g["unit"], il["unit"])
    for sku, g in groups.items():
        pl = by_sku.get(sku)
        if pl is None:
            out.append(Finding("sku_not_on_po", sku, f"invoice bills {sku}, which is not on the PO", sum(l["qty"] * l["unit"] for l in g["lines"])))
            continue
        qty, unit = g["qty"], g["unit"]
        billed_after = pl["billed"] + qty
        if len(g["lines"]) > 1:
            out.append(Finding("duplicate_line_sku", sku, f"{len(g['lines'])} invoice lines for {sku}; quantities are added before matching"))
        if billed_after > pl["qty"]:
            out.append(Finding("qty_over_po", sku, f"billed {billed_after} units against a PO for {pl['qty']}", (billed_after - pl["qty"]) * unit))
        if billed_after > pl["accepted"]:
            gap = billed_after - max(pl["accepted"], pl["billed"])
            if pl["accepted"] + pl["rejected"] == 0:
                out.append(Finding("billed_before_receipt", sku, "nothing received yet for this line"))
            else:
                why = f"{pl['accepted']} accepted" + (f", {pl['rejected']} rejected" if pl["rejected"] else "")
                out.append(Finding("qty_short", sku, f"billed {billed_after} units, received {why}", gap * unit))
        # price: the contract (PO) is the reference; the invoice only asks
        diff = sum((l["unit"] - pl["unit"]) * l["qty"] for l in g["lines"])
        if diff != 0:
            tol = line_tolerance(pl["unit"] * qty, policy, strict)
            if abs(diff) <= tol:
                out.append(Finding("price_variance_immaterial", sku, f"{diff:+d} cents on the line, inside the {tol} cent tolerance"))
            else:
                out.append(Finding("price_variance", sku, f"{diff:+d} cents on the line against a {tol} cent tolerance", max(diff, 0)))
        # condition: what we inspected beats what they claim; the PO says what we bought
        bad = [c for c in pl["accepted_conditions"] if c not in g["conds"]]
        if bad:
            out.append(Finding("condition_mismatch", sku, f"invoice says {', '.join(sorted(g['conds']))}, receiving found {sorted(set(bad))[0]}", len(bad) * unit))
        elif any(c != pl["condition"] for c in g["conds"]):
            out.append(Finding("condition_mismatch", sku, f"invoice says {', '.join(sorted(g['conds']))}, PO bought {pl['condition']}", qty * unit))
    return out
