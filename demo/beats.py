"""Beats 2 and 3: the sealed round with the advocate's veto, and Shield blocking an injected listing."""
from __future__ import annotations

from datetime import datetime

from demo.adapters import advocate_checks
from demo.common import MIRROR, PAGE_BASE, SIM, SITE, money, validate
from demo.pages import read_page
from demo.round import caught_label, landed_note, run_round
from demo.sellers import Seller, all_sellers
from shield.classifier import UNAVAILABLE_RULE
from shield.core import screen
from shield.service import attack_type


def owned_attrs(owned: list[dict]) -> dict:
    """What the advocate gets for fit checks: {"psu": {...}, "case": {...}} keyed by the part kind."""
    return {o["sku_spec"].split()[0]: o["attrs"] for o in owned}


def _fmt_line(l: dict) -> str:
    kind = l["origin"] if l["origin"] == MIRROR else "SIM-derived" if "derived" in l["basis"] else "SIM"
    return f"{l['offered_condition']} {l['unit_price']:,.2f} ({kind})"


def run_beat2(b1: dict, now: datetime, say, round_no: int = 1) -> dict:
    sellers, skips = all_sellers()
    need, goal = b1["need"], b1["goal"]
    res = run_round(need, sellers, owned_attrs(b1["owned_parts"]), goal["cap"], now, round_no)
    by_id = {s.id: s for s in sellers}
    bids = {b["seller_id"]: b for b in res["bids"]}
    say.header(2, "Sealed round: sellers bid, the advocate vetoes the traps with a source",
               "REAL agents/advocate/checks.py (" + ("uagents-free load" if "empty module" in advocate_checks()[1] else "direct") + "), data.fit_checker, "
               + "shield.screen; claim check: " + res["claim_check"]["label"]
               + "; SIM stand-ins for Lane A seller bids and Lane B market rules (Python, node not installed)")
    dates = sorted({l.snapshot_date[:16] for sl in sellers for l in sl.lines if l.snapshot_date})
    say.line(MIRROR, f"listings read from data/mirror/snapshots (Apify, dated {dates[0]}Z to {dates[-1]}Z), one agent per seller of record")
    for s in skips:
        say.line(MIRROR, s, 1)
    say.blank()
    say.note("Sealed bids, arrival order (a seller sees only its own bid until close):")
    for s in sorted(sellers, key=lambda x: x.learning):
        b = bids[s.id]
        anchor = next((l for l in s.lines if l.origin == MIRROR), s.lines[0])
        where = (f"snapshot {anchor.snapshot_id}" if anchor.origin == MIRROR
                 else "hosted SIM page" if s.page_html else "SIM listing, no page hosted")
        alt = "  (alternatives, the market takes the cheapest allowed)" if len(b["lines"]) > 1 else ""
        say.line(b["origin"], f"{s.name}: " + " | ".join(_fmt_line(l) for l in b["lines"]) + alt, 0)
        say.line(b["origin"], f"{where}  {anchor.listing_url}", 2)
        for w in b.get("withheld_lines", []):
            say.line(b["origin"], f"withheld {w['model']} at {w['unit_price']:,.2f}: {w['reason']} (rule {w['rule_id']})", 2)
            say.line(b["origin"], f"maker spec: {w['source_url']}", 3)
    arrival_ext = [a for a in res["arrivals"] if a["extended"]]
    say.blank()
    vis = res["visibility"]
    say.line(SIM, f"round clock: {vis['bids_sealed']} bids sealed; public sees {vis['before_close']['public']} before close and "
                  f"{vis['after_close']} after; every seller sees {max(vis['each_seller_sees'].values())} (its own)")
    for a in arrival_ext:
        say.line(SIM, f"anti-snipe: {a['seller_id']} sealed at {a['at_ms'] / 1000:.1f}s, deadline extended to {a['deadline_ms'] / 1000:.1f}s "
                      f"(capped at 2 extensions)")
    for r in res["referee"]:
        if not r["passed"]:
            say.line(SIM, f"referee: {by_id[r['seller_id']].name} rejected before anyone saw it: {'; '.join(r['reasons'])}")
    ok = sum(1 for r in res["referee"] if r["passed"])
    say.line(SIM, f"referee: {ok} of {len(res['referee'])} bids pass the floor and quantity rules (the market holds the floors)")
    allow = sum(1 for v in res["shield"] if v["verdict"] == "allow")
    say.line(SIM, f"Shield (REAL shield.screen on each seller's text before the advocate): {allow} of {len(res['shield'])} allow"
                  + ("" if allow == len(res["shield"]) else "; held: " + ", ".join(
                      f"{v['seller_id']} ({', '.join(v['rule_ids'])})" for v in res["shield"] if v["verdict"] != "allow")))
    unverified = sum(1 for cs in res["claims"].values() for c in cs if c["check"] == "unverified")
    say.line(SIM, f"claims checked: {sum(1 for cs in res['claims'].values() for c in cs if c['check'] == 'verified')} verified, "
                  f"{sum(1 for cs in res['claims'].values() for c in cs if c['check'] == 'false')} false, {unverified} unverified "
                  f"(offline: only the hosted SIM pages can be fetched, so claims on real listings stay unverified, never false)")
    say.blank()
    say.note(f"Score: the cheapest allowed line per bid, then quality-adjusted landed price (SIM weights), cap {money(goal['cap'])} withheld from sellers")
    for r in res["ranking"]["ranked"]:
        s = by_id[r["seller_id"]]
        alt = f" (picked of {len(r['alternatives'])} lines)" if len(r["alternatives"]) > 1 else ""
        say.line(bids[s.id]["origin"], f"#{r['rank']} {s.name}: {r['condition']}{alt}, landed {money(r['landed'])}, adjusted {money(r['adjusted'])}", 1)
    for d in res["ranking"]["disqualified"]:
        s = by_id[d["seller_id"]]
        say.line(bids[s.id]["origin"], f"out: {s.name}: {'; '.join(d['reasons'])}", 1)
    real_in = [r for r in res["ranking"]["ranked"] if by_id[r["seller_id"]].origin == MIRROR]
    if real_in:
        say.line(MIRROR, f"real bids inside the cap: " + ", ".join(f"{by_id[r['seller_id']].name} {r['condition']} {money(r['landed'])}" for r in real_in)
                         + f"; the other real listings are over the cap or state no condition (labelled MIRROR, never mixed with SIM numbers)")
    say.blank()
    say.note("Advocate (code decides fit, claims come from their pages, no model, every veto cites a source):")
    for r, card in zip(res["ranking"]["ranked"], res["cards"]):
        s = by_id[r["seller_id"]]
        tag = bids[s.id]["origin"]
        verdict = {"veto": "VETO", "caution": "CAUTION", "buy": "OK"}[card["recommendation"]]
        say.line(tag, f"#{r['rank']} {s.name} {money(r['landed'])}: {verdict}", 1)
        for w in card["warnings"]:
            if w["kind"] == "note":
                continue
            say.line(tag, f"{w['rule_id']}: {w['text']}", 3)
            say.line(tag, f"source: {w['source_url']}", 4)
        if card["recommendation"] != "veto":
            fit = card["fit"]
            say.line(tag, "fit " + fit["verdict"] + ": " + "; ".join(c["reason"] for c in fit["checks"]), 3)
            cs = res["claims"][r["bid_id"]]
            say.line(tag, f"claims: {sum(1 for c in cs if c['check'] == 'verified')} of {len(cs)} verified (the rest could not be fetched offline)", 3)
    for e in res["caught"]:   # option C: Shield held the bid (never ranked, never payable), the advocate still judged it
        s, card = by_id[e["seller_id"]], e["card"]
        tag = bids[s.id]["origin"]
        say.blank()
        say.line(tag, f"{caught_label(e)}: {s.name} {money(e['landed'])}, rule {e['rule']}; never ranked, never payable", 1)
        say.line(tag, f"the advocate still judged it: {card['recommendation'].upper()}", 1)
        for w in card["warnings"]:
            if w["kind"] == "note":
                continue
            say.line(tag, f"{w['rule_id']}: {w['text']}", 3)
            say.line(tag, f"source: {w['source_url']}", 4)
    w = res["winner"]
    say.blank()
    winner_seller = by_id[w["seller_id"]] if w else None
    if w is None:   # nothing survived (for example the classifier down for every seller): there is nothing to rank or pay
        if res["shield"] and all(UNAVAILABLE_RULE in v["rule_ids"] for v in res["shield"]):
            say.line(SIM, f"no seller could be screened: the Shield classifier was unavailable for all {len(res['shield'])} sellers, "
                          "so every bid was held closed; nothing is ranked or paid and there is no winner")
        else:
            say.line(SIM, "no winner: no bid survived Shield, the referee and the advocate; nothing is ranked or paid")
    else:
        vetoed = [(r["landed"], by_id[r["seller_id"]].name + f" ({money(r['landed'])}, {c['call_reason']['rule_id']})")
                  for r, c in zip(res["ranking"]["ranked"], res["cards"]) if c["recommendation"] == "veto" and r["rank"] < w["rank"]]
        vetoed += [(e["landed"], by_id[e["seller_id"]].name + f" ({money(e['landed'])}, {e['card']['call_reason']['rule_id']}, "
                    + ("held by Shield (classifier unavailable)" if e["rule"] == UNAVAILABLE_RULE else "caught by Shield") + ")")
                   for e in res["caught"] if e["card"]["recommendation"] == "veto" and e["landed"] < w["landed"]]
        say.line(winner_seller.origin, f"winner: {winner_seller.name} at {landed_note(winner_seller, w['landed'])}; vetoed as cheaper: "
                 + "; ".join(t for _, t in vetoed))
    first = min([(r["landed"], c) for r, c in zip(res["ranking"]["ranked"], res["cards"])] + [(e["landed"], e["card"]) for e in res["caught"]],
                key=lambda t: t[0], default=(0, None))[1]
    return {"sellers": [_seller_artifact(s) for s in sellers], "skips": skips, **res,
            "veto_reason": first["call_reason"] if first and first["recommendation"] == "veto" else None,
            "winner_seller_id": w["seller_id"] if w else None,
            "winner_note": landed_note(winner_seller, w["landed"]) if w else None}


