"""Beat 2, step 1: seller agents and their sealed bids. SIM stand-in for agents/sellers (Lane A, not merged).

Seller model (LOCKED Fri 22:36): one agent per SELLER OF RECORD, several condition lines for the same SKU inside
one sealed bid. Prices come from a deterministic policy (list price less a discount, never below the floor),
never from a model. Mirrors origin/agents agents/sellers/policy.py make_bid.

MIRROR agents bid from real, dated listings in data/mirror/snapshots (listing URL and snapshot id on every line).
Where a seller has no real listing for a condition, the agent adds a derived line labelled SIM. SIM sellers are
ours: Honest Hal and Shady Sam from Lane C's hosted pages (data/liar_pages/site), plus two more labelled SIM.
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
# SIM derivation rules for lines a real listing does not give us (labelled SIM on every line that uses them).
OPEN_BOX_DISCOUNT = 0.10
FLOOR_OF_LIST = 0.93  # a MIRROR agent never bids below 93 percent of its listed price (SIM assumption)

SELLER_OF_RECORD = {  # snapshot file prefix -> seller of record for listings the retailer sells itself
    "bestbuy": "Best Buy",
    "microcenter": "Micro Center",
    "bh": "B&H Photo",
    "amazon": "Amazon.com",   # label only: Amazon listings are split by who the listing says sells it
    "ebay_live": "eBay",
}


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
    skips = [f"{SELLER_OF_RECORD.get(prefix, prefix)}: {len(ids)} real listing(s) out of stock or unpriced in the snapshot, no bid"
             for prefix, ids in sorted(dropped.items())]
    return offers, skips


def _mirror_line(offer: dict, condition: str) -> Line:
    card = offer["card"]
    price = float(card["price"])
    return Line(condition=condition, list_price=price, floor=round(price * FLOOR_OF_LIST, 2),
                listing_url=card["source"], origin=MIRROR, page_condition=condition,
                basis=f"real listing {card['snapshot_id']} at {price:,.2f}, floor {FLOOR_OF_LIST:.0%} of list (SIM assumption)",
                attrs={"category": "gpu", "chipset": CHIPSET}, snapshot_id=card["snapshot_id"],
                snapshot_date=card["snapshot_date"])


def _derived_open_box(base: Line) -> Line:
    price = round(base.list_price * (1 - OPEN_BOX_DISCOUNT), 2)
    return Line(condition="open-box", list_price=price, floor=round(price * FLOOR_OF_LIST, 2), listing_url=base.listing_url,
                origin=SIM, page_condition=None,
                basis=f"derived open-box line: {OPEN_BOX_DISCOUNT:.0%} under its own new listing, no open-box listing captured",
                attrs=dict(base.attrs), snapshot_id=base.snapshot_id, snapshot_date=base.snapshot_date)


def mirror_sellers(offers: list[dict]) -> list[Seller]:
    """One agent per seller of record. Amazon selling directly is one agent; each eBay listing is its own agent
    because the snapshot does not capture the seller handle."""
    groups: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for o in offers:
        prefix, listing = o["prefix"], o["listing"]
        if prefix == "ebay_live":
            sid = "ebay-" + _slug(o["card"]["source"].split("/itm/")[1].split("?")[0])[-6:]
            names[sid] = f"eBay seller of item ...{sid[-6:]} (handle not captured)"
        elif prefix == "amazon":
            direct = listing.get("seller") == "Amazon.com"
            sid = "amazon-direct" if direct else "amazon-3p-" + _slug(o["card"]["id"])[-4:]
            names[sid] = "Amazon.com (sells direct)" if direct else "Amazon third-party seller (name not captured)"
        else:
            sid = _slug(SELLER_OF_RECORD[prefix])
            names[sid] = SELLER_OF_RECORD[prefix]
        groups.setdefault(sid, []).append(o)
    sellers = []
    for sid, group in sorted(groups.items()):
        by_cond: dict[str, dict] = {}
        for o in group:  # cheapest real listing per stated condition
            cond = o["card"].get("condition") or "unknown"
            if cond not in by_cond or o["card"]["price"] < by_cond[cond]["card"]["price"]:
                by_cond[cond] = o
        lines = [_mirror_line(o, cond) for cond, o in sorted(by_cond.items())]
        if "open-box" not in by_cond and "new" in by_cond:
            lines.append(_derived_open_box(next(l for l in lines if l.condition == "new")))
        shipping_txt = next((o["listing"].get("shipping") for o in group if o["listing"].get("shipping")), "")
        first = group[0]
        claims = [{"text": f"{l.condition} per the listing", "kind": "spec", "field": "condition", "value": l.condition,
                   "evidence_url": l.listing_url} for l in lines if l.origin == MIRROR and l.condition != "unknown"]
        sellers.append(Seller(id=sid, name=names[sid], origin=MIRROR, lines=lines, shipping=0.0,
                              returns_days=0, claims=claims,
                              note=f"delivery per listing: {shipping_txt or 'not captured'}; first listing {first['card']['id']}"))
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
    sellers_json = json.loads((SITE / "sellers.json").read_text(encoding="utf-8"))["sellers"]
    return Seller(id=seller_key, name=name, origin=SIM, lines=[line], shipping=0.0, returns_days=30,
                  payee=sellers_json[seller_key]["payee"], claims=claims,
                  page_html=read_page(html_name), **kw)


def sim_sellers() -> list[Seller]:
    sim_url = lambda slug: f"https://example.com/sim/{slug}/rtx-5070-ti"
    hal = _sim_hosted("honest-hal", "Honest Hal's Parts (SIM)", 0.02, 0.94, lies=False, control=True)
    sam = _sim_hosted("shady-sam", "Shady Sam's Deals (SIM)", 0.04, 0.89, lies=True)
    # A card that is too long for Joe's 305 mm case: the fit checker, not a model, vetoes it.
    xl = Line("new", 764.0, 740.0, sim_url("bargain-bin"), SIM, page_condition="new",
              basis="SIM listing, 5070 Ti with a 4-slot cooler", attrs={"category": "gpu", "chipset": CHIPSET, "length_mm": 336})
    bin_ = Seller("bargain-bin", "Bargain Bin Hardware (SIM)", SIM, [xl], 0.0, 30, payee="bargain-bin@pay.example.test",
                  claims=[{"text": "New, retail box", "kind": "spec", "field": "condition", "value": "new", "evidence_url": xl.listing_url}])
    # The learning seller: fair, honest and a little too high. It adjusts after its first loss report.
    gg = Line("new", 840.0, 740.0, sim_url("gadget-grove"), SIM, page_condition="new", discount=0.025,
              basis="SIM listing, honest card and 303 mm", attrs={"category": "gpu", "chipset": CHIPSET, "length_mm": 303})
    grove = Seller("gadget-grove", "Gadget Grove (SIM)", SIM, [gg], 0.0, 30, payee="gadget-grove@pay.example.test", learning=True,
                   claims=[{"text": "New, retail box", "kind": "spec", "field": "condition", "value": "new", "evidence_url": gg.listing_url}])
    # A seller whose agent tries to bid under its own floor: the referee rejects it before anyone sees it.
    lb = Line("new", 760.0, 735.0, sim_url("lowball"), SIM, page_condition="new", bid_override=690.0,
              basis="SIM listing", attrs={"category": "gpu", "chipset": CHIPSET, "length_mm": 303})
    lowball = Seller("lowball", "Lowball Direct (SIM)", SIM, [lb], 0.0, 30, payee="lowball@pay.example.test", note="rogue: bids under its floor",
                     claims=[])
    return [hal, sam, bin_, grove, lowball]


def all_sellers() -> tuple[list[Seller], list[str]]:
    offers, skips = load_offers()
    return mirror_sellers(offers) + sim_sellers(), skips


def line_price(line: Line, step: float = 0.0) -> tuple[float, str]:
    """Policy price for one line: list less discount less any learned step, clamped at the floor. A rogue
    line (bid_override) skips the clamp on purpose, to show the referee."""
    if line.bid_override is not None:
        return line.bid_override, "rogue agent ignored its floor"
    price = round(line.list_price * (1 - line.discount) * (1 - step), 2)
    if price < line.floor:
        return line.floor, f"held at floor {line.floor:,.2f}"
    return price, "list less discount"


def make_bid(seller: Seller, need: dict, now: datetime, strategy: Optional[dict] = None) -> dict:
    """One sealed bid: every condition line this seller carries for the SKU. `need` must already be sealed
    (no spend_limit). Contract fields of Bid plus origin, seller_id and per-line listing facts; floors are
    NOT in the bid (the market holds them)."""
    assert "spend_limit" not in need, "sellers never see the buyer's cap (sealed bids)"
    step = (strategy or {}).get("price_step", 0.0)
    want = need["items"][0]
    lines, notes = [], []
    for ln in seller.lines:
        price, why = line_price(ln, step if seller.learning else 0.0)
        lines.append({"sku_spec": want["sku_spec"], "unit_price": price, "quantity": want["quantity"],
                      "offered_condition": ln.condition, "page_condition": ln.page_condition or ln.condition,
                      "listing_url": ln.listing_url, "origin": ln.origin, "attrs": dict(ln.attrs), "basis": ln.basis})
        notes.append(f"{ln.condition} {price:,.2f} ({why})")
    perks = ["free shipping"] + ([f"{seller.returns_days}-day returns"] if seller.returns_days else [])
    trace = f"{seller.name}: " + "; ".join(notes) + f"; plus {seller.shipping:,.2f} shipping"
    snap = next((l.snapshot_id for l in seller.lines if l.snapshot_id), "sim-hosted-pages-2026-10-23")
    return {"id": f"bid-{need['id']}-{seller.id}", "need_id": need["id"], "supplier_id": seller.id, "seller_id": seller.id,
            "persona": seller.name, "lines": lines,
            # cheapest line plus shipping: the bid carries several condition lines, the buyer takes one
            "total_landed_price": round(min(l["unit_price"] for l in lines) + seller.shipping, 2),
            "perks": perks, "claims": [c["text"] for c in seller.claims], "floor_check_passed": False,  # set by the referee, never by the seller
            "mirror_snapshot_id": snap, "decision_trace": trace,
            "expires_at": utc_iso(now + timedelta(seconds=need.get("auction_window_s", 12))),
            "source": SOURCE_OF[seller.origin], "origin": seller.origin}
