"""Claim check (Lane C, c3). Checks one seller claim against the live page.

check_claim(claim, fetch=None, history=None) ->
    {"result": "verified"|"unverified"|"false", "evidence_url", "checked_at" (ISO-8601 UTC), "method",
     "evidence_hash" (sha256 of the page bytes), "reason"}
Input is a Claim (contracts/Claim.schema.json); `result` maps to Claim.check. The page is claim["evidence_url"].
Optional claim["field"] and claim["value"] skip text parsing. Page facts come from schema.org JSON-LD; our own SIM liar pages
(is_our_liar_page) also carry a <script id="listing"> JSON block, read first on those pages only (RT-20: on any other host a
seller could write that block, so it is ignored). A page we cannot read is "unverified", never "false".
A price claim is in USD unless it names another currency ("C$1,749.99", "$1,749.99 CAD", or claim["currency"]); when the page
states a priceCurrency that differs, the price claim is "unverified" and the reason names both currencies (RT-19).
Wording is neutral: "differs from the listing at time T", "did not match the price history", "could not verify".
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from data.fit_checker.tables import MICROARCH_SOCKET

PATTERNS = [  # (field, regex, value from match); first match per field, every field is checked
    ("was_price", r"\bwas\s*(?:(US|CA|CDN|AU|NZ|HK|MX|C|A|S)?\$)?\s*([\d,]+(?:\.\d+)?)", lambda m: _num(m.group(2))),
    ("socket", r"\bsocket\s*(AM\d|LGA\s?\d{3,4})", lambda m: m.group(1).replace(" ", "").upper()),
    ("return_days", r"(\d+)[- ]day returns?", lambda m: int(m.group(1))),
    ("stock", r"\b(out of stock|not in stock|unavailable|sold out)\b", lambda m: False),
    ("stock", r"\bin stock\b", lambda m: True),
    ("warranty_months", r"(\d+)[- ]?(year|yr|month|mo)s?\b[- ]?(?:limited\s+)?warranty", lambda m: _warranty_months(int(m.group(1)), m.group(2))),
    ("condition", r"\bopen[- ]box\b", lambda m: "open-box"),
    ("condition", r"\brefurb", lambda m: "refurbished"),
    ("condition", r"\b(used|pre-owned)\b", lambda m: "used"),
    ("condition", r"\bnew\b", lambda m: "new"),
    ("price", None, None),  # see _price: a $ amount next to over/save/off/fee/shipping is not the price
]
# A keyword attaches only to its own amount: directly before the $ (spaces only, no comma or colon between) or directly
# after it. "off" and "fee" follow their amount ("$50 off"), so "$50 off $749" keeps $749 as the price.
NOT_PRICE_BEFORE = re.compile(r"\b(over|save|saves|saving|under|shipping|ship)\s*$", re.I)
NOT_PRICE_AFTER = re.compile(r"^\s*(off|fee|fees)\b", re.I)
# Amounts that are not the item price but say something about the offer: the claim's price is then unverified.
OFFER_BEFORE = re.compile(r"\b(orders? of|up to|rebate|coupon|gift card|credit)\s*$", re.I)
OFFER_AFTER = re.compile(r"^\s*(or more|gift card|rebate|coupon|credit|back)\b", re.I)

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


# RT-19: a "$" amount is USD unless the claim names another currency right beside it.
CURRENCY_PREFIX = {"US": "USD", "C": "CAD", "CA": "CAD", "CDN": "CAD", "A": "AUD", "AU": "AUD", "NZ": "NZD", "HK": "HKD", "S": "SGD", "MX": "MXN"}
CURRENCY_CODES = frozenset({"USD", "CAD", "EUR", "GBP", "AUD", "NZD", "JPY", "CNY", "CHF", "MXN", "INR", "SEK", "NOK", "DKK", "SGD",
                            "HKD", "KRW", "BRL", "PLN", "CZK", "ZAR", "TWD"})
_PREFIX_BEFORE = re.compile(r"(?<![A-Za-z0-9])(US|CA|CDN|AU|NZ|HK|MX|C|A|S)$", re.I)   # letters glued to the $ sign: C$1,749
_CODE_BEFORE = re.compile(r"(?<![A-Za-z])([A-Za-z]{3})\s?$")                            # CAD $1,749
_CODE_AFTER = re.compile(r"^\s?([A-Za-z]{3})(?![A-Za-z])")                              # $1,749 CAD


def _currency_code(v):
    """A three-letter currency code upper-cased, else None (missing, "$", "dollars", 840)."""
    return v.strip().upper() if isinstance(v, str) and re.fullmatch(r"[A-Za-z]{3}", v.strip()) else None


def _amount_currency(before, after):
    """The currency a claim names beside one "$" amount: a prefix glued to the sign (C$), else a code just before or after
    (CAD $5, $5 CAD). USD when it names none."""
    m = _PREFIX_BEFORE.search(before)
    if m:
        return CURRENCY_PREFIX[m.group(1).upper()]
    for found in (_CODE_BEFORE.search(before), _CODE_AFTER.match(after)):
        if found and found.group(1).upper() in CURRENCY_CODES:
            return found.group(1).upper()
    return "USD"


def _price_and_currency(text):
    """((amount,), currency): (amount,) for the claimed price; (None,) when it is ambiguous (two different amounts, or an
    offer amount such as a gift card or an order minimum); () when no amount is the price. The currency is the one named
    beside that amount, USD when none; two amounts in two currencies are ambiguous too."""
    amounts, offer = [], False
    for m in re.finditer(r"\$\s?([\d,]+(?:\.\d+)?)", text):
        before, after = text[:m.start()], text[m.end():]
        if OFFER_BEFORE.search(before) or OFFER_AFTER.search(after):
            offer = True
        elif not (NOT_PRICE_BEFORE.search(before) or NOT_PRICE_AFTER.search(after)):
            amounts.append((_num(m.group(1)), _amount_currency(before, after)))
    if offer or len({a for a, _ in amounts}) > 1 or len({c for _, c in amounts}) > 1:
        return (None,), "USD"
    return ((amounts[0][0],), amounts[0][1]) if amounts else ((), "USD")


def _price(text):
    return _price_and_currency(text)[0]


def _parse(claim):
    """([(field, value)], {field: currency}): every field the claim states, in PATTERNS order, and the currency its amount is in
    (USD unless named, or claim["currency"]). A "was $X" amount is not also read as the current price."""
    named = _currency_code(claim.get("currency"))
    if claim.get("field"):
        return [(claim["field"], claim.get("value"))], {claim["field"]: named or "USD"}
    text = claim.get("text") or ""
    found, currency = {}, {}
    for field, rx, val in PATTERNS:
        if field == "price":
            values, cur = _price_and_currency(text)
            for v in values:
                found.setdefault("price", v)
                currency.setdefault("price", cur)
            continue
        m = re.search(rx, text, re.I)
        if m and field not in found:
            found[field] = val(m)
            if field == "was_price":
                currency[field] = CURRENCY_PREFIX[m.group(1).upper()] if m.group(1) else _amount_currency("", text[m.end():])
                text = text[:m.start()] + text[m.end():]
    return list(found.items()), {f: named or currency.get(f, "USD") for f in found}


def parse_claims(claim):
    """Every field the claim states, in PATTERNS order. A "was $X" amount is not also read as the current price."""
    return _parse(claim)[0]


def parse_claim(claim):
    """The first field the claim states (kept for callers that read one field)."""
    return (parse_claims(claim) or [(None, None)])[0]


from .fetch import guarded_get as default_fetch  # noqa: E402  (http(s) only, public addresses, redirects re-checked, 2 MB cap)


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")  # keeps the length, unlike str.lower
LISTING_TAG = '<script type="application/json" id="listing">'
PRODUCT_TYPES = {"Product", "IndividualProduct", "SomeProducts", "ProductModel", "ProductGroup"}


def script_blocks(html):
    """[(opening tag, body)] for every <script ...>...</script> in one linear scan (#317: the old regex was cubic on
    "<script x application/ld+json" * N). Each search starts where the last one ended, so no character is rescanned."""
    low, out, i = html.translate(_ASCII_LOWER), [], 0
    while True:
        s = low.find("<script", i)
        if s < 0:
            break
        if low[s + 7:s + 8] not in ("", ">", "/") and not low[s + 7:s + 8].isspace():
            i = s + 7  # <scripty is another tag
            continue
        e = low.find(">", s + 7)
        if e < 0:
            break
        c = low.find("</script", e + 1)
        if c < 0:
            break  # no closing tag: nothing after this can close either
        out.append((html[s:e + 1], html[e + 1:c]))
        i = c + 8
    return out


def _loads(text, what):
    try:
        return json.loads(text)
    except RecursionError as e:  # deeply nested JSON: a parse failure, never a crash
        raise ValueError(f"{what} is nested too deeply") from e


def _is_product(node):
    t = node.get("@type")
    types = [t] if isinstance(t, str) else t if isinstance(t, list) else []
    return any(isinstance(x, str) and re.sub(r"^(https?://schema\.org/|schema:)", "", x.strip()) in PRODUCT_TYPES for x in types)


def _same_url(a, b):
    norm = lambda u: u.strip().split("#", 1)[0].rstrip("/") if isinstance(u, str) else None
    return norm(a) is not None and norm(a) == norm(b)


def _page_key(u, base):
    """(host, path) of u resolved against base, ignoring scheme, query, fragment and a trailing slash; None if not a URL."""
    from urllib.parse import urljoin, urlparse
    if not isinstance(u, str) or not u.strip():
        return None
    p = urlparse(urljoin(base, u.strip()))
    host = (p.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host  # #397: www.shop.example and shop.example are one store's page
    return (host, p.path.rstrip("/")) if p.hostname else None


def _names_another_page(node, url):
    """True when the Product's url is a different page (a related product or a carousel item, not this listing)."""
    there, here = _page_key(node.get("url"), url), _page_key(url, url)
    return there is not None and here is not None and there != here


