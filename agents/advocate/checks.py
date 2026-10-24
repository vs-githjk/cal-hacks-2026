"""Quality Advocate checks for Tech Bazaar: pure and deterministic. One AdvocateCard per bid.

Bid line: {sku_spec, unit_price, quantity, offered_condition, page_condition, listing_url, attrs}; attrs carry
`category` and SpecCard attr names. Need item: {sku_spec, condition, variant, quantity}. owned: the buyer's parts
as {category: SpecCard attrs}, e.g. {"psu": {"wattage": 750}, "case": {"max_gpu_length_mm": 330}}.
Fit is Lane C's checker (data.fit_checker), run once per bid on the bid's parts plus the owned parts.
Fee fields are ignored: the advocate never sees a fee. Text rule: neutral wording ("did not match"), no en/em dashes.
"""
import re
from urllib.parse import urlsplit

import common  # noqa: F401  (puts the repo root on sys.path for data.*)
from data.fit_checker import check_fit

PRICE_TOLERANCE = 0.10
FLOOR_URL = "https://example.com/price-floor/simulated"
MAX_WARNINGS = 3
VETO_KINDS = {"condition", "fit", "recall"}
INFO_KINDS = {"note"}  # shown, but never change the recommendation
REPO = "https://github.com/vs-githjk/cal-hacks-2026/blob/main"
# Code-owned sources for warnings whose evidence is our own rules, used when no listing URL is given.
CODE_SOURCES = {"fit": f"{REPO}/data/fit_checker/README.md", "fit_unknown": f"{REPO}/data/fit_checker/README.md",
                "note": f"{REPO}/data/fit_checker/README.md", "record": f"{REPO}/agents/advocate/checks.py",
                "floor": FLOOR_URL, "unsourced": f"{REPO}/agents/advocate/checks.py"}

# Closed-schema reason for the voice call: summary comes only from this table, never from seller text or a model.
# Every summary must pass pay.callscript.clean_advocate_reason (tested).
CALL_SUMMARIES = {
    "advocate.condition": "The listing page shows a different condition than the seller claims",
    "advocate.recall": "This product matches a CPSC recall entry",
    "advocate.price": "The price is more than 10 percent above its price history",
    "advocate.spec": "This offer is not the condition you asked for",
    "advocate.record": "This seller has a caution record",
    "advocate.floor": "This bid did not pass the price floor check",
    "advocate.unsourced": "A claim on this bid could not be checked against its listing",
    "advocate.fit_unknown": "Fit could not be confirmed from the listing details",
    "fit.gpu_length": "The card is longer than your case allows",
    "fit.psu_wattage": "Your power supply is below what this card needs",
    "fit.gpu_connectors": "Your power supply lacks the connectors this card needs",
    "fit.cpu_socket": "The processor socket does not match the board",
    "fit.ram_type": "The memory type does not match the board",
    "fit.form_factor": "The board does not fit your case",
    "fit.psu_form_factor": "The power supply does not fit your case",
    "fit.cooler_height": "The cooler is taller than your case allows",
    "fit.cooler_socket": "The cooler does not support this processor socket",
    "fit": "This part does not fit your build",
    "advocate.ok": "No problems found in the checks",
}


def _norm(s) -> str:
    return " ".join(str(s or "").lower().replace("-", " ").replace("_", " ").split())


def _warn(kind, text, url, dollars, rule_id=None):
    """Every warning carries a source. A veto needs evidence: a condition veto with no listing link is
    downgraded to a caution that says so; code-decided warnings fall back to the rule's own source."""
    if not url and kind in ("condition", "spec"):
        kind, text = "unsourced", text + " No listing link to cite, so this is a caution, not a veto."
    url = _safe_source_url(url) if url else CODE_SOURCES.get(kind) or CODE_SOURCES["unsourced"]
    return {"kind": kind, "rule_id": rule_id or f"advocate.{kind}",
            "text": text.replace("\u2014", ",").replace("\u2013", " to "),
            "source_url": url, "dollar_impact": round(float(dollars), 2)}


