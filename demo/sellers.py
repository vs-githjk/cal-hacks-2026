"""Beat 2, step 1: seller agents and their sealed bids. SIM stand-in for agents/sellers (Lane A, not merged).

Seller model (LOCKED Fri 22:36): one agent per SELLER OF RECORD, several condition lines for the same SKU inside
one sealed bid. Prices come from a deterministic policy (list price less a discount, never below the floor),
never from a model. Mirrors origin/agents agents/sellers/policy.py make_bid.

MIRROR agents bid from real, dated listings in data/mirror/snapshots (listing URL and snapshot id on every line).
They never get an invented line: a real seller bids only the conditions its real listings show. SIM sellers are
ours: Shady Sam from Lane C's hosted pages (data/liar_pages/site) and four more labelled SIM, priced inside the real
market band ($1,200 to $1,300 at the retailers on Oct 24) so one real seller can win honestly. Sam's page is
Lane C's and shows $789, so he is the "too good to be true" trap. Honest Hal's page is used by beat 3 only: at $789
his honest listing would undercut every real seller, so he does not bid in the market round.
Seller model (LOCKED): the lines of one bid are ALTERNATIVES for the same SKU; the market takes the cheapest line
whose condition the goal allows. Gadget Grove (Vedant, a SIM seller) carries two lines, new and open-box.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from demo.common import MIRROR, PAGE_BASE, SIM, SITE, SNAPSHOTS, SOURCE_OF, utc_iso
from demo.pages import page_listing, read_page

SKU = "rtx 5070 ti"
CHIPSET = "RTX 5070 Ti"
FLOOR_OF_LIST = 0.93  # a MIRROR agent never bids below 93 percent of its listed price (SIM assumption)
POLICY_SOURCE = "https://github.com/vs-githjk/cal-hacks-2026/blob/main/demo/sellers.py"

SELLER_OF_RECORD = {  # snapshot file prefix -> operator-grouped direct retailer, not marketplace labels
    "bestbuy": "Best Buy",
    "microcenter": "Micro Center",
    "bh": "B&H Photo",
}
STORE_LABELS = {"amazon": "Amazon.com", "ebay_live": "eBay"}


@dataclass
class Line:
    condition: str                 # what is offered: new, open-box, refurbished, used, unknown
    list_price: float
    floor: float
    listing_url: str
    origin: str                    # MIRROR (real listing) or SIM (derived or simulated)
    basis: str                     # one line saying where the number comes from
    page_condition: Optional[str] = None   # what the listing page itself shows
    attrs: dict = field(default_factory=dict)
    snapshot_id: str = ""
    snapshot_date: str = ""
    discount: float = 0.0
    bid_override: Optional[float] = None   # a rogue agent that ignores its floor (demo of the referee)
    listing_id: Optional[str] = None
    seller_of_record: Optional[str] = None


@dataclass
class Seller:
    id: str
    name: str
    origin: str                    # bid-level badge: MIRROR if anchored on a real listing, else SIM
    lines: list[Line]
    shipping: float = 0.0
    returns_days: int = 0
    record: str = "good"
    payee: str = ""
    claims: list[dict] = field(default_factory=list)   # {text, kind, field, value, evidence_url}
    learning: bool = False
    control: bool = False
    page_html: Optional[str] = None
    note: str = ""
    seller_of_record: Optional[str] = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _stock_ok(listing: dict) -> bool:
    stock = listing.get("stock")
    return not (stock is False or (isinstance(stock, str) and stock.lower() in ("out_of_stock", "out of stock")))


def load_offers() -> tuple[list[dict], list[str]]:
    """Real RTX 5070 Ti offers from the newest snapshot of each retailer, plus one printable note per retailer
    whose listings cannot bid (out of stock, no price). Sold-listing snapshots are comps, not offers."""
    offers, dropped = [], {}
    for path in sorted(SNAPSHOTS.glob("*.json")):
        prefix = path.name.split("-")[0]
        if prefix == "ebay_sold":
            continue
        for card in json.loads(path.read_text(encoding="utf-8")):
            if (card.get("attrs") or {}).get("chipset") != CHIPSET:
                continue
            listing = card.get("listing") or {}
            if card.get("price") is None or not _stock_ok(listing):
                dropped.setdefault(prefix, []).append(card["id"])
                continue
            offers.append({"prefix": prefix, "card": card, "listing": listing})
    skips = [f"{SELLER_OF_RECORD.get(prefix, STORE_LABELS.get(prefix, prefix))}: {len(ids)} real listing(s) out of stock or unpriced in the snapshot, no bid"
             for prefix, ids in sorted(dropped.items())]
    return offers, skips


def _mirror_line(offer: dict, condition: str, seller_of_record: Optional[str]) -> Line:
    card = offer["card"]
    price = float(card["price"])
    return Line(condition=condition, list_price=price, floor=round(price * FLOOR_OF_LIST, 2),
                listing_url=card["source"], origin=MIRROR, page_condition=condition,
                basis=f"real listing {card['snapshot_id']} at {price:,.2f}, floor {FLOOR_OF_LIST:.0%} of list (SIM assumption)",
                attrs={"category": "gpu", "chipset": CHIPSET}, snapshot_id=card["snapshot_id"],
                snapshot_date=card["snapshot_date"], listing_id=card["id"],
                seller_of_record=seller_of_record)


def mirror_sellers(offers: list[dict]) -> list[Seller]:
    """One agent per seller of record. Amazon selling directly is one agent; each eBay listing is its own agent
    because the snapshot does not capture the seller handle. Marketplace identities absent from the listing are
    retained for skip visibility but are not eligible to bid."""
    groups: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    records: dict[str, Optional[str]] = {}
    for o in offers:
        prefix, listing = o["prefix"], o["listing"]
        if prefix == "ebay_live":
            sid = "ebay-" + _slug(o["card"]["source"].split("/itm/")[1].split("?")[0])[-6:]
            names[sid] = f"eBay seller of item ...{sid[-6:]} (handle not captured)"
            records[sid] = None
        elif prefix == "amazon":
            direct = listing.get("seller") == "Amazon.com"
            sid = "amazon-direct" if direct else "amazon-3p-" + _slug(o["card"]["id"])[-4:]
            names[sid] = "Amazon.com (sells direct)" if direct else "Amazon third-party seller (name not captured)"
            records[sid] = "Amazon.com" if direct else None
        else:
            sid = _slug(SELLER_OF_RECORD[prefix])
            names[sid] = SELLER_OF_RECORD[prefix]
            records[sid] = SELLER_OF_RECORD[prefix]
        groups.setdefault(sid, []).append(o)
    sellers = []
    for sid, group in sorted(groups.items()):
        by_cond: dict[str, dict] = {}
        for o in group:  # cheapest real listing per stated condition
            cond = o["card"].get("condition") or "unknown"
            if cond not in by_cond or o["card"]["price"] < by_cond[cond]["card"]["price"]:
                by_cond[cond] = o
        lines = [_mirror_line(o, cond, records[sid]) for cond, o in sorted(by_cond.items())]
        shipping_txt = next((o["listing"].get("shipping") for o in group if o["listing"].get("shipping")), "")
        first = group[0]
        claims = [{"text": f"{l.condition} per the listing", "kind": "spec", "field": "condition", "value": l.condition,
                   "evidence_url": l.listing_url} for l in lines if l.origin == MIRROR and l.condition != "unknown"]
        sellers.append(Seller(id=sid, name=names[sid], origin=MIRROR, lines=lines, shipping=0.0,
                              returns_days=0, claims=claims, payee=f"{sid}@pay.example.test",
                              note=f"delivery per listing: {shipping_txt or 'not captured'}; first listing {first['card']['id']}; "
                                   "payee is a SIM test address, no real merchant is paid",
                              seller_of_record=records[sid]))
    return sellers


def _sim_hosted(seller_key: str, name: str, discount: float, floor_pct: float, lies: bool, **kw) -> Seller:
    """A planted seller from Lane C's hosted pages: Honest Hal (page tells the truth) or Shady Sam (lies on)."""
    html_name = f"{seller_key}-gpu-5070ti{'-lies' if lies else ''}.html"
    facts = page_listing(html_name)
    url = PAGE_BASE + html_name
    list_price = float(facts["price"])
    line = Line(condition="new" if lies else facts["condition"], list_price=list_price, floor=round(list_price * floor_pct, 2),
                listing_url=url, origin=SIM, page_condition=facts["condition"], discount=discount,
                basis=f"hosted SIM page {html_name}, listed at {list_price:,.2f}",
                attrs={"category": "gpu", "chipset": CHIPSET, "length_mm": 303})
    claims = ([{"text": "BRAND NEW, factory sealed", "kind": "spec", "field": "condition", "value": "new", "evidence_url": url},
               {"text": f"was ${1099:,.0f}", "kind": "price", "field": "was_price", "value": 1099.0, "evidence_url": url}]
              if lies else
              [{"text": "New, sealed box", "kind": "spec", "field": "condition", "value": "new", "evidence_url": url},
               {"text": "30-day returns", "kind": "returns", "field": "return_days", "value": 30, "evidence_url": url}])
    if lies:   # one claim in Sam's page is true; the claim check marks it verified next to the two false ones
        claims.append({"text": "30-day returns", "kind": "returns", "field": "return_days", "value": 30, "evidence_url": url})
    sellers_json = json.loads((SITE / "sellers.json").read_text(encoding="utf-8"))["sellers"]
    return Seller(id=seller_key, name=name, origin=SIM, lines=[line], shipping=0.0, returns_days=30,
                  payee=sellers_json[seller_key]["payee"], claims=claims,
                  page_html=read_page(html_name), **kw)


