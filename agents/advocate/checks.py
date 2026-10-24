"""Quality Advocate checks: pure and deterministic. One AdvocateCard per bid.

Inputs (shapes in mock_data.py):
  baseline: {sku_spec: {"unit_price": float, "source_url": str}}   (USDA-style, Lane C)
  signals:  {supplier_id: SupplierSignal + "source_url"}            (CRS, Lane D)
  recalls:  ["romaine", ...] lowercase substrings matched against bid line sku_spec

Spec rule: bid lines line up with need items by index. A line is a swap if its sku_spec
differs from the need item's (case/space-insensitive), or the bid's decision_trace says
"swap" or "substitut". Grade and pack are part of the agreed sku_spec text.
"""
PRICE_TOLERANCE = 0.10
RECALL_URL = "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts"
FLOOR_URL = "https://www.ams.usda.gov/market-news"
MAX_WARNINGS = 3


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _warn(kind, text, url, dollars):
    return {"kind": kind, "text": text, "source_url": url, "dollar_impact": round(float(dollars), 2)}


def _card_warnings(need, bid, baseline, signals, recalls):
    out = []
    items = need["items"]
    trace = bid.get("decision_trace", "").lower()
    traced_swap = "swap" in trace or "substitut" in trace
    # flag only the lines the trace names; if it names none, flag every line
    named = {l["sku_spec"] for l in bid["lines"] if l["sku_spec"].lower() in trace} if traced_swap else set()
    for i, line in enumerate(bid["lines"]):
        item = items[i] if i < len(items) else None
        want = item["sku_spec"] if item else line["sku_spec"]
        line_total = line["unit_price"] * line["quantity"]
        base = baseline.get(want) or baseline.get(line["sku_spec"])

        swapped = traced_swap and (line["sku_spec"] in named or not named)
        if item and (_norm(line["sku_spec"]) != _norm(want) or swapped):
            # the supplier's own trace says what it swapped in, e.g. "offered US No. 2 instead of requested US No. 1"
            said = next((s.split(":", 1)[-1].strip() for s in bid.get("decision_trace", "").split(";")
                         if line["sku_spec"].lower() in s.lower() and "offered" in s.lower()), f"'{line['sku_spec']}'")
            out.append(_warn("spec", f"Asked for {want} ({item['grade']}, {item['pack_size']}); bid {said}. "
                             f"Not what you ordered.",
                             base["source_url"] if base else FLOOR_URL, line_total))

        if base and line["unit_price"] > base["unit_price"] * (1 + PRICE_TOLERANCE):
            over = (line["unit_price"] - base["unit_price"]) * line["quantity"]
            out.append(_warn("price", f"{line['sku_spec']} at ${line['unit_price']:.2f}/unit vs USDA "
                             f"${base['unit_price']:.2f}: you overpay ${over:.2f}.", base["source_url"], over))

        hit = next((r for r in recalls if r.lower() in line["sku_spec"].lower()), None)
        if hit:
            out.append(_warn("recall", f"{line['sku_spec']} matches an active recall ('{hit}').",
                             RECALL_URL, line_total))

    sig = signals.get(bid["supplier_id"])
    if sig and sig["stability"] in ("caution", "not_verified"):
        out.append(_warn("stability", f"Supplier {bid['supplier_id']} stability is '{sig['stability']}'.",
                         sig.get("source_url", ""), 0))

    if not bid["floor_check_passed"]:
        out.append(_warn("floor", "Bid failed the price-floor check; the price may not hold.", FLOOR_URL, 0))
    return out


def advise(need: dict, bids: list[dict], baseline: dict, signals: dict, recalls: list[str]) -> list[dict]:
    cards = []
    for bid in bids:
        warnings = _card_warnings(need, bid, baseline, signals, recalls)
        kinds = {w["kind"] for w in warnings}  # decided before truncation so a veto is never hidden
        rec = "veto" if kinds & {"spec", "recall"} else "caution" if warnings else "buy"
        warnings = sorted(warnings, key=lambda w: -w["dollar_impact"])[:MAX_WARNINGS]
        cards.append({"need_id": need["id"], "bid_id": bid["id"], "warnings": warnings,
                      "recommendation": rec, "wait_until": ""})
    return cards


def best_bid(bids: list[dict], cards: list[dict]):
    vetoed = {c["bid_id"] for c in cards if c["recommendation"] == "veto"}
    ok = [b for b in bids if b["id"] not in vetoed]
    return min(ok, key=lambda b: b["total_landed_price"]) if ok else None
