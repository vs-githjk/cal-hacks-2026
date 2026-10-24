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
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from data.fit_checker.tables import MICROARCH_SOCKET

PATTERNS = [  # (field, regex, value from match); first match per field, every field is checked
    ("was_price", r"\bwas\s*\$?\s*([\d,]+(?:\.\d+)?)", lambda m: _num(m.group(1))),
    ("socket", r"\bsocket\s*(AM\d|LGA\s?\d{3,4})", lambda m: m.group(1).replace(" ", "").upper()),
    ("return_days", r"(\d+)[- ]day returns?", lambda m: int(m.group(1))),
    ("stock", r"\b(out of stock|not in stock|unavailable|sold out)\b", lambda m: False),
    ("stock", r"\bin stock\b", lambda m: True),
    ("condition", r"\bopen[- ]box\b", lambda m: "open-box"),
    ("condition", r"\brefurb", lambda m: "refurbished"),
    ("condition", r"\b(used|pre-owned)\b", lambda m: "used"),
    ("condition", r"\bnew\b", lambda m: "new"),
    ("price", None, None),  # see _price: a $ amount next to over/save/off/fee/shipping is not the price
]
NOT_PRICE = re.compile(r"(over|save|saves|saving|off|fee|fees|shipping|ship|under)\W*$|^\W*(off|fee|fees|shipping)\b", re.I)

LD_CONDITION = {"NewCondition": "new", "UsedCondition": "used", "RefurbishedCondition": "refurbished", "DamagedCondition": "used"}


def _num(s):
    return float(str(s).replace(",", ""))


def _money(v):
    """Page price -> float, or None when the page gives no usable number ("", null, "N/A")."""
    if isinstance(v, bool) or v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d[\d,]*\.?\d*", str(v))
    return _num(m.group(0)) if m else None


def _price(text):
    """The claimed price, or None when the text gives more than one candidate amount; absent when there is none."""
    amounts = []
    for m in re.finditer(r"\$\s?([\d,]+(?:\.\d+)?)", text):
        if NOT_PRICE.search(text[max(0, m.start() - 14):m.start()]) or NOT_PRICE.search(text[m.end():m.end() + 10]):
            continue
        amounts.append(_num(m.group(1)))
    if not amounts:
        return ()
    return (amounts[0],) if len(set(amounts)) == 1 else (None,)


def parse_claims(claim):
    """Every field the claim states, in PATTERNS order. A "was $X" amount is not also read as the current price."""
    if claim.get("field"):
        return [(claim["field"], claim.get("value"))]
    text = claim.get("text") or ""
    found = {}
    for field, rx, val in PATTERNS:
        if field == "price":
            for v in _price(text):
                found.setdefault("price", v)
            continue
        m = re.search(rx, text, re.I)
        if m and field not in found:
            found[field] = val(m)
            if field == "was_price":
                text = text[:m.start()] + text[m.end():]
    return list(found.items())


def parse_claim(claim):
    """The first field the claim states (kept for callers that read one field)."""
    return (parse_claims(claim) or [(None, None)])[0]


from .fetch import guarded_get as default_fetch  # noqa: E402  (http(s) only, public addresses, redirects re-checked, 2 MB cap)


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
            facts = {"title": node.get("name"), "price": _money(offer.get("price")),
                     "condition": LD_CONDITION.get(cond), "stock": avail or None}
            return {k: v for k, v in facts.items() if v is not None}, "page JSON-LD"
    return {}, "no structured data"


def in_stock(v):
    if isinstance(v, bool):
        return v
    s = str(v).lower()
    if re.search(r"out of stock|outofstock|not in stock|unavailable|sold out|soldout", s) or s.startswith("0 "):
        return False  # negations first: "not in stock" contains "in stock"
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
    if field == "price" and value is None:
        return "unverified", "could not verify: the claim states more than one price"
    if field == "price":
        page = _money(facts.get("price"))
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
    unverified = lambda why: {**out, "method": f"could not verify: {why}", "reason": "could not verify"}
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = {"result": "unverified", "evidence_url": url, "checked_at": at, "evidence_hash": ""}
    fields = parse_claims(claim)
    if not fields:
        return unverified("claim text not recognized")
    if urlparse(url).scheme not in ("http", "https"):
        return unverified("only http and https pages are checked")
    try:
        body = fetch(url)
    except Exception as e:  # unreachable or blocked page: never "false"
        return unverified(f"page fetch failed ({e if isinstance(e, ValueError) else type(e).__name__})")
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, (bytes, bytearray)):
        return unverified("page body was not text")
    out["evidence_hash"] = hashlib.sha256(body).hexdigest()
    try:  # a malformed page must not abort a batch or turn into "false"
        facts, source = page_facts(body.decode("utf-8", "replace"))
        results = [(f, *judge(f, v, facts, at, _history(url, facts, fetch, history) if f == "was_price" else None))
                   for f, v in fields]
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        return unverified(f"page could not be parsed ({type(e).__name__})")
    rank = {"false": 0, "unverified": 1, "verified": 2}  # the worst field decides: one false part makes the claim false
    result = min((r for _, r, _ in results), key=rank.get)
    names = ", ".join(f for f, _, _ in results)
    reason = "; ".join(why for _, r, why in results if r == result)
    rules = f"{names} rule{'s' if len(results) > 1 else ''}"
    if result == "unverified":
        return {**out, "result": result, "method": f"could not verify: {source}, {rules}", "reason": reason}
    return {**out, "result": result, "method": f"fetched page, {source}, {rules}", "reason": reason}
