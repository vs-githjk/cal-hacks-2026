"""ASI:One questions to the Advocate: "is this card worth it?", "will it fit my case?". The answer runs the SAME checks as a
bid (checks.advise: price history, fit, recall, condition, then tco.rank), on a one-line bid built from the user's words.
Reading the question is regex, not a model. The model may only reword the one-sentence explanation (phrasing.phrase).
Nothing here buys anything or approves a purchase.
"""
from __future__ import annotations

import asyncio
import re

import phrasing
from advocate import checks, clarify, explain, real_data
from data.fit_checker import tables
from data.fit_checker.gpu_lengths import maker_length

CHAT_SELLER = "chat_seller"
SKUS = {"rtx 5070 ti": "rtx 5070 ti", "rtx 4070 super": "rtx 4070 super 12gb"}  # the two cards the buyer shops for
HELP = ("Tell me the card (for example RTX 4070 Super), the price and its condition, and for fit your case's GPU clearance in mm "
        "and your PSU watts. I check price history, recalls, fit and total cost with the same code my vetoes use. "
        "I cannot buy anything; send goals to @techbazaarbuyer.")
_GPU = re.compile(r"\b(RTX|RX|GTX)\s*(\d{3,4})(?:\s*(Ti|SUPER|XTX|XT|GRE))?\b", re.I)
_PRICE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
_LENGTH = re.compile(r"(\d{3})\s*mm\s*(?:long|length)|(?:length|long)\s*(?:of\s*|is\s*)?(\d{3})\s*mm", re.I)
_CLEAR = re.compile(r"(\d{3})\s*mm\s*(?:of\s*)?(?:gpu\s*)?clearance|clearance\s*(?:of\s*|is\s*)?(\d{3})\s*mm", re.I)
_CASE_MM = re.compile(r"\bcase\b[^.;?]*?(\d{3})\s*mm|(\d{3})\s*mm\s*(?:gpu\s*)?case\b", re.I)
_PSU = re.compile(r"(\d{3,4})\s*-?\s*w(?:atts?)?\b[^.;,?]*?(?:psu|power supply)|(?:psu|power supply)[^.;,?]*?(\d{3,4})\s*-?\s*w(?:atts?)?\b", re.I)
_CARD_8PIN = re.compile(r"(?:needs|requires|uses)\s*(\d)\s*x?\s*8[- ]?pin", re.I)
_PSU_8PIN = re.compile(r"(?:psu|power supply)[^.;?]*?(?:has|with)\s*(\d)\s*x?\s*(?:pcie\s*)?8[- ]?pin", re.I)
_WARRANTY = re.compile(r"(\d+)\s*[- ]?(year|yr|month|mo)s?\s*(?:of\s*)?warranty|warranty\s*(?:of\s*)?(\d+)\s*[- ]?(year|yr|month|mo)", re.I)
_RETURNS = re.compile(r"(\d+)\s*[- ]?day\s*(?:return|refund)s?|returns?\s*(?:window\s*)?(?:of\s*)?(\d+)\s*days?", re.I)
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)


def _first(m, *groups):
    return next((g for g in (m.group(i) for i in groups) if g), None) if m else None


def _chipset(text):
    m = _GPU.search(text)
    if not m:
        return None
    raw = " ".join(p for p in (m.group(1).upper(), m.group(2), m.group(3)) if p)
    key = raw.lower()
    for name in tables.GPU_POWER:  # the checker's own spelling (RTX 5070 Ti, RTX 4070 SUPER)
        if name.lower() == key:
            return name
    return raw


def parse(text: str) -> dict:
    """What the question says about the card. Missing facts stay None: nothing is guessed."""
    out = {"chipset": _chipset(text), "price": None, "condition": clarify.parse_answer(text), "warranty_months": None,
           "return_window_days": None, "length_mm": None, "length_source": None, "psu_w": None, "case_mm": None,
           "url": None, "card_8pin": None, "psu_8pin": None}
    if m := _PRICE.search(text):
        out["price"] = float(m.group(1).replace(",", ""))
    if m := _WARRANTY.search(text):
        n, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out["warranty_months"] = int(n) * (12 if unit.lower() in ("year", "yr") else 1)
    if m := _RETURNS.search(text):
        out["return_window_days"] = int(_first(m, 1, 2))
    if n := _first(_LENGTH.search(text), 1, 2):
        out["length_mm"] = int(n)
    elif out["chipset"] == "RTX 5070 Ti" and (row := maker_length(text)):  # the maker table covers 5070 Ti titles only
        out["length_mm"], out["length_source"] = row["length_mm"], row["source"]
    if n := _first(_CLEAR.search(text), 1, 2):
        out["case_mm"] = int(n)
    else:  # "my 330 mm case": never the card's own length
        out["case_mm"] = next((int(n) for m in _CASE_MM.finditer(text)
                               if (n := _first(m, 1, 2)) and int(n) != out["length_mm"]), None)
    if n := _first(_PSU.search(text), 1, 2):
        out["psu_w"] = int(n)
    if n := _first(_CARD_8PIN.search(text), 1):
        out["card_8pin"] = int(n)
    if n := _first(_PSU_8PIN.search(text), 1):
        out["psu_8pin"] = int(n)
    if m := _URL.search(text):
        out["url"] = m.group(0).rstrip(".,;)")
    return out


