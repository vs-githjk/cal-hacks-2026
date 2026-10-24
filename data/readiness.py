"""Seller agent-readiness for any listing URL (Lane C, issue #271; the readiness Actor). Builds on data.seller_report (#171).

    check_listing(url, fetch=None, now=None) -> {"url", "status", "summary", "findings", "facts_read", "checked_at", "origin", ...}
    check_page(url, html, now=None)         -> the same, for a page already fetched

status: "blocks" (an agent would skip the listing), "warns" (an agent cannot confirm something), "ready" (no findings), or
"unreadable" (the page could not be fetched; nothing is known). Findings are {rule_id, severity, what_an_agent_sees,
source_url, fix}, worded as what a shopping agent sees, never what the seller did.

What is read: the page's schema.org Product JSON-LD (data.claim_check.page_facts plus shipping and currency here). Then:
  page checks   no Product structured data (blocks), no price (blocks), no condition (warns), no return policy (warns),
                no model identifier (mpn, gtin or sku) an agent can match to maker specs (warns);
  seller_report title claims against the page's own data (blocks), and shipping and stock stated (warns).
The seller_report GPU fit rows are not run: they warn when OUR maker table lacks a model, which is not the seller's to fix.
The dated retail price band is not used here: it is a 24 h window over our own captures, so it would be stale for a run on a
later day. Each page is fetched once, live, with data.claim_check.fetch.guarded_get (public addresses only, 2 MB cap).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from data.claim_check import page_facts
from data.seller_report import _finding, findings_for

def _ld_product(html: str) -> dict:
    """The first schema.org Product node, or {}."""
    for block in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html, re.S | re.I):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if isinstance(node, dict) and "Product" in str(node.get("@type")):
                return node
    return {}


def _offer(product: dict) -> dict:
    offer = product.get("offers") or {}
    offer = offer[0] if isinstance(offer, list) and offer else offer
    return offer if isinstance(offer, dict) else {}


IDS = ("mpn", "gtin", "gtin8", "gtin12", "gtin13", "gtin14", "sku")


def _shipping(offer: dict):
    """A shipping cost an agent can price: offers.shippingDetails.shippingRate.value as a number, else None (never 0)."""
    details = offer.get("shippingDetails")
    for d in details if isinstance(details, list) else [details]:
        rate = (d or {}).get("shippingRate") if isinstance(d, dict) else None
        rate = rate[0] if isinstance(rate, list) and rate else rate
        value = rate.get("value") if isinstance(rate, dict) else None
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v >= 0 and v == v and v != float("inf"):
            return v
    return None


def _card(url: str, facts: dict, offer: dict, at: str) -> dict:
    """The listing as the card seller_report.findings_for reads (no category or chipset, so its GPU fit rows never run)."""
    stock = facts.get("stock")
    return {"id": f"live:{url}", "name": str(facts.get("title") or ""), "price": facts.get("price"),
            "condition": facts.get("condition") or "unknown", "category": None, "attrs": {}, "origin": "LIVE", "source": url, "snapshot_date": at,
            "listing": {"url": url, "price": facts.get("price"), "stock": re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stock).lower() if isinstance(stock, str) else stock,
                        "shipping": _shipping(offer)}}


def _page_findings(url: str, facts: dict, how: str, product: dict | None = None) -> list[dict]:
    if how == "no structured data":
        return [_finding("listing.no_structured_data", "blocks", "The page has no schema.org Product data, so an agent cannot read "
                         "the price, stock or condition without guessing from the page text.", url,
                         "Add a schema.org Product block (JSON-LD) with offers: price, priceCurrency, availability and itemCondition.")]
    out = []
    if facts.get("price") is None:
        out.append(_finding("listing.price_unreadable", "blocks", "The Product data has no price an agent can read.", url,
                            "Put the price as a number in offers.price, with offers.priceCurrency."))
    if not facts.get("condition"):
        out.append(_finding("listing.condition_unknown", "warns", "No item condition is stated, so an agent cannot tell new from "
                            "used or refurbished.", url, "Set offers.itemCondition, for example https://schema.org/NewCondition."))
    if not facts.get("return_policy"):
        out.append(_finding("listing.returns_unknown", "warns", "No return policy is stated in the Product data, so an agent cannot "
                            "compare returns across sellers.", url, "Add offers.hasMerchantReturnPolicy with the return window in days."))
    if product is not None and not any(str(product.get(k) or "").strip() for k in IDS):
        out.append(_finding("listing.model_unknown", "warns", "The Product data has no mpn, gtin or sku, so an agent cannot match the "
                            "exact model to maker specs such as size and power.", url,
                            "Add the maker part number as mpn and the barcode as gtin13 (or gtin12)."))
    return out


def _summary(status: str, findings: list[dict]) -> str:
    if status == "ready":
        return "READY: an agent can read price, condition, stock, shipping and returns, and no title claim contradicts the page"
    n_b = sum(f["severity"] == "blocks" for f in findings)
    n_w = len(findings) - n_b
    lead = next((f for f in findings if f["severity"] == "blocks"), findings[0])
    return f"{status.upper()}: {n_b} block(s), {n_w} warning(s); first: {lead['rule_id']}"


def check_page(url: str, html: str, now: datetime | None = None) -> dict:
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    try:
        facts, how = page_facts(html)
    except (ValueError, TypeError, AttributeError):
        facts, how = {}, "no structured data"
    product = _ld_product(html) if how == "page JSON-LD" else None
    offer = _offer(product) if product else {}
    findings = _page_findings(url, facts, how, product)
    if how != "no structured data":
        findings += findings_for(_card(url, facts, offer, at), None, [])
    findings = list({f["rule_id"]: f for f in findings}.values())  # one finding per rule
    status = "blocks" if any(f["severity"] == "blocks" for f in findings) else "warns" if findings else "ready"
    read = {k: facts.get(k) for k in ("title", "price", "condition", "stock", "return_policy", "warranty_months") if facts.get(k) is not None}
    if offer.get("priceCurrency"):
        read["currency"] = str(offer["priceCurrency"])
    shipping = _shipping(offer)
    if shipping is not None:
        read["shipping"] = shipping
    return {"url": url, "status": status, "summary": _summary(status, findings), "findings": findings, "facts_read": read,
            "read_from": how, "checked_at": at, "origin": "LIVE"}


def check_listing(url: str, fetch=None, now: datetime | None = None) -> dict:
    """Fetch the page once and check it. Any fetch failure is "unreadable" (nothing is known), never "ready"."""
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    url = str(url or "").strip()
    if not re.match(r"https?://", url, re.I):
        return {"url": url, "status": "unreadable", "summary": "UNREADABLE: not an http(s) URL", "findings": [], "facts_read": {},
                "read_from": None, "checked_at": at, "origin": "LIVE"}
    try:
        if fetch is None:
            from data.claim_check.fetch import guarded_get as fetch
        body = fetch(url)
        html = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
    except Exception as e:  # blocked, down, too large, not public: we do not know, so never "ready"
        return {"url": url, "status": "unreadable", "summary": f"UNREADABLE: the page could not be fetched ({type(e).__name__})",
                "findings": [], "facts_read": {}, "read_from": None, "checked_at": at, "origin": "LIVE", "error": type(e).__name__}
    return check_page(url, html, now=now)
