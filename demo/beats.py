"""Beats 2 and 3: the sealed round with the advocate's veto, and Shield blocking an injected listing."""
from __future__ import annotations

from datetime import datetime

from demo.common import LIVE, MIRROR, PAGE_BASE, SIM, SITE, money, schema_errors, validate
from demo.pages import read_page
from demo.round import run_round
from demo.sellers import Seller, all_sellers
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
               "REAL data.fit_checker + shield.screen; claim check: " + res["claim_check"]["label"]
               + "; SIM stand-ins for Lane A sellers and advocate, Lane B market rules")
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
        say.line(b["origin"], f"{s.name}: " + " | ".join(_fmt_line(l) for l in b["lines"]), 0)
        say.line(b["origin"], f"{where}  {anchor.listing_url}", 2)
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
                  + ("" if allow == len(res["shield"]) else "; held: " + ", ".join(v["seller_id"] for v in res["shield"] if v["verdict"] != "allow")))
    unverified = sum(1 for cs in res["claims"].values() for c in cs if c["check"] == "unverified")
    say.line(SIM, f"claims checked: {sum(1 for cs in res['claims'].values() for c in cs if c['check'] == 'verified')} verified, "
                  f"{sum(1 for cs in res['claims'].values() for c in cs if c['check'] == 'false')} false, {unverified} unverified "
                  f"(offline: only the hosted SIM pages can be fetched, every other claim stays unverified)")
    say.blank()
    say.note(f"Score: quality-adjusted landed price (SIM weights), cap {money(goal['cap'])} withheld from sellers")
    for r in res["ranking"]["ranked"]:
        s = by_id[r["seller_id"]]
        say.line(bids[s.id]["origin"], f"#{r['rank']} {s.name}: {r['condition']}, landed {money(r['landed'])}, adjusted {money(r['adjusted'])}", 1)
    for d in res["ranking"]["disqualified"]:
        s = by_id[d["seller_id"]]
        say.line(bids[s.id]["origin"], f"out: {s.name}: {'; '.join(d['reasons'])}", 1)
    real_min = min(l["unit_price"] for b in res["bids"] for l in b["lines"] if l["origin"] == MIRROR and l["offered_condition"] != "unknown") if any(
        l["origin"] == MIRROR for b in res["bids"] for l in b["lines"]) else None
    if real_min:
        say.line(MIRROR, f"cheapest real listing with a stated condition today: {money(real_min)}; every MIRROR bid is over Joe's cap, "
                         f"so only SIM sellers can win this round (labelled, never mixed into real numbers)")
    say.blank()
    say.note("Advocate (code decides fit, claims come from their pages, no model, every veto cites a source):")
    for r, card in zip(res["ranking"]["ranked"], res["cards"]):
        s = by_id[r["seller_id"]]
        tag = bids[s.id]["origin"]
        verdict = {"veto": "VETO", "caution": "CAUTION", "buy": "OK"}[card["recommendation"]]
        say.line(tag, f"#{r['rank']} {s.name} {money(r['landed'])}: {verdict}", 1)
        for w in card["warnings"]:
            if w["kind"] == "fit_unknown":
                continue
            say.line(tag, f"{w['rule_id']}: {w['text']}", 3)
            say.line(tag, f"source: {w['source_url']}", 4)
        if card["recommendation"] == "buy":
            fit = card["fit"]
            say.line(tag, "fit " + fit["verdict"] + ": " + "; ".join(c["reason"] for c in fit["checks"]), 3)
            cs = res["claims"][r["bid_id"]]
            say.line(tag, f"claims: {sum(1 for c in cs if c['check'] == 'verified')} of {len(cs)} verified against the page", 3)
    w = res["winner"]
    winner_seller = by_id[w["seller_id"]]
    say.blank()
    cheapest = res["ranking"]["ranked"][0]
    say.line(SIM, f"winner: {winner_seller.name} at {money(w['landed'])}; the cheaper {by_id[cheapest['seller_id']].name} "
                  f"({money(cheapest['landed'])}) was vetoed under {res['cards'][0]['call_reason']['rule_id']}")
    return {"sellers": [_seller_artifact(s) for s in sellers], "skips": skips, **res,
            "veto_reason": res["cards"][0]["call_reason"] if res["cards"] and res["cards"][0]["recommendation"] == "veto" else None,
            "winner_seller_id": w["seller_id"]}


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