def ld_product(html, url=None, notes=None):
    """The schema.org Product node an agent reads: the one whose @id or url is this page (a leading www. ignored), else the
    first with offers, else the first; {} when there is none. With the page url given, a Product whose url is another page
    is not read when another Product is there (#334); when it is the only Product (a canonical on another path) it is kept
    and a note is appended to `notes` (#397). Raises ValueError for JSON-LD too deeply nested to parse."""
    nodes = []
    for tag, body in script_blocks(html):
        if "application/ld+json" not in tag.translate(_ASCII_LOWER):
            continue
        try:
            data = _loads(body, "JSON-LD")
        except ValueError as e:
            if isinstance(e.__cause__, RecursionError):
                raise
            continue  # one broken block does not hide the others
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        nodes += [n for n in (items if isinstance(items, list) else [items]) if isinstance(n, dict) and _is_product(n)]
    if url:
        here = _page_key(url, url)
        for n in nodes:
            if _same_url(n.get("@id"), url) or _same_url(n.get("url"), url) or \
                    (here is not None and here in (_page_key(n.get("@id"), url), _page_key(n.get("url"), url))):
                return n
        kept = [n for n in nodes if not _names_another_page(n, url)]
        if not kept and len(nodes) == 1:
            if notes is not None:
                notes.append(f"the only Product names another url ({str(nodes[0].get('url'))[:120]}), read as this listing")
            return nodes[0]
        nodes = kept
    return next((n for n in nodes if n.get("offers")), nodes[0] if nodes else {})


