"""SIM stand-in for Lane C's claim check (origin/lane-c-data data/claim_check, task c3), used only while
`data.claim_check` on this branch is the always-unverified mock. Same I/O and the same rules for the three
claim fields the demo uses (condition, price, was_price, return_days); other fields answer "could not verify".

check_claim(claim, fetch=None, history=None) -> {"result": verified|unverified|false, "evidence_url",
"checked_at", "method", "evidence_hash", "reason"}. claim["field"] and claim["value"] are given directly.
A page that cannot be read is "unverified", never "false". Wording stays neutral.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse


def _facts(html):
    m = re.search(r'<script type="application/json" id="listing">(.*?)</script>', html, re.S)
    return (json.loads(m.group(1)), "page listing JSON") if m else ({}, "no structured data")


def _judge(field, value, facts, at, series):
    if field == "condition":
        page = facts.get("condition")
        if not page:
            return "unverified", "could not verify: the page states no condition"
        if page == value:
            return "verified", f"the page shows {page}"
        return "false", f"claim says {value}; differs from the listing at {at}: the page shows {page}"
    if field == "price":
        page = facts.get("price")
        if page is None:
            return "unverified", "could not verify: the page states no price"
        if abs(float(page) - float(value)) < 0.01:
            return "verified", f"the page shows ${float(page):,.2f}"
        return "false", f"claim says ${float(value):,.2f}; differs from the listing at {at}: the page shows ${float(page):,.2f}"
    if field == "was_price":
        if not series:
            return "unverified", "could not verify: no dated price history for this item"
        top = max(series, key=lambda p: p["price"])
        span = f"{series[0]['date']} to {series[-1]['date']}"
        if value <= top["price"] + 0.01:
            return "verified", f"price history shows ${top['price']:,.2f} on {top['date']}"
        return "false", f"the price claim did not match the price history: highest recorded ${top['price']:,.2f} ({span})"
    if field == "return_days":
        m = re.search(r"(\d+)[- ]day", str(facts.get("return_policy") or ""))
        if not m:
            return "unverified", "could not verify: no return window on the page"
        days = int(m.group(1))
        if days == value:
            return "verified", f"the page shows {days}-day returns"
        return "false", f"claim says {value}-day returns; differs from the listing at {at}: the page shows {days}-day"
    return "unverified", f"could not verify: {field} claims are not checked yet"


def check_claim(claim, fetch=None, history=None):
    url = claim.get("evidence_url") or ""
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = {"result": "unverified", "evidence_url": url, "checked_at": at, "evidence_hash": ""}
    unverified = lambda why: {**out, "method": f"could not verify: {why}", "reason": "could not verify"}
    field, value = claim.get("field"), claim.get("value")
    if field is None:
        return unverified("claim field not given")
    if urlparse(url).scheme not in ("http", "https") or fetch is None:
        return unverified("only http and https pages are checked")
    try:
        body = fetch(url)
    except Exception as e:  # unreachable or blocked page: never "false"
        return unverified(f"page fetch failed ({type(e).__name__})")
    out["evidence_hash"] = hashlib.sha256(body).hexdigest()
    try:
        facts, source = _facts(body.decode("utf-8", "replace"))
        series = history
        if field == "was_price" and series is None and facts.get("origin") == "SIM" and facts.get("sku"):
            series = json.loads(fetch(urljoin(url, "price_history.json")))["series"].get(facts["sku"])
        result, reason = _judge(field, value, facts, at, series)
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as e:
        return unverified(f"page could not be parsed ({type(e).__name__})")
    method = f"fetched page, {source}, {field} rule" if result != "unverified" else f"could not verify: {source}, {field} rule"
    return {**out, "result": result, "method": method, "reason": reason}
