"""Seller agent-readiness for any listing URL (Lane C, issue #271; the readiness Actor). Builds on data.seller_report (#171).

    check_listing(url, fetch=None, now=None) -> {"url", "status", "summary", "findings", "facts_read", "checked_at", "origin", ...}
    check_page(url, html, now=None)         -> the same, for a page already fetched

status: "blocks" (an agent would skip the listing), "warns" (an agent cannot confirm something), "ready" (no findings), or
"unreadable" (the page could not be fetched or parsed, or the store showed a bot check instead of the listing; nothing is
known). Findings are {rule_id, severity, what_an_agent_sees, source_url, fix}, worded as what a shopping agent sees, never
what the seller did.

What is read: the page's schema.org Product JSON-LD (data.claim_check.page_facts and ld_product: the Product whose @id or
url is the page, else the first with offers), with price, name and availability re-checked strictly here. Then:
  page checks   no Product structured data (blocks), no price that is a finite number of at least 0.01 or a plain numeric
                string in offers.price, offers.priceSpecification.price or an AggregateOffer's lowPrice (blocks), a
                lowPrice that is not one price (warns), a price with no three-letter priceCurrency (warns), no name as text (warns), no condition
                (warns), no return policy (warns), no model identifier (mpn, gtin or sku) an agent can match to maker specs
                (warns), availability not a schema.org value (warns);
  seller_report title claims against the page's own data (blocks), and shipping and stock stated (warns).
The seller_report GPU fit rows are not run: they warn when OUR maker table lacks a model, which is not the seller's to fix.
The dated retail price band is not used here: it is a 24 h window over our own captures, so it would be stale for a run on a
later day. Each page is fetched once, live, with data.claim_check.fetch.guarded_get (public addresses only, 2 MB cap).
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from data.claim_check import ld_offer as _offer, ld_product, page_facts
from data.seller_report import _finding, findings_for

PLAIN_PRICE = re.compile(r"[0-9]+(\.[0-9]+)?")
MIN_PRICE = 0.01  # one cent: a price below it (1e-8, "0.001") is not a price a shopper pays (#334)
CURRENCY = re.compile(r"[A-Za-z]{3}")  # an ISO 4217 code such as USD or CAD
# schema.org ItemAvailability values (https://schema.org/ItemAvailability), by their lower-case name
ITEM_AVAILABILITY = {v.lower(): v for v in ("InStock", "InStoreOnly", "OnlineOnly", "LimitedAvailability", "OutOfStock", "SoldOut",
                                            "Discontinued", "PreOrder", "PreSale", "BackOrder", "MadeToOrder", "Reserved")}


def _plain_price(v):
    """A price an agent can read without guessing: a finite number of at least MIN_PRICE, or a plain numeric string ("299.99"), else None.
    "1.749,99", "1,749.99", "$5", [1], {"a": 1}, NaN, 1e400, 0, -5 (#317) and anything below MIN_PRICE (#334) are not."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        if not PLAIN_PRICE.fullmatch(v.strip()):
            return None
        v = v.strip()
    elif not isinstance(v, (int, float)):
        return None
    try:
        v = float(v)
    except (OverflowError, ValueError):
        return None
    return v if math.isfinite(v) and v >= MIN_PRICE else None


def _currency(v):
    """A three-letter currency code ("USD"), upper-cased, else None (missing, "XYZ!!", "$", 840)."""
    return v.strip().upper() if isinstance(v, str) and CURRENCY.fullmatch(v.strip()) else None


def _offer_price(offer: dict) -> tuple:
    """(price, currency, source, high) as an agent reads the offer (#353): offers.price with offers.priceCurrency; else the first
    offers.priceSpecification (one or a list) with a readable price, with its own priceCurrency (else the offer's); else an
    AggregateOffer's lowPrice, the lowest price on offer, with high its highPrice. source names the field the price came from.
    Every price passes _plain_price, so "$5", 0 or "1,749.99" in any of these places is still no price."""
    cur = _currency(offer.get("priceCurrency"))
    price = _plain_price(offer.get("price"))
    if price is not None:
        return price, cur, "price", None
    specs = offer.get("priceSpecification")
    for spec in specs if isinstance(specs, list) else [specs]:
        if isinstance(spec, dict) and _plain_price(spec.get("price")) is not None:
            return _plain_price(spec.get("price")), _currency(spec.get("priceCurrency")) or cur, "priceSpecification.price", None
    low = _plain_price(offer.get("lowPrice"))
    if low is not None:
        return low, cur, "lowPrice", _plain_price(offer.get("highPrice"))
    return None, cur, None, None


# A 200 page that is a bot check, not the listing (#353). Strong markers are the challenge pages' own scripts and ids; weak
# ones (plain words a real page can also say) count only in the <title> or on a short page, as challenge pages are short.
BOT_WALL_STRONG = (("cloudflare", ("cf-browser-verification", "challenge-platform", "cf_chl_", "cf-challenge", "attention required! | cloudflare")),
                   ("akamai", ("errors.edgesuite.net",)),
                   ("perimeterx", ("px-captcha", "_pxcaptcha", "perimeterx", "/px/client")),
                   ("datadome", ("captcha-delivery.com", "geo.captcha-delivery", "datadome")),
                   ("incapsula", ("_incapsula_resource", "incapsula incident id")))
BOT_WALL_WEAK = ("just a moment...", "access denied", "captcha", "are you a robot", "are you a human", "verify you are human",
                 "confirm you are a human", "press & hold", "press &amp; hold", "unusual traffic", "request blocked", "pardon our interruption")
SHORT_PAGE = 20000  # characters: a challenge page is a few KB; a store's real product page is far longer


def _bot_wall(html: str) -> str | None:
    """Which bot check the page is ("cloudflare", "akamai", "perimeterx", "datadome", "incapsula", "a captcha"), else None.
    Only asked of a page with no structured data: a real listing that loads reCAPTCHA or says "access denied" is still read."""
    low = html.lower()
    for name, marks in BOT_WALL_STRONG:
        if any(m in low for m in marks):
            return name
    title = re.search(r"<title[^>]*>([^<]{0,300})", low)
    where = (title.group(1) if title else "") + (low if len(low) <= SHORT_PAGE else "")
    hit = next((m for m in BOT_WALL_WEAK if m in where), None)
    if hit is None:
        return None
    return "akamai" if hit == "access denied" and "reference #" in low else "a captcha" if "captcha" in hit else "a bot check"


def _availability(v):
    """A schema.org ItemAvailability name ("InStock") from "https://schema.org/InStock", "schema:InStock" or "InStock", else None."""
    if not isinstance(v, str):
        return None
    name = re.sub(r"^(https?://schema\.org/|schema:)", "", v.strip(), flags=re.I)
    return ITEM_AVAILABILITY.get(name.lower())


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


def _page_findings(url: str, facts: dict, how: str, product: dict | None = None, offer: dict | None = None) -> list[dict]:
    if how == "no structured data":
        return [_finding("listing.no_structured_data", "blocks", "The page has no schema.org Product data, so an agent cannot read "
                         "the price, stock or condition without guessing from the page text.", url,
                         "Add a schema.org Product block (JSON-LD) with offers: price, priceCurrency, availability and itemCondition.")]
    out = []
    if not facts.get("title"):
        out.append(_finding("listing.name_unreadable", "warns", "The Product data has no name an agent can read as text, so it "
                            "cannot match the listing to what a shopper asked for.", url, "Put the product name as plain text in name."))
    if facts.get("price") is None:
        out.append(_finding("listing.price_unreadable", "blocks", "The Product data has no price an agent can read.", url,
                            "Put the price as a number in offers.price, with offers.priceCurrency."))
    else:
        if product is not None and facts.get("currency") is None:
            out.append(_finding("listing.currency_unknown", "warns", "The Product data has no currency an agent can read, so it cannot "
                                "tell which currency the price is in or compare it with other sellers.", url,
                                "Set offers.priceCurrency to a three-letter ISO 4217 code, for example USD or CAD."))
        if facts.get("price_from") == "lowPrice" and facts.get("price_high") != facts.get("price"):
            out.append(_finding("listing.price_range", "warns", "The Product data gives a price range (AggregateOffer), so an agent "
                                "reads the lowPrice as the price and cannot tell what this listing costs a shopper.", url,
                                "Give this listing's own price in offers.price (an Offer), or set lowPrice and highPrice to the same value."))
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


def _unreadable(url: str, at: str, why: str, error: str) -> dict:
    return {"url": url, "status": "unreadable", "summary": f"UNREADABLE: {why} ({error})", "findings": [], "facts_read": {},
            "read_from": None, "checked_at": at, "origin": "LIVE", "error": error}


def check_page(url: str, html: str, now: datetime | None = None) -> dict:
    """Any parse failure (bad listing JSON, JSON nested too deeply, anything unexpected) is "unreadable", never "ready"."""
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    try:
        return _check_page(url, html, at)
    except Exception as e:  # RecursionError included: we do not know what the page says
        return _unreadable(url, at, "the page could not be parsed", type(e).__name__)


def _check_page(url: str, html: str, at: str) -> dict:
    facts, how = page_facts(html, url)
    if how == "no structured data":
        wall = _bot_wall(html)
        if wall:  # we were shown a challenge, not the listing: nothing is known about the page, so it is free (#353)
            return _unreadable(url, at, f"the store showed a bot check ({wall}) instead of the listing, so its page was not read",
                               "bot_wall")
    product = ld_product(html, url) if how.startswith("page JSON-LD") else None
    offer = _offer(product) if product else {}
    if how != "no structured data":  # read the raw values ourselves: the claim check is lenient where an agent is not
        facts = dict(facts)
        if product is not None:
            facts["price"], facts["currency"], facts["price_from"], facts["price_high"] = _offer_price(offer)
        else:
            facts["price"] = _plain_price(facts.get("price"))
        title = product.get("name") if product is not None else facts.get("title")
        facts["title"] = title.strip() if isinstance(title, str) and title.strip() else None
        if product is not None:
            facts["stock"] = _availability(offer.get("availability"))
    findings = _page_findings(url, facts, how, product, offer)
    if how != "no structured data":
        findings += findings_for(_card(url, facts, offer, at), None, [])
    findings = list({f["rule_id"]: f for f in findings}.values())  # one finding per rule
    status = "blocks" if any(f["severity"] == "blocks" for f in findings) else "warns" if findings else "ready"
    read = {k: facts.get(k) for k in ("title", "price", "condition", "stock", "return_policy", "warranty_months") if facts.get(k) is not None}
    if facts.get("price") is not None:
        for k in ("currency", "price_high"):  # price_high: the price is an AggregateOffer's lowPrice, this its highPrice
            if facts.get(k) is not None:
                read[k] = facts[k]
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
        return _unreadable(url, at, "the page could not be fetched", type(e).__name__)
    return check_page(url, html, now=now)