def ld_offer(product):
    offer = product.get("offers") or {}
    offer = offer[0] if isinstance(offer, list) and offer else offer
    return offer if isinstance(offer, dict) else {}


def _ld_currency(offer):
    """The offer's priceCurrency as a three-letter code, else the first priceSpecification's (the order readiness reads them in);
    None when neither is a readable code (RT-19)."""
    cur = _currency_code(offer.get("priceCurrency"))
    if cur:
        return cur
    specs = offer.get("priceSpecification")
    for spec in specs if isinstance(specs, list) else [specs]:
        cur = _currency_code(spec.get("priceCurrency")) if isinstance(spec, dict) else None
        if cur:
            return cur
    return None


def page_facts(html, url=None):
    """(facts, how) from our SIM <script id="listing"> JSON, else the page's schema.org Product (see ld_product).
    RT-20: the listing block is read only when `url` is one of our own demo liar pages (is_our_liar_page). On any other host,
    and when no url is given, a seller could write that block to say anything, so it is ignored and never parsed.
    Raises ValueError when our listing JSON is not a JSON object or the page's JSON is too deeply nested to parse."""
    body = next((b for tag, b in script_blocks(html) if tag == LISTING_TAG), None) if is_our_liar_page(url) else None
    if body is not None:
        data = _loads(body, "listing JSON")
        if not isinstance(data, dict):
            raise ValueError("listing JSON is not an object")
        if "warranty_months" not in data:
            wm = _text_warranty(data.get("warranty"))
            if wm is None:
                wm = _text_warranty(data.get("description"))
                if wm is not None:
                    data["warranty_source"] = "description"
            if wm is not None:
                data["warranty_months"] = wm
        cur = _currency_code(data.get("priceCurrency")) or _currency_code(data.get("currency"))
        data.pop("priceCurrency", None)
        data.pop("currency", None)
        if cur:
            data["currency"] = cur
        return data, "page listing JSON"
    notes = []
    node = ld_product(html, url, notes)
    if not node:
        return {}, "no structured data"
    offer = ld_offer(node)
    cond = str(offer.get("itemCondition") or "").rsplit("/", 1)[-1]
    avail = str(offer.get("availability") or "").rsplit("/", 1)[-1]
    structured = node.get("warranty") or offer.get("warranty")
    described = None if structured else _text_warranty(node.get("description"))
    facts = {"title": node.get("name"), "price": _money(offer.get("price")), "currency": _ld_currency(offer),
             "condition": LD_CONDITION.get(cond), "stock": avail or None,
             "return_policy": _ld_returns(offer.get("hasMerchantReturnPolicy") or node.get("hasMerchantReturnPolicy")),
             "warranty_months": _ld_warranty(structured) if structured else described,
             "warranty_source": "description" if described is not None else None}
    return {k: v for k, v in facts.items() if v is not None}, "page JSON-LD" + "".join(f"; {n}" for n in notes)