def _sim_line(slug: str, condition: str, list_price: float, floor: float, basis: str, length_mm: int = 303, **kw) -> Line:
    url = f"https://example.com/sim/{slug}/rtx-5070-ti"
    return Line(condition, list_price, floor, url, SIM, page_condition=condition, basis=basis,
                attrs={"category": "gpu", "chipset": CHIPSET, "length_mm": length_mm}, **kw)


def _sim_seller(sid: str, name: str, lines: list[Line], **kw) -> Seller:
    claims = [{"text": f"{l.condition.capitalize()}, retail box", "kind": "spec", "field": "condition", "value": l.condition,
               "evidence_url": l.listing_url} for l in lines]
    return Seller(sid, name, SIM, lines, 0.0, 30, payee=f"{sid}@pay.example.test", claims=claims, **kw)


def sim_sellers() -> list[Seller]:
    band = "SIM listing priced inside the real market band"
    sam = _sim_hosted("shady-sam", "Shady Sam's Deals (SIM)", 0.04, 0.89, lies=True)
    # A card that is too long for Vidyut's 305 mm case: the fit checker, not a model, vetoes it.
    bin_ = _sim_seller("bargain-bin", "Bargain Bin Hardware (SIM)",
                       [_sim_line("bargain-bin", "new", 1199.0, 1150.0, f"{band}, 5070 Ti with a 4-slot cooler", length_mm=336)])
    # The learning seller: honest and a little too high, with two condition lines (the seller-model demo).
    # It adjusts after its first loss report.
    grove = _sim_seller("gadget-grove", "Gadget Grove (Vedant)", [
        _sim_line("gadget-grove", "new", 1349.0, 1230.0, f"{band}, honest card and 303 mm", discount=0.025),
        _sim_line("gadget-grove", "open-box", 1279.0, 1190.0, f"{band}, open-box line of the same card", discount=0.025)],
        learning=True)
    # A seller whose agent tries to bid under its own floor: the referee rejects it before anyone sees it.
    lowball = _sim_seller("lowball", "Lowball Direct (SIM)",
                          [_sim_line("lowball", "new", 1180.0, 1150.0, band, bid_override=1090.0)], note="rogue: bids under its floor")
    lowball.claims = []
    # The static control: honest, fair, and a little above the real winner. It never changes its bid.
    fair = _sim_seller("fair-price-pc", "Fair Price PC (SIM)", [_sim_line("fair-price-pc", "new", 1289.0, 1200.0, f"{band}, honest card and 303 mm")],
                       control=True)
    return [sam, bin_, grove, lowball, fair]


