"""Quality Advocate checks for Tech Bazaar: pure and deterministic. One AdvocateCard per bid.

Bid line: {sku_spec, unit_price, quantity, offered_condition, page_condition, listing_url, attrs}; attrs carry
`category` and SpecCard attr names. Need item: {sku_spec, condition, variant, quantity}. owned: the buyer's parts
as {category: SpecCard attrs}, e.g. {"psu": {"wattage": 750}, "case": {"max_gpu_length_mm": 330}}.
Fit is Lane C's checker (data.fit_checker), run once per bid on the bid's parts plus the owned parts.
Fee fields are ignored: the advocate never sees a fee. Text rule: neutral wording ("did not match"), no en/em dashes.
"""
import common  # noqa: F401  (puts the repo root on sys.path for data.*)
from data.fit_checker import check_fit

PRICE_TOLERANCE = 0.10
FLOOR_URL = "https://example.com/price-floor/simulated"
MAX_WARNINGS = 3
VETO_KINDS = {"condition", "fit", "recall"}
INFO_KINDS = {"note"}  # shown, but never change the recommendation


def _norm(s) -> str:
    return " ".join(str(s or "").lower().replace("-", " ").replace("_", " ").split())


def _warn(kind, text, url, dollars):
    return {"kind": kind, "text": text.replace("—", ",").replace("–", " to "),
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
        out.append(_warn("fit", f"Does not fit: {'; '.join(c['reason'] for c in fails)} (rule {fails[0]['rule_id']}).",
                         url, bid["total_landed_price"]))
    elif unsure:
        out.append(_warn("fit_unknown", f"Fit not confirmed: {'; '.join(c['reason'] for c in unsure)}.", url, 0))
    if fit["notes"]:
        out.append(_warn("note", "; ".join(fit["notes"]) + ".", url, 0))
    return out


def _card_warnings(bid, owned, baseline, records, recalls, wanted=None):
    out = _fit_warnings(bid, owned)
    for line in bid["lines"]:
        sku = line["sku_spec"]
        total = line["unit_price"] * line["quantity"]
        url = line.get("listing_url", "")

        # an honest offer of a different condition than asked for: caution, not a veto
        asked = _norm((wanted or {}).get(sku))
        if asked and _norm(line.get("offered_condition")) not in ("", asked):
            out.append(_warn("spec", f"You asked for {asked}; this offer is {_norm(line['offered_condition'])}.",
                             url, 0))

        offered, page = _norm(line.get("offered_condition")), _norm(line.get("page_condition"))
        if offered and page and offered != page:
            out.append(_warn("condition", f"{sku} is listed as {offered}, the page says {page}. "
                             "The condition claim did not match the listing.", url, total))

        base = baseline.get(_norm(sku))
        if base and line["unit_price"] > base["unit_price"] * (1 + PRICE_TOLERANCE):
            over = (line["unit_price"] - base["unit_price"]) * line["quantity"]
            out.append(_warn("price", f"{sku} at ${line['unit_price']:.2f} is above the price history baseline "
                             f"of ${base['unit_price']:.2f}; the price claim did not match the price history "
                             f"by ${over:.2f}.", base["source_url"], over))

        hit = next((r for r in recalls if r["match"] in _norm(sku)), None)
        if hit:
            out.append(_warn("recall", f"{sku} matches a CPSC recall entry ('{hit['match']}').",
                             hit["source_url"], total))

    rec = records.get(bid["supplier_id"])
    if rec and rec["record"] != "good":
        out.append(_warn("record", f"Seller {bid['supplier_id']} has a '{rec['record']}' record.",
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
        warnings = sorted(warnings, key=lambda w: -w["dollar_impact"])[:MAX_WARNINGS]
        cards.append({"need_id": need["id"], "bid_id": bid["id"], "warnings": warnings,
                      "recommendation": rec, "wait_until": ""})
    return cards


def best_bid(bids: list[dict], cards: list[dict]):
    vetoed = {c["bid_id"] for c in cards if c["recommendation"] == "veto"}
    ok = [b for b in bids if b["id"] not in vetoed]
    return min(ok, key=lambda b: b["total_landed_price"]) if ok else None