def _return_days(days):
    """Finite, non-negative, whole-number days only (a bool, Infinity, -30 or 14.5 is not a policy)."""
    if isinstance(days, str) and days.strip().isdigit():
        days = int(days)
    if isinstance(days, bool) or not isinstance(days, (int, float)):
        return None
    if isinstance(days, float) and (days != days or days in (float("inf"), float("-inf")) or days != int(days)):
        return None
    return int(days) if days >= 0 else None


def _one_return_policy(policy):
    if not isinstance(policy, dict):
        return None
    if str(policy.get("returnPolicyCategory") or "").endswith("MerchantReturnNotPermitted"):
        return "returns not permitted"
    days = _return_days(policy.get("merchantReturnDays"))
    return None if days is None else f"{days}-day returns"


def _warranty_months(n, unit):
    """N years or months -> whole months, or None when out of range (finite, non-negative, whole, at most 120 months)."""
    n = _return_days(n)
    if n is None:
        return None
    months = n * 12 if str(unit).lower().startswith(("y", "ann")) else n if str(unit).lower().startswith(("m", "mon")) else None
    return months if months is not None and months <= 120 else None


def _one_warranty(w):
    d = w.get("durationOfWarranty") if isinstance(w, dict) else None
    if not isinstance(d, dict):
        return None
    return _warranty_months(d.get("value"), d.get("unitCode") or d.get("unitText"))


def _ld_warranty(w):
    """schema.org WarrantyPromise -> months. A list counts only when every promise agrees."""
    if isinstance(w, list):
        found = {_one_warranty(x) for x in w}
        return found.pop() if len(found) == 1 else None
    return _one_warranty(w)


def _text_warranty(*texts):
    for t in texts:
        m = re.search(PATTERNS[next(i for i, p in enumerate(PATTERNS) if p[0] == "warranty_months")][1], str(t or ""), re.I)
        if m:
            return _warranty_months(int(m.group(1)), m.group(2))
    return None


def _ld_returns(policy):
    """schema.org MerchantReturnPolicy -> "N-day returns", "returns not permitted", or None when it says neither.
    A list of policies counts only when every one agrees (we do not guess which country applies)."""
    if isinstance(policy, list):
        found = {_one_return_policy(p) for p in policy}
        return found.pop() if len(found) == 1 else None
    return _one_return_policy(policy)


SCHEMA_AVAILABLE = {"instock", "limitedavailability", "onlineonly", "instoreonly"}
SCHEMA_UNAVAILABLE = {"outofstock", "soldout", "discontinued", "preorder", "presale", "backorder"}  # not available now


def in_stock(v):
    if isinstance(v, bool):
        return v
    s = str(v).lower()
    if s.replace(" ", "") in SCHEMA_AVAILABLE:
        return True
    if s.replace(" ", "") in SCHEMA_UNAVAILABLE:
        return False
    if re.search(r"out of stock|outofstock|not in stock|unavailable|sold out|soldout", s) or s.startswith("0 "):
        return False  # negations first: "not in stock" contains "in stock"
    if "in stock" in s or "instock" in s or re.match(r"\d+ (units|in stock|remaining)", s):
        return True
    return None


LIAR_PAGE_HOSTS = {"localhost:8765", "127.0.0.1:8765"}  # where we serve data/liar_pages/site (python -m http.server 8765)


def is_our_liar_page(url):
    """SIM is decided from the evidence URL (our own hosted pages), never from anything a page says about itself."""
    p = urlparse(url or "")
    return p.scheme == "http" and p.netloc in LIAR_PAGE_HOSTS and p.path.endswith(".html")


