"""Claim check (Lane C, c3). Checks one seller claim against the live page.

check_claim(claim, fetch=None, history=None) ->
    {"result": "verified"|"unverified"|"false", "evidence_url", "checked_at" (ISO-8601 UTC), "method",
     "evidence_hash" (sha256 of the page bytes), "reason"}
Input is a Claim (contracts/Claim.schema.json); `result` maps to Claim.check. The page is claim["evidence_url"].
Optional claim["field"] and claim["value"] skip text parsing. Page facts come from our SIM pages'
<script id="listing"> JSON, else schema.org JSON-LD. A page we cannot read is "unverified", never "false".
Wording is neutral: "differs from the listing at time T", "did not match the price history", "could not verify".
"""
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urljoin

from data.fit_checker.tables import MICROARCH_SOCKET

UA = "TechBazaar-claim-check/0.1 (hackathon research)"
PATTERNS = [  # (field, regex, value from match); first match wins
    ("was_price", r"\bwas\s*\$?\s*([\d,]+(?:\.\d+)?)", lambda m: _num(m.group(1))),
    ("socket", r"\bsocket\s*(AM\d|LGA\s?\d{3,4})", lambda m: m.group(1).replace(" ", "").upper()),
    ("return_days", r"(\d+)[- ]day returns?", lambda m: int(m.group(1))),
    ("stock", r"\bout of stock\b", lambda m: False),
    ("stock", r"\bin stock\b", lambda m: True),
    ("condition", r"\bopen[- ]box\b", lambda m: "open-box"),
    ("condition", r"\brefurb", lambda m: "refurbished"),
    ("condition", r"\b(used|pre-owned)\b", lambda m: "used"),
    ("condition", r"\bnew\b", lambda m: "new"),
    ("price", r"\$\s?([\d,]+(?:\.\d+)?)", lambda m: _num(m.group(1))),
]
LD_CONDITION = {"NewCondition": "new", "UsedCondition": "used", "RefurbishedCondition": "refurbished", "DamagedCondition": "used"}


def _num(s):
    return float(str(s).replace(",", ""))


def parse_claim(claim):
    if claim.get("field"):
        return claim["field"], claim.get("value")
    text = claim.get("text") or ""
    for field, rx, val in PATTERNS:
        m = re.search(rx, text, re.I)
        if m:
            return field, val(m)
    return None, None


def default_fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def page_facts(html):
    m = re.search(r'<script type="application/json" id="listing">(.*?)</script>', html, re.S)
    if m:
        return json.loads(m.group(1)), "page listing JSON"
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in data if isinstance(data, list) else data.get("@graph", [data]):
            if not isinstance(node, dict) or "Product" not in str(node.get("@type")):
                continue
            offer = node.get("offers") or {}
            offer = offer[0] if isinstance(offer, list) else offer
            cond = str(offer.get("itemCondition") or "").rsplit("/", 1)[-1]
            avail = str(offer.get("availability") or "").rsplit("/", 1)[-1]
            facts = {"title": node.get("name"), "price": _num(offer["price"]) if offer.get("price") else None,
                     "condition": LD_CONDITION.get(cond), "stock": avail or None}
            return {k: v for k, v in facts.items() if v is not None}, "page JSON-LD"
    return {}, "no structured data"


def in_stock(v):
    if isinstance(v, bool):
        return v
    s = str(v).lower()
    if "out of stock" in s or "outofstock" in s or s.startswith("0 "):
        return False
    if "in stock" in s or "instock" in s or re.match(r"\d+ (units|in stock|remaining)", s):
        return True
    return None


def _history(url, facts, fetch, history):
    if history is not None:
        return history
    if facts.get("origin") == "SIM" and facts.get("sku"):  # our planted pages publish their SIM price history
        try:
            return json.loads(fetch(urljoin(url, "price_history.json")))["series"].get(facts["sku"])
        except (OSError, ValueError, KeyError):
            return None
    return None


def judge(field, value, facts, at, series):
    """-> (result, reason)"""
    if field == "condition":
        page = facts.get("condition")
        if not page:
            return "unverified", "could not verify: the page states no condition"
        return ("verified", f"the page shows {page}") if page == value else \
            ("false", f"claim says {value}; differs from the listing at {at}: the page shows {page}")
    if field == "price":
        page = facts.get("price")
        if page is None:
            return "unverified", "could not verify: the page states no price"
        return ("verified", f"the page shows ${page:,.2f}") if abs(page - value) < 0.01 else \
            ("false", f"claim says ${value:,.2f}; differs from the listing at {at}: the page shows ${page:,.2f}")
    if field == "was_price":
        if not series:
            return "unverified", "could not verify: no dated price history for this item"
        top = max(series, key=lambda p: p["price"])
        span = f"{series[0]['date']} to {series[-1]['date']}"
        if value <= top["price"] + 0.01:
            return "verified", f"price history shows ${top['price']:,.2f} on {top['date']}"
        return "false", f"the price claim did not match the price history: highest recorded ${top['price']:,.2f} ({span})"
    if field == "socket":
        specs = facts.get("specs") or {}
        arch = specs.get("Microarchitecture")
        truth = MICROARCH_SOCKET.get(arch) if arch else None
        if truth:
            return ("verified", f"maker table maps {arch} to {truth}") if truth == value else \
                ("false", f"claim says {value}; the maker table maps {arch} to {truth}")
        page = specs.get("Socket")
        if not page:
            return "unverified", "could not verify: no socket or microarchitecture on the page"
        return ("verified", f"the page lists socket {page}") if page == value else \
            ("false", f"claim says {value}; differs from the listing at {at}: the page lists {page}")
    if field == "stock":
        page = in_stock(facts.get("stock"))
        if page is None:
            return "unverified", "could not verify: stock not stated on the page"
        word = lambda b: "in stock" if b else "out of stock"
        return ("verified", f"the page shows {word(page)}") if page == value else \
            ("false", f"claim says {word(value)}; differs from the listing at {at}: the page shows {word(page)}")
    if field == "return_days":
        m = re.search(r"(\d+)[- ]day", str(facts.get("return_policy") or ""))
        if not m:
            return "unverified", "could not verify: no return window on the page"
        days = int(m.group(1))
        return ("verified", f"the page shows {days}-day returns") if days == value else \
            ("false", f"claim says {value}-day returns; differs from the listing at {at}: the page shows {days}-day")
    return "unverified", f"could not verify: {field} claims are not checked yet"


def check_claim(claim, fetch=None, history=None):
    fetch = fetch or default_fetch
    url = claim.get("evidence_url") or ""
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = {"result": "unverified", "evidence_url": url, "checked_at": at, "evidence_hash": ""}
    field, value = parse_claim(claim)
    if field is None:
        return {**out, "method": "could not verify: claim text not recognized", "reason": "could not verify"}
    try:
        body = fetch(url)
    except Exception as e:  # unreachable or blocked page: never "false"
        return {**out, "method": f"could not verify: page fetch failed ({type(e).__name__})", "reason": "could not verify"}
    out["evidence_hash"] = hashlib.sha256(body).hexdigest()
    facts, source = page_facts(body.decode("utf-8", "replace"))
    series = _history(url, facts, fetch, history) if field == "was_price" else None
    result, reason = judge(field, value, facts, at, series)
    return {**out, "result": result, "method": f"fetched page, {source}, {field} rule", "reason": reason}