def all_sellers() -> tuple[list[Seller], list[str]]:
    offers, skips = load_offers()
    mirror = mirror_sellers(offers)
    eligible = []
    for seller in mirror:
        if seller.seller_of_record is None:
            for line in seller.lines:
                skips.append(f"MIRROR listing skipped: seller identity not captured; snapshot {line.snapshot_id}; source {line.listing_url}")
        else:
            eligible.append(seller)
    return eligible + sim_sellers(), skips


def line_price(line: Line, step: float = 0.0) -> tuple[float, str]:
    """Policy price for one line: list less discount less any learned step, clamped at the floor. A rogue
    line (bid_override) skips the clamp on purpose, to show the referee."""
    if line.bid_override is not None:
        return line.bid_override, "rogue agent ignored its floor"
    price = round(line.list_price * (1 - line.discount) * (1 - step), 2)
    if price < line.floor:
        return line.floor, "held at the configured floor"
    return price, "list less discount"


def make_bid(seller: Seller, need: dict, now: datetime, strategy: Optional[dict] = None) -> Optional[dict]:
    """One sealed bid: every condition line this seller carries for the SKU. `need` must already be sealed
    (no spend_limit). Contract fields of Bid plus origin, seller_id and per-line listing facts; floors are
    NOT in the bid (the market holds them)."""
    assert "spend_limit" not in need, "sellers never see the buyer's cap (sealed bids)"
    if seller.origin == MIRROR and seller.seller_of_record is None:
        return None
    step = (strategy or {}).get("price_step", 0.0)
    want = need["items"][0]
    lines, notes = [], []
    for ln in seller.lines:
        price, why = line_price(ln, step if seller.learning else 0.0)
        item = {"sku_spec": want["sku_spec"], "unit_price": price, "quantity": want["quantity"],
                      "offered_condition": ln.condition, "page_condition": ln.page_condition or ln.condition,
                      "listing_url": ln.listing_url, "origin": ln.origin, "attrs": dict(ln.attrs), "basis": ln.basis}
        if seller.origin == MIRROR:
            item.update({"listing_id": ln.listing_id, "seller_of_record": ln.seller_of_record,
                         "snapshot_id": ln.snapshot_id, "snapshot_date": ln.snapshot_date,
                         "shipping": seller.shipping,
                         "floor_evidence": {"origin": SIM, "source": POLICY_SOURCE,
                                            "observed_at": ln.snapshot_date},
                         "shipping_evidence": {"origin": SIM, "source": POLICY_SOURCE,
                                               "policy": "Shipping amount unobserved; zero is the existing SIM policy."}})
        lines.append(item)
        notes.append(f"{ln.condition} {price:,.2f} ({why})")
    perks = ([] if seller.origin == MIRROR else ["free shipping"])
    perks += [f"{seller.returns_days}-day returns"] if seller.returns_days else []
    trace = f"{seller.name}: " + "; ".join(notes) + f"; plus {seller.shipping:,.2f} shipping"
    if seller.origin == MIRROR:
        trace += "; MIRROR asking price with SIM operator floor and SIM shipping policy (shipping amount unobserved)"
    snap = next((l.snapshot_id for l in seller.lines if l.snapshot_id), "sim-hosted-pages-2026-10-23")
    bid = {"id": f"bid-{need['id']}-{seller.id}", "need_id": need["id"], "supplier_id": seller.id, "seller_id": seller.id,
            "persona": seller.name, "lines": lines,
            # cheapest line plus shipping: the bid carries several condition lines, the buyer takes one
            "total_landed_price": round(min(l["unit_price"] for l in lines) + seller.shipping, 2),
            "perks": perks, "claims": [c["text"] for c in seller.claims], "floor_check_passed": False,  # set by the referee, never by the seller
            "mirror_snapshot_id": snap, "decision_trace": trace,
            "expires_at": utc_iso(now + timedelta(seconds=need.get("auction_window_s", 12))),
            "source": SOURCE_OF[seller.origin], "origin": seller.origin}
    if seller.origin == MIRROR:
        bid["seller_of_record"] = seller.seller_of_record
    return bid
