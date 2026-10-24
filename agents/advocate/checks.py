"""Quality Advocate checks for Tech Bazaar: pure and deterministic. One AdvocateCard per bid.

Bid line: {sku_spec, unit_price, quantity, offered_condition, page_condition, listing_url, attrs}; attrs carry
`category` and SpecCard attr names. Need item: {sku_spec, condition, variant, quantity}. owned: the buyer's parts
as {category: SpecCard attrs}, e.g. {"psu": {"wattage": 750}, "case": {"max_gpu_length_mm": 330}}.
Fit is Lane C's checker (data.fit_checker), run once per bid on the bid's parts plus the owned parts.
Fee fields are ignored: the advocate never sees a fee. Text rule: neutral wording ("did not match"), no en/em dashes.
"""
import common  # noqa: F401  (puts the repo root on sys.path for data.*)
from data.fit_checker import check_fit
from urllib.parse import urlsplit, urlunsplit

PRICE_TOLERANCE = 0.10
FLOOR_URL = "https://example.com/price-floor/simulated"
MAX_WARNINGS = 3
MAX_CLAIM_CHECKS = 9
VETO_KINDS = {"condition", "fit", "recall"}
INFO_KINDS = {"note"}  # shown, but never change the recommendation
REPO = "https://github.com/vs-githjk/cal-hacks-2026/blob/main"
# Code-owned sources for warnings whose evidence is our own rules, used when no listing URL is given.
CODE_SOURCES = {"fit": f"{REPO}/data/fit_checker/README.md", "fit_unknown": f"{REPO}/data/fit_checker/README.md",
                "note": f"{REPO}/data/fit_checker/README.md", "record": f"{REPO}/agents/advocate/checks.py",
                "floor": FLOOR_URL, "unsourced": f"{REPO}/agents/advocate/checks.py",
                "recall_unknown": "https://www.cpsc.gov/Recalls"}

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
    url = url or CODE_SOURCES.get(kind) or CODE_SOURCES["unsourced"]
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
        out.append(_warn("fit", f"Does not fit: {summary}.",
                         url, bid["total_landed_price"], rule_id=fails[0]["rule_id"]))
    elif unsure:
        out.append(_warn("fit_unknown", f"{CALL_SUMMARIES['advocate.fit_unknown']}.", url, 0))
    if fit["notes"]:
        out.append(_warn("note", "The fit checker returned a non-blocking note.", url, 0))
    return out