def _seller_artifact(s: Seller) -> dict:
    """Seller side of the round for Lane B's screens: origin badge, listing URL, floor per line."""
    return {"id": s.id, "name": s.name, "origin": s.origin, "payee": s.payee, "learning": s.learning, "control": s.control,
            "returns_days": s.returns_days, "record": s.record, "note": s.note,
            "lines": [{"condition": l.condition, "origin": l.origin, "list_price": l.list_price, "floor": l.floor,
                       "listing_url": l.listing_url, "snapshot_id": l.snapshot_id, "snapshot_date": l.snapshot_date, "basis": l.basis}
                      for l in s.lines]}


INJECTED_PAGE = "shady-sam-gpu-5070ti-injected.html"
CLEAN_PAGE = "honest-hal-gpu-5070ti.html"


def _price_history() -> list[dict]:
    import json
    return json.loads((SITE / "price_history.json").read_text(encoding="utf-8"))["series"]["gpu-5070ti"]


def _screen_page(name: str, seller: str, payee: str, with_history: bool) -> dict:
    ctx = {"sender_role": "seller", "payee_of_record": payee, **({"price_history": _price_history()} if with_history else {})}
    html = read_page(name)
    v = screen(html, ctx)
    out = {"page": name, "url": PAGE_BASE + name, "seller_id": seller, "chars": len(html), "context_keys": sorted(ctx),
           "verdict": v["verdict"], "reasons": list(v["rule_ids"]), "attack_type": attack_type(v["rule_ids"]),
           "latency_ms": v["latency_ms"], "message_id": f"msg-{name}", "sender_agent": seller,
           "rule_ids": list(v["rule_ids"]), "severity": v["severity"], "evidence_spans": v["evidence_spans"],
           "version": v["version"], "request_id": v["request_id"]}
    legacy = {k: out[k] for k in ("message_id", "sender_agent", "verdict", "reasons", "attack_type", "latency_ms")}
    validate("ShieldVerdict", legacy)
    return out


