"""Beat 2, step 1: seller agents and their sealed bids. SIM stand-in for agents/sellers (Lane A, not merged).

Seller model (LOCKED Fri 22:36): one agent per SELLER OF RECORD, several condition lines for the same SKU inside
one sealed bid. Prices come from a deterministic policy (list price less a discount, never below the floor),
never from a model. Mirrors origin/agents agents/sellers/policy.py make_bid.

MIRROR agents bid from real, dated listings in data/mirror/snapshots (listing URL and snapshot id on every line).
They never get an invented line: a real seller bids only the conditions its real listings show. SIM sellers are
ours: Shady Sam from Lane C's hosted pages (data/liar_pages/site) and four more labelled SIM, priced inside the real
market band (about $1,200 to $1,350 at the retailers on Oct 24) so one real seller that fits Vidyut's case can win honestly. Sam's page is
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

from data.fit_checker import check_fit
from data.fit_checker.gpu_lengths import maker_length
from demo.common import MIRROR, PAGE_BASE, SIM, SITE, SNAPSHOTS, SOURCE_OF, utc_iso
from demo.pages import page_listing, read_page

SKU = "rtx 5070 ti"
CHIPSET = "RTX 5070 Ti"
FLOOR_OF_LIST = 0.93  # a MIRROR agent never bids below 93 percent of its listed price (SIM assumption)
CASE_CLEARANCE_MM = 305  # Vidyut's case (goal.py owned-case); a spec the buyer shares with sellers, never the cap

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
    withheld: list[dict] = field(default_factory=list)  # own catalog lines the seller agent did not bid, with the cited reason
    shipping_captured: bool = False                      # False: the listing does not state a delivery cost (shown as such)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _stock_ok(listing: dict) -> bool:
    stock = listing.get("stock")
    return not (stock is False or (isinstance(stock, str) and stock.lower() in ("out_of_stock", "out of stock")))


def stated_shipping(listing: dict) -> Optional[float]:
    """The delivery cost a listing states, or None when it states none. A numeric listing.shipping_cost wins; else the
    data lane's anchored rule (data.mirror.normalize.landed): a bare 'free delivery' is 0.0 and '+$29.95 delivery' is
    29.95, while '+C $12.99' (not USD), 'or free over $35' and 'free shipping on orders over $35' (conditional) and a
    delivery date range state no cost (#188)."""
    cost = listing.get("shipping_cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        return float(cost)
    from data.mirror.normalize import landed
    return landed({"shipping": listing.get("shipping"), "shipping_type": listing.get("shipping_type")}, None)["shipping_cost"]


def load_offers() -> tuple[list[dict], list[str]]:
    """Real RTX 5070 Ti offers from the newest snapshot of each retailer, plus one printable note per retailer
    whose listings cannot bid (out of stock, no price). Sold-listing snapshots are comps, not offers."""
    latest: dict[str, tuple[str, dict]] = {}   # listing URL -> (prefix, card): a URL seen in two snapshots is one listing, the newest
    for path in sorted(SNAPSHOTS.glob("*.json")):   # file names end in a UTC stamp, so sorted order is oldest to newest
        prefix = path.name.split("-")[0]
        # Sold history is comps, not offers. A store snapshot this round has no seller of record for (for example
        # centralcomputers, #308, served by data.mirror.central_computers) stays out until Lane D adds it here.
        if prefix == "ebay_sold" or prefix not in SELLER_OF_RECORD:
            continue
        for card in json.loads(path.read_text(encoding="utf-8")):
            if (card.get("attrs") or {}).get("chipset") != CHIPSET:
                continue
            latest[card.get("source") or card["id"]] = (prefix, card)
    offers, dropped = [], {}
    for prefix, card in latest.values():
        listing = card.get("listing") or {}
        if card.get("price") is None or not _stock_ok(listing):
            dropped.setdefault(prefix, []).append(card["id"])
            continue
        offers.append({"prefix": prefix, "card": card, "listing": listing})
    skips = [f"{SELLER_OF_RECORD.get(prefix, prefix)}: {len(ids)} real listing(s) out of stock or unpriced in the snapshot, no bid"
             for prefix, ids in sorted(dropped.items())]
    return offers, skips


def _maker(offer: dict) -> Optional[dict]:
    """The maker-spec row (data/fit_checker/gpu_lengths.json) for a listing, matched on its title and URL; None = unknown."""
    card = offer["card"]
    return maker_length(f"{card.get('name', '')} {card.get('source', '')}")


def _mirror_line(offer: dict, condition: str) -> Line:
    card = offer["card"]
    price = float(card["price"])
    attrs = {"category": "gpu", "chipset": CHIPSET}
    maker = _maker(offer)
    if maker:   # maker-spec length (MIRROR); a model we cannot name gets no length, never a guess
        attrs.update(length_mm=maker["length_mm"], length_source=maker["source"], length_model=maker["model"])
    return Line(condition=condition, list_price=price, floor=round(price * FLOOR_OF_LIST, 2),
                listing_url=card["source"], origin=MIRROR, page_condition=condition,
                basis=f"real listing {card['snapshot_id']} at {price:,.2f}, floor {FLOOR_OF_LIST:.0%} of list (SIM assumption)",
                attrs=attrs, snapshot_id=card["snapshot_id"], snapshot_date=card["snapshot_date"])


def choose_offer(cands: list[dict], clearance_mm: int = CASE_CLEARANCE_MM) -> tuple[dict, list[dict]]:
    """Which real listing a seller agent bids for one condition, and the cheaper ones it withholds because the
    maker's own spec says they are too long. Cheapest card that fits; else the cheapest whose length we cannot
    confirm (flagged, the advocate says 'fit not confirmed'); else the cheapest card (the advocate vetoes it)."""
    ordered = sorted(cands, key=lambda o: o["card"]["price"])
    fit = [o for o in ordered if (m := _maker(o)) and m["length_mm"] <= clearance_mm]
    unknown = [o for o in ordered if not _maker(o)]
    pick = (fit or unknown or ordered)[0]
    too_long = [o for o in ordered if o["card"]["price"] <= pick["card"]["price"] and o is not pick
                and (m := _maker(o)) and m["length_mm"] > clearance_mm] if fit else []
    return pick, too_long


def _withheld(offer: dict, clearance_mm: int) -> dict:
    """A catalog line the seller agent did not bid: the real fit checker's reason, its rule and the maker's spec page."""
    m = _maker(offer)
    cards = [{"id": "gpu", "category": "gpu", "name": "gpu", "attrs": {"chipset": CHIPSET, "length_mm": m["length_mm"]}},
             {"id": "owned-case", "category": "case", "name": "case", "attrs": {"max_gpu_length_mm": clearance_mm}}]
    check = next(c for c in check_fit(cards)["checks"] if c["rule_id"] == "fit.gpu_length")
    return {"model": m["model"], "unit_price": float(offer["card"]["price"]), "condition": offer["card"].get("condition") or "unknown",
            "length_mm": m["length_mm"], "rule_id": check["rule_id"], "reason": check["reason"], "source_url": m["source"],
            "listing_url": offer["card"]["source"]}


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
        per_cond: dict[str, list[dict]] = {}
        for o in group:
            per_cond.setdefault(o["card"].get("condition") or "unknown", []).append(o)
        by_cond, withheld = {}, []
        for cond, cands in per_cond.items():   # per condition: the cheapest listing that fits the buyer's case
            by_cond[cond], too_long = choose_offer(cands)
            withheld += [_withheld(o, CASE_CLEARANCE_MM) for o in too_long]
        lines = [_mirror_line(o, cond) for cond, o in sorted(by_cond.items())]
        shipping_txt = next((o["listing"].get("shipping") for o in group if o["listing"].get("shipping")), "")
        stated = [c for o in by_cond.values() if (c := stated_shipping(o["listing"])) is not None]   # of the lines it bids
        first = group[0]
        claims = [{"text": f"{l.condition} per the listing", "kind": "spec", "field": "condition", "value": l.condition,
                   "evidence_url": l.listing_url} for l in lines if l.origin == MIRROR and l.condition != "unknown"]
        sellers.append(Seller(id=sid, name=names[sid], origin=MIRROR, lines=lines, shipping=max(stated, default=0.0), shipping_captured=bool(stated),
                              returns_days=0, claims=claims, payee=f"{sid}@pay.example.test", withheld=withheld,
                              note=f"delivery per listing: {shipping_txt or 'not captured'}; first listing {first['card']['id']}; "
                                   "payee is a SIM test address, no real merchant is paid"))
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
    return Seller(id=seller_key, name=name, origin=SIM, lines=[line], shipping=0.0, returns_days=30, shipping_captured=True,
                  payee=sellers_json[seller_key]["payee"], claims=claims,
                  page_html=read_page(html_name), **kw)


def _sim_line(slug: str, condition: str, list_price: float, floor: float, basis: str, length_mm: int = 303, **kw) -> Line:
    url = f"https://example.com/sim/{slug}/rtx-5070-ti"
    return Line(condition, list_price, floor, url, SIM, page_condition=condition, basis=basis,
                attrs={"category": "gpu", "chipset": CHIPSET, "length_mm": length_mm}, **kw)


def _sim_seller(sid: str, name: str, lines: list[Line], **kw) -> Seller:
    claims = [{"text": f"{l.condition.capitalize()}, retail box", "kind": "spec", "field": "condition", "value": l.condition,
               "evidence_url": l.listing_url} for l in lines]
    return Seller(sid, name, SIM, lines, 0.0, 30, payee=f"{sid}@pay.example.test", claims=claims, shipping_captured=True, **kw)


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
        _sim_line("gadget-grove", "open-box", 1319.0, 1190.0, f"{band}, open-box line of the same card", discount=0.025)],
        learning=True)
    # A seller whose agent tries to bid under its own floor: the referee rejects it before anyone sees it.
    lowball = _sim_seller("lowball", "Lowball Direct (SIM)",
                          [_sim_line("lowball", "new", 1180.0, 1150.0, band, bid_override=1090.0)], note="rogue: bids under its floor")
    lowball.claims = []
    # The static control: honest, fair, and a little above the real winner (and the cap). It never changes its bid.
    fair = _sim_seller("fair-price-pc", "Fair Price PC (SIM)", [_sim_line("fair-price-pc", "new", 1329.0, 1200.0, f"{band}, honest card and 303 mm")],
                       control=True)
    return [sam, bin_, grove, lowball, fair]


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
            "source": SOURCE_OF[seller.origin], "origin": seller.origin,
            # cheaper catalog lines the seller agent screened out against the buyer's case (additive key; not seller text, so Shield does not read it)
            **({"withheld_lines": [dict(w) for w in seller.withheld]} if seller.withheld else {})}