def _card_warnings(bid, owned, baseline, records, recalls, wanted=None, evidence=None):
    out = _fit_warnings(bid, owned)
    for line in bid["lines"]:
        sku = line["sku_spec"]
        total = line["unit_price"] * line["quantity"]
        url = line.get("listing_url", "")

        # an honest offer of a different condition than asked for: caution, not a veto
        want = (wanted or {}).get(sku)
        allowed = {_norm(c) for c in (want.get("allowed_conditions") or [want.get("condition")])} if isinstance(want, dict) else {_norm(want)}
        condition = _norm(line.get("offered_condition"))
        if condition and condition not in allowed:
            out.append(_warn("spec", f"This offer's condition is not in the allowed conditions for {sku}.", url, 0))

        offered, page = _norm(line.get("offered_condition")), _norm(line.get("page_condition"))
        origin = line.get("origin") or bid.get("origin", "SIM")
        if origin == "simulated":
            origin = "SIM"
        if evidence is None:
            if offered and page and offered != page:
                out.append(_warn("condition", f"{sku} is listed as {offered}, the page says {page}. "
                                 "The condition claim did not match the listing.", url, total))
        elif origin == "SIM":
            # These repository-owned fixture pages are deterministic control cases.
            # Never treat seller-supplied page_condition on LIVE/MIRROR as evidence.
            if offered and page and offered != page:
                out.append(_warn("condition", f"{sku} is listed as {offered}, the page says {page}. "
                                 "The condition claim did not match the listing.", url, total))
        else:
            checked = evidence.get((url, line.get("offered_condition"))) if isinstance(evidence, dict) else None
            result = checked.get("result") if isinstance(checked, dict) else None
            if result == "false":
                warning = _warn("condition", f"{sku} condition claim did not match the independently checked listing.",
                                url, total)
                warning.update({k: checked[k] for k in ("checked_at", "evidence_hash") if isinstance(checked.get(k), str)})
                out.append(warning)
            elif result != "verified":
                warning = _warn("unsourced", f"The condition claim for {sku} could not be independently verified.", url, 0)
                if isinstance(checked, dict):
                    warning.update({k: checked[k] for k in ("checked_at", "evidence_hash") if isinstance(checked.get(k), str)})
                out.append(warning)

        base = baseline.get(_norm(sku))
        if base and base.get("status") not in (None, "ok"):
            span = f", observed {base['from']} to {base['to']}" if base.get("from") and base.get("to") else ""
            out.append(_warn("unsourced", f"The price history for {sku} is unconfirmed ({base['status']}{span}).",
                             base.get("source_url", ""), 0))
        elif base and line["unit_price"] > base["unit_price"] * (1 + PRICE_TOLERANCE):
            over = (line["unit_price"] - base["unit_price"]) * line["quantity"]
            out.append(_warn("price", f"{sku} at ${line['unit_price']:.2f} is above the price history baseline "
                             f"of ${base['unit_price']:.2f}; the price claim did not match the price history "
                             f"by ${over:.2f}.", base["source_url"], over))

        mirror = bid.get("origin") == "MIRROR"
        recall_rows = [r for r in recalls or [] if not mirror or r.get("origin") in ("LIVE", "MIRROR")]
        hit = next((r for r in recall_rows if r["match"] in _norm(sku)), None)
        if hit:
            out.append(_warn("recall", f"{sku} matches a CPSC recall entry ('{hit['match']}').",
                             hit["source_url"], total))
        elif mirror and not recall_rows:
            out.append(_warn("unsourced", "Recall status was not checked against a dated source.",
                             CODE_SOURCES["recall_unknown"], 0))

    rec = records.get(bid.get("seller_of_record") if bid.get("origin") == "MIRROR" else bid["supplier_id"])
    if rec and rec["record"] != "good":
        out.append(_warn("record", f"Seller {bid['supplier_id']} has a '{rec['record']}' record.",
                         rec.get("source_url", ""), 0))
    elif bid.get("origin") == "MIRROR" and not rec:
        out.append(_warn("unsourced", "No independently sourced seller record was available.",
                         CODE_SOURCES["record"], 0))

    if not bid.get("floor_check_passed", True):
        out.append(_warn("floor", "Bid did not pass the price floor check; the price may not hold.", FLOOR_URL, 0))
    return out


def _line_indices(bid):
    lines = bid.get("lines", [])
    explicit = ["line_index" in line for line in lines]
    if any(explicit) and not all(explicit):
        raise ValueError("selected line index must be present on every selected line")
    indices = [line["line_index"] for line in lines] if all(explicit) and lines else list(range(len(lines)))
    if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in indices) or len(set(indices)) != len(indices):
        raise ValueError("selected line index must be a unique nonnegative integer")
    return indices


def _claim_checks(bid, evidence):
    """Bounded normalized evidence, suitable for the market's attach_claim_check hook."""
    checks = []
    for index, line in zip(_line_indices(bid), bid.get("lines", [])):
        condition = line.get("offered_condition")
        if condition not in {"new", "open-box", "refurbished", "used"}:
            continue
        origin = line.get("origin") or bid.get("origin", "SIM")
        if origin == "simulated":
            origin = "SIM"
        url = line.get("listing_url") or ""
        if origin == "SIM":
            page = line.get("page_condition")
            if page not in {"new", "open-box", "refurbished", "used"}:
                result, source = "unverified", "SIM fixture has no condition fixture"
            else:
                result = "verified" if _norm(condition) == _norm(page) else "false"
                source = "SIM fixture page_condition (repository-owned control)"
            check = {"result": result}
        else:
            check = evidence.get((url, condition), {}) if isinstance(evidence, dict) else {}
            result = check.get("result") if check.get("result") in {"verified", "false", "unverified"} else "unverified"
            source = _check_source(check.get("method", "independent claim check"))
        row = {"bid_id": bid["id"], "line_index": index, "listing_id": line.get("listing_id", ""),
               "sku_spec": line.get("sku_spec", ""), "field": "condition", "value": condition,
               "result": result, "evidence_url": _safe_source_url(check.get("evidence_url", url)),
               "evidence_hash": check.get("evidence_hash", ""), "checked_at": check.get("checked_at", ""),
               "source": source, "origin": origin}
        checks.append(row)
        if len(checks) >= MAX_CLAIM_CHECKS:
            break
    return checks