def _spec_cards(bid, owned):
    """The build to check: the bid's parts, plus owned parts of any category the bid doesn't replace."""
    cards = [{"id": l["sku_spec"], "category": (l.get("attrs") or {}).get("category"), "name": l["sku_spec"],
              "attrs": l.get("attrs") or {}} for l in bid["lines"]]
    offered = {c["category"] for c in cards}
    cards += [{"id": f"owned-{cat}", "category": cat, "name": f"your {cat}", "attrs": attrs}
              for cat, attrs in (owned or {}).items() if cat not in offered]
    return cards


# Which part categories each of Lane C's rules compares. Checks between two parts the buyer already owns
# are dropped: those parts already work together, so they say nothing about this bid.
# ponytail: hand map of data/fit_checker rules; ask Anoop to put the parts on each check if rules change often.
RULE_PARTS = {"fit.cpu_socket": {"cpu", "motherboard"}, "fit.ram_type": {"motherboard", "memory"},
              "fit.ram_slots": {"motherboard", "memory"}, "fit.psu_wattage": {"psu", "cpu", "gpu"},
              "fit.gpu_connectors": {"gpu", "psu"}, "fit.gpu_length": {"gpu", "case"},
              "fit.cooler_socket": {"cpu", "cooler"}, "fit.cooler_height": {"cooler", "case"},
              "fit.form_factor": {"motherboard", "case"}, "fit.psu_form_factor": {"psu", "case"},
              "fit.storage": {"motherboard", "storage"}}


def _fit_warnings(bid, owned):
    cards = _spec_cards(bid, owned)
    fit = check_fit(cards)
    bid_parts = {c["category"] for c in cards if not c["id"].startswith("owned-")}
    checks = [c for c in fit["checks"] if RULE_PARTS.get(c["rule_id"], bid_parts) & bid_parts]
    fails = [c for c in checks if c["verdict"] == "fail"]
    unsure = [c for c in checks if c["verdict"] == "uncertain"]
    url = bid["lines"][0].get("listing_url", "") if bid["lines"] else ""
    out = []
    if fails:
        rid = fails[0]["rule_id"]
        summary = CALL_SUMMARIES.get(rid, CALL_SUMMARIES["fit"])
        out.append(_warn("fit", f"Does not fit: {summary}.", url, bid["total_landed_price"], rule_id=rid))
    elif unsure:
        out.append(_warn("fit_unknown", f"Fit not confirmed: {CALL_SUMMARIES['advocate.fit_unknown']}.", url, 0))
    if fit["notes"]:
        out.append(_warn("note", "The fit checker returned a non-blocking note.", url, 0))
    return out


# #89: seller-supplied strings never reach card text. Conditions map to this closed set, item names come from the
# buyer's own need, seller ids must match our pattern, and fit text comes from the rule templates.
CONDITIONS = {"new", "open box", "refurbished", "used"}


def _cond(value) -> str:
    v = _norm(value)
    return v if v in CONDITIONS else "an unrecognized condition"


def _item(sku, wanted) -> str:
    return sku if sku in (wanted or {}) else "this item"


def _seller(supplier_id) -> str:
    return f"Seller {supplier_id}" if re.fullmatch(r"seller_\d{1,3}", str(supplier_id)) else "This seller"


