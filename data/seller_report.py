"""Seller agent-readiness report (Lane C, issue #171): why a buyer agent would skip or doubt each of a seller's listings.

    report(listings, as_of=None, cards=None, observations=None) -> {"seller", "as_of", "findings": [...], ...}
    python3 -m data.seller_report ebay_live:<item id>      # writes data/reports/<seller>-<date>.md

`listings` is a list of listing URLs, or a mirror seller id: "<store>" or "<store>:<item id>" (eBay seller handles are not
captured, so an eBay seller is named by item id). Every finding is {rule_id, severity, what_an_agent_sees, source_url, fix};
severity is "blocks" or "warns". The checks are the ones the agents already run: the fit checker's maker length and power
rows, the claim check (real_scan), the dated baseline of retail asks, and normalize.landed for stock and shipping.
A finding without a source_url is dropped. Wording says what an agent sees, never what the seller did. MIRROR data only.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPORTS = Path(__file__).resolve().parent / "reports"
SEVERITIES = ("blocks", "warns")
OFFER = "Offered free to a seller in exchange for a signed commitment; no payment taken."


def _url(card: dict) -> str:
    return (card.get("listing") or {}).get("url") or card.get("source") or ""


def _select(cards: list[dict], listings) -> tuple[str, list[dict]]:
    if isinstance(listings, str):
        store, _, item = listings.partition(":")
        picked = [c for c in cards if c.get("id", "").split(":")[0] == store and (not item or item in re.split(r"[/?&=#]", _url(c)))]
        return listings, picked
    wanted = set(listings)
    return "listings", [c for c in cards if _url(c) in wanted]


PAID_SHIPPING = re.compile(r"\s*\+?\s*\$\s*(\d[\d,]*(?:\.\d+)?)\s+(?:delivery|shipping)\s*\.?\s*", re.I)


def shipping_stated(listing: dict, price) -> bool:
    """Shipping an agent can price: what normalize.landed reads, or a plain "+$N delivery" / "+$N shipping" (a stated price
    that landed() does not parse yet; read here so the report does not count our parser's gap against the listing)."""
    from data.mirror.normalize import landed
    if landed(listing, price)["shipping_captured"]:
        return True
    ship = listing.get("shipping")
    return isinstance(ship, str) and bool(PAID_SHIPPING.fullmatch(ship))


def _finding(rule_id, severity, sees, source_url, fix):
    assert severity in SEVERITIES
    return {"rule_id": rule_id, "severity": severity, "what_an_agent_sees": sees, "source_url": source_url or "", "fix": fix}


def findings_for(card: dict, band: dict | None, observations: list[dict]) -> list[dict]:
    from data.claim_check.real_scan import check_card
    from data.fit_checker.gpu_lengths import listing_length
    from data.fit_checker.power import check_power
    from data.mirror.normalize import landed

    url, title = _url(card), card.get("name") or ""
    out = []
    if card.get("category") == "gpu" or (card.get("attrs") or {}).get("chipset"):
        if listing_length(url, title)["length_mm"] is None:
            out.append(_finding("fit.length_unknown", "warns", "The title names no card model we can match to a maker length, so "
                                "an agent cannot confirm the card fits the buyer's case and marks fit as not confirmed.", url,
                                "Put the maker's model name or part number in the title."))
        p = check_power(title, {})
        if p["source"] is None or "chipset reference" in (p["source"] or ""):
            out.append(_finding("fit.power_unknown", "warns", "No maker power spec matches this title, so an agent falls back to a "
                                "chipset-level PSU guess or cannot check power at all.", url,
                                "Name the exact model so its maker PSU and connector spec can be matched."))
    for r in check_card(card, observations):
        if r["result"] == "false":
            out.append(_finding(f"claim.{r['rule_id']}", "blocks", f"The title claim does not match the listing's own data: {r['reason']}.",
                                url, "Make the title and the item specifics agree."))
    price = card.get("price")
    comparable = (card.get("attrs") or {}).get("chipset") == "RTX 5070 Ti" and card.get("condition") in ("new", "unknown")
    if band and comparable and price is not None and band.get("max") is not None and price > band["max"]:
        out.append(_finding("price.above_band", "warns", f"${price:,.2f} is above every in-stock retail ask we hold for a new card "
                            f"(${band['min']:,.2f} to ${band['max']:,.2f}, n = {band['n']}, {band['dates']}); an agent warns on a "
                            "price above its baseline.", band["max_url"], "Check the price against the dated retail asks."))
    lt = landed(card.get("listing") or {}, price)
    if not shipping_stated(card.get("listing") or {}, price):
        out.append(_finding("listing.shipping_unknown", "warns", "No shipping cost is stated in a form an agent can read, so it cannot "
                            "compute a landed price.", url, "State the shipping cost as a number, or 'Free shipping' with no condition."))
    if lt["availability"] is None:
        out.append(_finding("listing.stock_unknown", "warns", "Stock is not stated, so an agent cannot tell whether the item is "
                            "available now.", url, "State stock (in stock, or the number available)."))
    return [f for f in out if f["source_url"]]  # nothing without a source


def _band(observations: list[dict], as_of: str) -> dict | None:
    from data.baselines import baseline
    b = baseline("rtx 5070 ti", as_of, rows=observations)
    rows = b.get("rows") or []
    if not rows:
        return None
    lo, hi = min(rows, key=lambda r: r["price"]), max(rows, key=lambda r: r["price"])
    return {"min": lo["price"], "max": hi["price"], "min_url": lo.get("url"), "max_url": hi.get("url"), "n": len(rows),
            "dates": f"{b['from'][:10]} to {b['to'][:10]}"}


def report(listings, as_of: str | None = None, cards: list[dict] | None = None, observations: list[dict] | None = None) -> dict:
    if cards is None:
        from data.mirror.price_spread import latest_by_url, load
        cards = [c for cs in load().values() for c in latest_by_url(cs)]
    if observations is None:
        from data.baselines import observations as load_obs
        observations = load_obs()
    as_of = as_of or max((r["observed_at"] for r in observations), default=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    seller, picked = _select(cards, listings)
    band = _band(observations, as_of)
    per = [{"url": _url(c), "title": c.get("name"), "snapshot_date": c.get("snapshot_date"), "price": c.get("price"),
            "findings": findings_for(c, band, observations)} for c in picked]
    return {"seller": seller, "as_of": as_of, "origin": "MIRROR", "listings": per, "band": band,
            "findings": [f for p in per for f in p["findings"]]}


def markdown(rep: dict) -> str:
    lines = [f"# Agent-readiness report: {rep['seller']} (MIRROR)", "",
             f"Checked {rep['as_of'][:16]} UTC from our dated captures, not a live visit. What was checked per listing: maker length and "
             "power spec match (fit checker), title claims against the listing's own data (claim check), price against the dated band "
             "of in-stock retail asks, and whether shipping and stock are stated. Findings marked 'warns' are uncertain: an agent "
             "cannot confirm something, not that it is wrong. 'blocks' means an agent would skip the listing.", "",
             OFFER, ""]
    if not rep["listings"]:
        lines.append("No captured listings matched this seller id.")
    for p in rep["listings"]:
        lines += [f"## {p['title']}", f"{p['url']} (captured {str(p['snapshot_date'])[:16]} UTC, ${p['price']:,.2f})", ""]
        if not p["findings"]:
            lines += ["No findings: an agent can read fit, claims, price, shipping and stock for this listing.", ""]
        for f in p["findings"]:
            lines += [f"- **{f['severity']}** `{f['rule_id']}`: {f['what_an_agent_sees']} Fix: {f['fix']} Source: {f['source_url']}"]
        lines.append("")
    return "\n".join(lines)


def write(rep: dict) -> Path:
    REPORTS.mkdir(exist_ok=True)
    name = rep["seller"].replace(":", "-").replace("/", "-")
    path = REPORTS / f"{name}-{rep['as_of'][:10]}.md"
    path.write_text(markdown(rep))
    return path


if __name__ == "__main__":
    print(write(report(sys.argv[1] if len(sys.argv) > 1 else "ebay_live")))