def _history(url, facts, fetch, history, observations=None):
    """Price history for a was-price claim, from our own records only: the caller's history, our recorded SIM series for a
    SIM page, or our dated MIRROR observations of this exact URL. Nothing is read from the page being judged."""
    if history is not None:
        return history
    if is_our_liar_page(url) and facts.get("sku"):
        try:
            from data.liar_pages.build import PRICE_HISTORY
        except ImportError:  # the Actor bundle ships no records
            return None
        return PRICE_HISTORY.get(facts["sku"])
    if observations is None:
        try:
            from data.baselines import observations as load_observations
        except ImportError:  # the Actor bundle ships no records
            return None
        observations = load_observations()
    series = sorted(({"date": str(r["observed_at"])[:10], "price": r["price"]} for r in observations if r.get("url") == url),
                    key=lambda p: p["date"])
    return series or None


def judge(field, value, facts, at, series, currency="USD"):
    """-> (result, reason). `currency` is the currency the claim's amount is in (USD unless it names another, RT-19)."""
    if field == "condition":
        page = facts.get("condition")
        if not page:
            return "unverified", "could not verify: the page states no condition"
        return ("verified", f"the page shows {page}") if page == value else \
            ("false", f"claim says {value}; differs from the listing at {at}: the page shows {page}")
    if field == "price" and value is None:
        return "unverified", "could not verify: the claim states more than one amount (another price, or an offer such as a gift card or order minimum)"
    if field == "price":
        page = _money(facts.get("price"))
        if page is None:
            return "unverified", "could not verify: the page states no price"
        shown = facts.get("currency")
        if shown and shown != currency:   # 1,749.99 CAD is not $1,749.99: never verified, and never false either
            return "unverified", f"could not verify: the claim is in {currency} and the page prices in {shown}, so the amounts cannot be compared"
        return ("verified", f"the page shows ${page:,.2f}") if abs(page - value) < 0.01 else \
            ("false", f"claim says ${value:,.2f}; differs from the listing at {at}: the page shows ${page:,.2f}")
    if field == "was_price":
        if currency != "USD":
            return "unverified", f"could not verify: the claim is in {currency} and our price history is in USD"
        if not series:
            return "unverified", "could not verify: no dated price history from our own captures"
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
        raw = str(facts.get("stock"))
        shown = f"{raw} (not available now)" if raw.lower().replace(" ", "") in SCHEMA_UNAVAILABLE - {"outofstock", "soldout"} else word(page)
        return ("verified", f"the page shows {shown}") if page == value else \
            ("false", f"claim says {word(value)}; differs from the listing at {at}: the page shows {shown}")
    if field == "warranty_months":
        page = facts.get("warranty_months")
        if page is None:
            return "unverified", "could not verify: no warranty term on the page"
        own = " (from the seller's own description)" if facts.get("warranty_source") == "description" else ""
        return ("verified", f"the page shows a {page}-month warranty{own}") if page == value else \
            ("false", f"claim says {value} months of warranty; differs from the listing at {at}: the page shows {page} months{own}")
    if field == "return_days":
        policy = str(facts.get("return_policy") or "")
        if "not permitted" in policy:
            return "false", f"claim says {value}-day returns; differs from the listing at {at}: the page says returns are not permitted"
        m = re.search(r"(\d+)[- ]day", policy)
        if not m:
            return "unverified", "could not verify: no return window on the page"
        days = int(m.group(1))
        return ("verified", f"the page shows {days}-day returns") if days == value else \
            ("false", f"claim says {value}-day returns; differs from the listing at {at}: the page shows {days}-day")
    return "unverified", f"could not verify: {field} claims are not checked yet"


def check_claim(claim, fetch=None, history=None, observations=None):
    fetch = fetch or default_fetch
    url = claim.get("evidence_url") or ""
    unverified = lambda why: {**out, "method": f"could not verify: {why}", "reason": "could not verify"}
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = {"result": "unverified", "evidence_url": url, "checked_at": at, "evidence_hash": ""}
    fields, currencies = _parse(claim)
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
        facts, source = page_facts(body.decode("utf-8", "replace"), url)
        results = [(f, *judge(f, v, facts, at, _history(url, facts, fetch, history, observations) if f == "was_price" else None,
                              currencies.get(f, "USD")))
                   for f, v in fields]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as e:
        return unverified(f"page could not be parsed ({type(e).__name__})")
    rank = {"false": 0, "unverified": 1, "verified": 2}  # the worst field decides: one false part makes the claim false
    result = min((r for _, r, _ in results), key=rank.get)
    names = ", ".join(f for f, _, _ in results)
    reason = "; ".join(why for _, r, why in results if r == result)
    rules = f"{names} rule{'s' if len(results) > 1 else ''}"
    if result == "unverified":
        return {**out, "result": result, "method": f"could not verify: {source}, {rules}", "reason": reason}
    return {**out, "result": result, "method": f"fetched page, {source}, {rules}", "reason": reason}