def _card_warnings(bid, owned, baseline, records, recalls, wanted=None):
    out = _fit_warnings(bid, owned)
    for line in bid["lines"]:
        sku = _item(line["sku_spec"], wanted)
        total = line["unit_price"] * line["quantity"]
        url = line.get("listing_url", "")

        # an honest offer of a different condition than asked for: caution, not a veto
        asked = _norm((wanted or {}).get(line["sku_spec"]))
        if asked and _norm(line.get("offered_condition")) not in ("", asked):
            out.append(_warn("spec", f"You asked for {_cond(asked)}; this offer is {_cond(line['offered_condition'])}.",
                             url, 0))

        offered, page = _norm(line.get("offered_condition")), _norm(line.get("page_condition"))
        if offered and page and offered != page:
            offered, page = _cond(offered), _cond(page)
            out.append(_warn("condition", f"{sku} is listed as {offered}, the page says {page}. "
                             "The condition claim did not match the listing.", url, total))

        base = baseline.get(_norm(line["sku_spec"]))
        if base and line["unit_price"] > base["unit_price"] * (1 + PRICE_TOLERANCE):
            over = (line["unit_price"] - base["unit_price"]) * line["quantity"]
            out.append(_warn("price", f"{sku} at ${line['unit_price']:.2f} is above the price history baseline "
                             f"of ${base['unit_price']:.2f}; the price claim did not match the price history "
                             f"by ${over:.2f}.", base["source_url"], over))

        hit = next((r for r in recalls if r["match"] in _norm(line["sku_spec"])), None)
        if hit:
            out.append(_warn("recall", f"{sku} matches a CPSC recall entry ('{hit['match']}').",
                             hit["source_url"], total))

    rec = records.get(bid["supplier_id"])
    if rec and rec["record"] != "good":
        out.append(_warn("record", f"{_seller(bid['supplier_id'])} has a '{_norm(rec['record'])}' record.",
                         rec.get("source_url", ""), 0))

    if not bid.get("floor_check_passed", True):
        out.append(_warn("floor", "Bid did not pass the price floor check; the price may not hold.", FLOOR_URL, 0))
    return out


def advise(need: dict, bids: list[dict], baseline: dict, records: dict, recalls: list[dict],
           owned: dict | None = None) -> list[dict]:
    owned = owned if owned is not None else need.get("owned", {})
    wanted = {i["sku_spec"]: i.get("condition") for i in need.get("items", [])}
    cards = []
    for bid in bids:
        warnings = _card_warnings(bid, owned, baseline, records, recalls, wanted)
        kinds = {w["kind"] for w in warnings}  # decided before truncation so a veto is never hidden
        rec = "veto" if kinds & VETO_KINDS else "caution" if kinds - INFO_KINDS else "buy"
        reason = call_reason(warnings, bid)  # from the full list, so a veto reason is never cut
        warnings = sorted(warnings, key=lambda w: -w["dollar_impact"])[:MAX_WARNINGS]
        # #89 closed output: recommendation, rule_id, reason (template only) and source_url at the top level
        cards.append({"need_id": need["id"], "bid_id": bid["id"], "recommendation": rec,
                      "rule_id": reason["rule_id"], "reason": reason["summary"], "source_url": reason["source_url"],
                      "warnings": warnings, "wait_until": "", "call_reason": reason})
    return cards


def call_reason(warnings: list[dict], bid: dict) -> dict:
    """The reason Lane D's voice call may speak: exactly {rule_id, summary, source_url}. Vetoes first, then the
    biggest dollar impact. The summary is looked up by rule_id; seller text and model output never reach it."""
    ranked = sorted((w for w in warnings if w["kind"] not in INFO_KINDS),
                    key=lambda w: (w["kind"] not in VETO_KINDS, -w["dollar_impact"]))
    if not ranked:
        url = bid["lines"][0].get("listing_url") if bid.get("lines") else None
        return {"rule_id": "advocate.ok", "summary": CALL_SUMMARIES["advocate.ok"],
                "source_url": _safe_source_url(url) if url else CODE_SOURCES["unsourced"]}
    w = ranked[0]
    rid = w["rule_id"] if w["rule_id"] in CALL_SUMMARIES else ("fit" if w["kind"] == "fit" else f"advocate.{w['kind']}")
    return {"rule_id": rid, "summary": CALL_SUMMARIES[rid],
            "source_url": _safe_source_url(w["source_url"])}


def _safe_source_url(value: str) -> str:
    """Keep valid public citation URLs unchanged; replace unsafe or malformed values."""
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return CODE_SOURCES["unsourced"]
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return CODE_SOURCES["unsourced"]
        parsed.port  # force malformed ports to fail closed
    except (TypeError, ValueError):
        return CODE_SOURCES["unsourced"]
    return value


def best_bid(bids: list[dict], cards: list[dict]):
    vetoed = {c["bid_id"] for c in cards if c["recommendation"] == "veto"}
    ok = [b for b in bids if b["id"] not in vetoed]
    return min(ok, key=lambda b: b["total_landed_price"]) if ok else None
