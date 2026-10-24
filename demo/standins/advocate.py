"""SIM stand-in for Lane A's quality advocate (origin/agents agents/advocate/checks.py; not merged here).

Same output shape: one AdvocateCard per bid (contracts/AdvocateCard.schema.json) plus `call_reason`, the closed
schema {rule_id, summary, source_url} the voice call may speak. Fit is decided by the REAL data.fit_checker, and
claims by the claim check (REAL when Lane C's c3 is on the branch, else the SIM stand-in); no model decides either.
Every veto carries a source URL. Not in this stand-in: the CPSC recall feed and price-history baseline (Lane A's
advocate has them; both need the network or recorded data this demo does not carry).
"""
from __future__ import annotations

from data.fit_checker import check_fit

REPO = "https://github.com/vs-githjk/cal-hacks-2026/blob/main"
FIT_SOURCE = f"{REPO}/data/fit_checker/README.md"
VETO_KINDS = {"fit", "claim_price", "condition", "claim_other"}
# Order the call speaks a veto in when a bid has several: fit first (code-decided), then the price claim.
VETO_ORDER = ("fit", "claim_price", "condition", "claim_other")
# Closed summaries, looked up by rule id. Each passes pay.callscript.clean_advocate_reason (tested).
CALL_SUMMARIES = {
    "advocate.condition": "The listing page shows a different condition than the seller claims",
    "advocate.claim_price": "The was price on the listing did not match the price history",
    "advocate.claim_other": "A claim on this bid did not match its listing page",
    "advocate.fit_unknown": "Fit could not be confirmed from the listing details",
    "fit.gpu_length": "The card is longer than your case allows",
    "fit.psu_wattage": "Your power supply is below what this card needs",
    "fit.gpu_connectors": "Your power supply lacks the connectors this card needs",
    "fit": "This part does not fit your build",
    "advocate.ok": "No problems found in the checks",
}
# Which part categories each fit rule compares: checks between two parts Joe already owns say nothing about this bid.
RULE_PARTS = {"fit.gpu_length": {"gpu", "case"}, "fit.gpu_connectors": {"gpu", "psu"}, "fit.psu_wattage": {"psu", "cpu", "gpu"},
              "fit.cpu_socket": {"cpu", "motherboard"}, "fit.ram_type": {"motherboard", "memory"}, "fit.ram_slots": {"motherboard", "memory"},
              "fit.cooler_socket": {"cpu", "cooler"}, "fit.cooler_height": {"cooler", "case"}, "fit.form_factor": {"motherboard", "case"},
              "fit.psu_form_factor": {"psu", "case"}, "fit.storage": {"motherboard", "storage"}}


def _warn(kind, text, url, dollars, rule_id, **extra):
    return {"kind": kind, "rule_id": rule_id, "text": text, "source_url": url, "dollar_impact": round(float(dollars), 2), **extra}


def fit_report(line: dict, owned_attrs: dict) -> dict:
    """REAL data.fit_checker on the offered card plus the parts Joe owns (never re-checking owned pairs)."""
    cards = [{"id": line["sku_spec"], "category": "gpu", "name": line["sku_spec"], "attrs": dict(line.get("attrs") or {}), "origin": "SIM", "source": line["listing_url"]}]
    cards += [{"id": f"owned-{cat}", "category": cat, "name": f"owned {cat}", "attrs": attrs, "origin": "SIM", "source": "ownership memory"}
              for cat, attrs in owned_attrs.items() if cat != "gpu"]
    fit = check_fit(cards)
    checks = [c for c in fit["checks"] if "gpu" in RULE_PARTS.get(c["rule_id"], {"gpu"})]
    fails = [c for c in checks if c["verdict"] == "fail"]
    unsure = [c for c in checks if c["verdict"] == "uncertain"]
    verdict = "fail" if fails else "uncertain" if unsure else "pass"
    return {"verdict": verdict, "rule_id": (fails or unsure or [{"rule_id": "fit.ok"}])[0]["rule_id"], "checks": checks,
            "notes": fit["notes"]}


def advise(need: dict, bid: dict, entry: dict, claims: list[dict], owned_attrs: dict) -> dict:
    """One AdvocateCard for a bid, judged on its best eligible line (`entry`, from market.rank_bids)."""
    line = bid["lines"][entry["line"]]
    url, landed = line["listing_url"], entry["landed"]
    warnings = []
    fit = fit_report(line, owned_attrs)
    if fit["verdict"] == "fail":
        bad = [c for c in fit["checks"] if c["verdict"] == "fail"]
        warnings.append(_warn("fit", "Does not fit: " + "; ".join(c["reason"] for c in bad) + f" (rule {bad[0]['rule_id']}).",
                              url, landed, bad[0]["rule_id"]))
    elif fit["verdict"] == "uncertain":
        warnings.append(_warn("fit_unknown", "Fit not confirmed: "
                              + "; ".join(c["reason"] for c in fit["checks"] if c["verdict"] == "uncertain") + ".", url, 0, "advocate.fit_unknown"))
    for c in claims:
        if c["check"] != "false":
            continue
        kind = {"price": "claim_price", "spec": "condition"}.get(c["kind"], "claim_other")
        rule = {"claim_price": "advocate.claim_price", "condition": "advocate.condition"}.get(kind, "advocate.claim_other")
        warnings.append(_warn(kind, f"\"{c['text']}\": {c['reason']}.", c["evidence_url"], landed, rule,
                              evidence_hash=c["evidence_hash"], checked_at=c["checked_at"]))
    warnings.sort(key=lambda w: VETO_ORDER.index(w["kind"]) if w["kind"] in VETO_ORDER else len(VETO_ORDER))
    kinds = {w["kind"] for w in warnings}
    rec = "veto" if kinds & VETO_KINDS else "caution" if kinds else "buy"
    card = {"need_id": need["id"], "bid_id": bid["id"], "warnings": warnings, "recommendation": rec, "wait_until": "",
            "call_reason": call_reason(warnings, url), "fit": {"verdict": fit["verdict"], "rule_id": fit["rule_id"], "checks": fit["checks"]},
            "line": entry["line"]}
    return card


def call_reason(warnings: list[dict], default_url: str) -> dict:
    """The only reason the voice call may speak: {rule_id, summary, source_url}, summary looked up by rule id."""
    vetoes = [w for w in warnings if w["kind"] in VETO_KINDS]
    if not vetoes:
        return {"rule_id": "advocate.ok", "summary": CALL_SUMMARIES["advocate.ok"], "source_url": default_url}
    w = min(vetoes, key=lambda x: VETO_ORDER.index(x["kind"]))
    rid = w["rule_id"] if w["rule_id"] in CALL_SUMMARIES else ("fit" if w["kind"] == "fit" else "advocate.claim_other")
    return {"rule_id": rid, "summary": CALL_SUMMARIES[rid], "source_url": w["source_url"]}
