"""What a seller's listing page truly says, as the page Lane C's claim check reads: a schema.org Product/Offer in a
<script type="application/ld+json"> block, the way a real store states price, condition, stock, warranty and returns. The
claim check reads that block on any host; it ignores the SIM-only <script id="listing"> block off our own demo pages (RT-20),
so these pages never use it. Sellers that tell the truth, and the Trickster's honest-looking bids, are both judged against
pages built here, so a lie is a difference from the page and nothing else. SIM pages: nothing here is a real store."""
from __future__ import annotations

import html
import json
import re

SCHEMA = "https://schema.org/"
# The claim check's LD_CONDITION reads these back as new / used / refurbished / used. schema.org has no open-box term, so an
# open-box line is UsedCondition on a page whose name says "open-box" (the claim check reads that pair as open-box).
CONDITION_URI = {"new": "NewCondition", "used": "UsedCondition", "refurbished": "RefurbishedCondition",
                 "open-box": "UsedCondition", "damaged": "DamagedCondition"}
AVAILABILITY_URI = {"in stock": "InStock", "out of stock": "OutOfStock", "limited": "LimitedAvailability",
                    "preorder": "PreOrder", "backorder": "BackOrder"}


def _return_policy(text: str) -> dict | None:
    if "not permitted" in text:
        return {"@type": "MerchantReturnPolicy", "returnPolicyCategory": SCHEMA + "MerchantReturnNotPermitted"}
    m = re.search(r"(\d+)[- ]day", text)
    return {"@type": "MerchantReturnPolicy", "returnPolicyCategory": SCHEMA + "MerchantReturnFiniteReturnWindow",
            "merchantReturnDays": int(m.group(1))} if m else None


def render(facts: dict, title: str) -> str:
    """A SIM listing page whose facts are exactly `facts` (price, condition, warranty_months, return_policy, stock, ...)."""
    cond = str(facts.get("condition") or "")
    name = title if cond != "open-box" or re.search(r"open[- ]box", title, re.I) else f"{title} (open-box)"
    offer: dict = {"@type": "Offer", "price": facts["price"], "priceCurrency": "USD"}
    if cond in CONDITION_URI:
        offer["itemCondition"] = SCHEMA + CONDITION_URI[cond]
    stock = str(facts.get("stock") or "").lower()
    if stock in AVAILABILITY_URI:
        offer["availability"] = SCHEMA + AVAILABILITY_URI[stock]
    policy = _return_policy(str(facts.get("return_policy") or ""))
    if policy:
        offer["hasMerchantReturnPolicy"] = policy
    product: dict = {"@context": "https://schema.org", "@type": "Product", "name": name, "sku": facts.get("sku"), "offers": offer}
    if facts.get("warranty_months") is not None:
        product["warranty"] = {"@type": "WarrantyPromise", "durationOfWarranty": {
            "@type": "QuantitativeValue", "value": int(facts["warranty_months"]), "unitCode": "MON"}}
    notes = [str(facts[k]) for k in ("condition_note", "fees") if facts.get(k)]
    if notes:
        product["description"] = ". ".join(notes)
    body = json.dumps(product, sort_keys=True).replace("<", "\\u003c")   # JSON still parses; the page cannot close its own script
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)} (SIM listing)</title><script type=\"application/ld+json\">{body}</script></head>"
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