def advise(need: dict, bids: list[dict], baseline: dict, records: dict, recalls: list[dict],
           owned: dict | None = None, evidence: dict | None = None) -> list[dict]:
    owned = owned if owned is not None else need.get("owned", {})
    wanted = {i["sku_spec"]: i for i in need.get("items", [])}
    cards = []
    for bid in bids:
        warnings = _card_warnings(bid, owned, baseline, records, recalls, wanted, evidence)
        kinds = {w["kind"] for w in warnings}  # decided before truncation so a veto is never hidden
        rec = "veto" if kinds & VETO_KINDS else "caution" if kinds - INFO_KINDS else "buy"
        reason = call_reason(warnings, bid)  # from the full list, so a veto reason is never cut
        warnings = sorted(warnings, key=lambda w: -w["dollar_impact"])[:MAX_WARNINGS]
        cards.append({"need_id": need["id"], "bid_id": bid["id"], "warnings": warnings,
                      "claim_checks": _claim_checks(bid, evidence),
                      "recommendation": rec, "wait_until": "", "call_reason": reason,
                      "rule_id": reason["rule_id"], "reason": reason["summary"],
                      "source_url": reason["source_url"]})
    return cards


def call_reason(warnings: list[dict], bid: dict) -> dict:
    """The reason Lane D's voice call may speak: exactly {rule_id, summary, source_url}. Vetoes first, then the
    biggest dollar impact. The summary is looked up by rule_id; seller text and model output never reach it."""
    ranked = sorted((w for w in warnings if w["kind"] not in INFO_KINDS),
                    key=lambda w: (w["kind"] not in VETO_KINDS, -w["dollar_impact"]))
    if not ranked:
        url = bid["lines"][0].get("listing_url") if bid.get("lines") else None
        source = url or CODE_SOURCES["unsourced"]
        return {"rule_id": "advocate.ok", "summary": CALL_SUMMARIES["advocate.ok"],
                "source_url": _safe_source_url(source)}
    w = ranked[0]
    rid = w["rule_id"] if w["rule_id"] in CALL_SUMMARIES else ("fit" if w["kind"] == "fit" else f"advocate.{w['kind']}")
    return {"rule_id": rid, "summary": CALL_SUMMARIES[rid], "source_url": _safe_source_url(w["source_url"])}


def _safe_source_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            return CODE_SOURCES["unsourced"]
        host = parsed.hostname.lower() + (f":{parsed.port}" if parsed.port else "")
        return urlunsplit((parsed.scheme, host, parsed.path[:200], "", ""))[:240]
    except (ValueError, TypeError):
        return CODE_SOURCES["unsourced"]


def _check_source(value: str) -> str:
    """Collapse checker adapter text to fixed provenance labels; never pass page prose onward."""
    if not isinstance(value, str):
        return "independent claim check"
    lowered = value.lower()
    if lowered.startswith("sim fixture"):
        return "SIM fixture page_condition (repository-owned control)"
    if lowered.startswith("fetched page"):
        return "independent listing page check"
    if lowered.startswith("could not verify"):
        return "independent listing check unavailable"
    return "independent claim check"


def validate_safety_card(card: dict) -> None:
    """Refuse any safety fields that diverge from the deterministic rule/template decision."""
    reason = card.get("call_reason")
    if not isinstance(reason, dict) or set(reason) != {"rule_id", "summary", "source_url"}:
        raise ValueError("AdvocateCard call_reason must use the closed safety shape")
    rule_id = reason["rule_id"]
    if (card.get("recommendation") not in {"buy", "caution", "veto"}
            or CALL_SUMMARIES.get(rule_id) != reason["summary"]
            or card.get("rule_id") != rule_id or card.get("reason") != reason["summary"]
            or card.get("source_url") != reason["source_url"]
            or _safe_source_url(reason["source_url"]) != reason["source_url"]):
        raise ValueError("AdvocateCard safety mirrors must match the code-owned canonical reason")


def best_bid(bids: list[dict], cards: list[dict]):
    vetoed = {c["bid_id"] for c in cards if c["recommendation"] == "veto"}
    ok = [b for b in bids if b["id"] not in vetoed]
    return min(ok, key=lambda b: b["total_landed_price"]) if ok else None
