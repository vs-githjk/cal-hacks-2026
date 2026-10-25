"""What a seller's listing page truly says, as the page Lane C's claim check reads (the SIM page shape used by
data/liar_pages: one <script type="application/json" id="listing"> block). Sellers that tell the truth, and the
Trickster's honest-looking bids, are both judged against pages built here, so a lie is a difference from the page and
nothing else. SIM pages: nothing here is a real store."""
from __future__ import annotations

import html
import json

LISTING_TAG = '<script type="application/json" id="listing">'


def render(facts: dict, title: str) -> str:
    """A SIM listing page whose facts are exactly `facts` (price, condition, warranty_months, return_policy, ...)."""
    body = json.dumps(facts, sort_keys=True)
    if "</" in body:
        raise ValueError("listing facts must not contain a closing tag")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)} (SIM listing)</title>{LISTING_TAG}{body}</script></head>"
            f"<body><p>SIM: simulated listing, not a real store.</p><h1>{html.escape(title)}</h1></body></html>")


def facts_for_line(line: dict, *, seller_id: str, price: float | None = None, condition: str | None = None,
                   warranty_months: int | None = None, return_days: int | None = None,
                   extra: dict | None = None) -> dict:
    """The page facts of one bid line. Defaults say the same thing the line says; a caller overrides only what the page
    truly differs on."""
    facts = {"seller_id": seller_id, "sku": line["sku_spec"], "origin": "SIM",
             "price": float(line["unit_price"] if price is None else price),
             "condition": condition or line.get("page_condition") or line.get("offered_condition"),
             "stock": "in stock"}
    if warranty_months is not None:
        facts["warranty_months"] = warranty_months
    if return_days is not None:
        facts["return_policy"] = f"{return_days}-day returns"
    facts.update(extra or {})
    return facts