def build(facts: dict) -> tuple[dict, list[dict], dict]:
    """(need, [bid], owned): one line, the same shape the buyer sends the advocate."""
    chip = facts["chipset"]
    sku = SKUS.get(chip.lower(), chip.lower()) if chip else "gpu"
    attrs = {"category": "gpu", "chipset": chip}
    if facts["length_mm"]:
        attrs["length_mm"] = facts["length_mm"]
    if facts["card_8pin"]:
        attrs["power_connector"] = ["8pin", facts["card_8pin"]]
    owned = {}
    if facts["psu_w"] or facts["psu_8pin"]:
        owned["psu"] = {**({"wattage": facts["psu_w"]} if facts["psu_w"] else {}),
                        **({"pcie_8pin": facts["psu_8pin"]} if facts["psu_8pin"] else {})}
    if facts["case_mm"]:
        owned["case"] = {"max_gpu_length_mm": facts["case_mm"]}
    price = facts["price"] or 0.0
    line = {"sku_spec": sku, "unit_price": price, "quantity": 1, "offered_condition": facts["condition"] or "unknown",
            "page_condition": "", "listing_url": facts["url"] or "", "attrs": attrs}
    if facts["warranty_months"] is not None:
        line["warranty_months"] = facts["warranty_months"]
    if facts["return_window_days"] is not None:
        line["return_window_days"] = facts["return_window_days"]
    need = {"id": "chat", "owned": owned, "items": [{"sku_spec": sku, "condition": facts["condition"], "variant": "", "quantity": 1}]}
    bid = {"id": "chat-bid", "need_id": "chat", "supplier_id": CHAT_SELLER, "origin": "SIM", "lines": [line],
           "total_landed_price": price, "floor_check_passed": True}
    return need, [bid], owned


def _fit_line(bid, owned) -> str:
    """The fit verdict in words, from the checker's own reasons (rule templates and our tables, never the user's text)."""
    relevant, _ = checks.fit_checks(bid, owned)
    fails = [c for c in relevant if c["verdict"] == "fail"]
    unsure = [c for c in relevant if c["verdict"] == "uncertain"]
    if fails:
        summary = checks.CALL_SUMMARIES.get(fails[0]["rule_id"], checks.CALL_SUMMARIES["fit"])
        return f"Fit: {summary.lower()} ({fails[0]['reason']}), so it will not fit."
    if unsure:
        return "Fit: not confirmed. Still unknown: " + "; ".join(c["reason"] for c in unsure[:3]) + "."
    if relevant:
        return "Fit: it fits your case and power supply by the checker's rules."
    return "Fit: tell me your case's GPU clearance in mm and your PSU watts and I will check it."


async def answer(text: str, *, inputs=None, phrase=phrasing.phrase) -> str:
    """The Advocate's reply to a worth-it or fit question. `inputs(need, bids)` returns the same four things
    real_data.advice_inputs gives checks.advise (injected in tests; a failed lookup means no price or recall check)."""
    facts = parse(text)
    if not facts["chipset"]:
        return HELP
    need, bids, owned = build(facts)
    try:
        baseline, records, recalls, notes = await asyncio.to_thread(inputs or real_data.advice_inputs, need, bids)
    except Exception:
        baseline, records, recalls = {}, {}, []
        notes = [real_data._note("advocate.lookup_unverified",
                                 "Price history and recall lookups could not run, so those checks were not made.")]
    cards = checks.advise(need, bids, baseline, records, recalls, owned)
    card = explain.attach(real_data.with_notes(cards, notes)[0])  # notes are info warnings: the explanation is rebuilt, the decision is not
    parts = [phrase(card["explanation"]), _fit_line(bids[0], owned)]
    if facts["price"]:
        parts.append(f"Worth it: {card['worth_it_note']}")
    else:
        parts.append("Worth it: give me the price and I will weigh it against price history, warranty, returns and condition.")
    sources = [card["source_url"]] + ([facts["length_source"]] if facts["length_source"] else [])
    parts.append("Source: " + ", ".join(dict.fromkeys(sources)))
    parts.append("Advice only: I checked price history, recalls, fit and condition with code, and I cannot buy or approve anything.")
    return "\n".join(parts)