def run_beat3(say) -> dict:
    import json
    sellers = json.loads((SITE / "sellers.json").read_text(encoding="utf-8"))["sellers"]
    bad = _screen_page(INJECTED_PAGE, "shady-sam", sellers["shady-sam"]["payee"], True)
    good = _screen_page(CLEAN_PAGE, "honest-hal", sellers["honest-hal"]["payee"], False)
    say.header(3, "Shield blocks an injected listing", "REAL shield.screen (Lane D), rules as files in shield/rules")
    say.line(SIM, f"Shady Sam (SIM) posts a new version of his listing: {bad['url']}")
    say.line(SIM, f"message: {bad['chars']} characters of page text; context: payee of record {sellers['shady-sam']['payee']} "
                  f"and the dated price history")
    say.line(SIM, f"verdict: {bad['verdict'].upper()}  severity {bad['severity']}  {bad['latency_ms']} ms  {bad['version']}")
    say.line(SIM, "rule ids: " + ", ".join(bad["rule_ids"]))
    say.line(SIM, "evidence spans (rule, chars, text from the page itself):")
    shown = {}
    for sp in bad["evidence_spans"]:
        if shown.get(sp["rule_id"], 0) < 1:
            shown[sp["rule_id"]] = shown.get(sp["rule_id"], 0) + 1
            say.line(SIM, f"{sp['rule_id']}  [{sp['start']}:{sp['end']}]  {sp['text']!r}", 1)
    say.line(SIM, "the advocate never reads this page: the bid is quarantined and the round goes on without it")
    say.line(SIM, f"control: Honest Hal's clean page {good['url']} -> {good['verdict'].upper()} "
                  f"({', '.join(good['rule_ids']) or 'no rule fired'})")
    return {"injected": bad, "control": good, "blocked": bad["verdict"] == "block", "origin": SIM}
