"""UCP (Universal Commerce Protocol) on each Seller Kit shop (#261). Label: UCP draft spec 2026-01-11, not certified.

Each kit shop answers at /ucp/<shop id>/:
  GET  .well-known/ucp                      the business profile (services, the checkout capability, payment handler)
  POST checkout-sessions                    create a session from line items (the shop's list price, never its floor)
  GET  checkout-sessions/<id>               read it back
  PUT  checkout-sessions/<id>               replace the line items (or the buyer) and re-total
  POST checkout-sessions/<id>/complete      hold the order for the buyer's Tech Bazaar mandate
  POST checkout-sessions/<id>/cancel        cancel it

Money: this endpoint moves none and approves nothing. A shop is SIM and its payee is a SIM test address. `complete`
takes the payment instrument of the one payment handler, dev.techbazaar.phone_approval: a Tech Bazaar mandate for
exactly this session (deal id, amount, payee, currency, unexpired and untampered, checked with pay.mandate.verify).
It then holds the order as complete_in_progress. A mandate in a request body proves nothing about approval (its status
and approval_id are outside the hash), so the charge stays where it always was: pay/, after the buyer's phone call
(can_charge). The session never says "completed" or "paid" from here.

The shapes follow the UCP 2026-01-11 overview and checkout pages as we understood them (ucp.dev was not reachable from
the build machine), so they were not validated against the official JSON schemas. Amounts are integer minor units
(cents), as UCP uses.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

UCP_VERSION = "2026-01-11"
LABEL = "UCP draft spec 2026-01-11, not certified"
SPEC = f"https://ucp.dev/{UCP_VERSION}/specification"
HANDLER = "dev.techbazaar.phone_approval"
HANDLER_ID = "tech_bazaar_phone_approval"
SESSION_TTL_S = 30 * 60
MAX_SESSIONS = 1000
MAX_LINE_ITEMS = 20
MAX_QUANTITY = 10
STATUSES = ("incomplete", "ready_for_complete", "complete_in_progress", "canceled")
HELD = ("Order held for the buyer's Tech Bazaar mandate. No money moved here: the charge runs in Tech Bazaar pay only after "
        "the buyer approves on a phone call. SIM shop, SIM payee.")


def payee_for(shop_id: str) -> str:
    """A kit shop's SIM test payee (the demo sellers use the same example.test addresses)."""
    return f"{shop_id}@pay.example.test"


def list_price(listing: dict, pricing: dict) -> Optional[float]:
    """The shop's asking price for a listing: `price`, or cost plus margin in fixed_margin mode. Never the floor."""
    if isinstance(listing.get("price"), (int, float)) and not isinstance(listing.get("price"), bool):
        return float(listing["price"])
    cost = listing.get("cost")
    if pricing.get("mode") == "fixed_margin" and isinstance(cost, (int, float)) and not isinstance(cost, bool):
        return round(float(cost) * (1 + float(pricing.get("margin_pct", 0)) / 100), 2)
    return None


def profile(shop: dict, base_url: str) -> dict:
    endpoint = f"{base_url.rstrip('/')}/ucp/{shop['id']}"
    return {
        "ucp": {
            "version": UCP_VERSION,
            "services": {"dev.ucp.shopping": {"version": UCP_VERSION, "spec": f"{SPEC}/overview",
                                              "rest": {"schema": f"https://ucp.dev/{UCP_VERSION}/services/shopping/rest.openapi.json",
                                                       "endpoint": endpoint}}},
            "capabilities": [{"name": "dev.ucp.shopping.checkout", "version": UCP_VERSION, "spec": f"{SPEC}/checkout",
                              "schema": f"https://ucp.dev/{UCP_VERSION}/schemas/shopping/checkout.json"}],
        },
        "payment": {"handlers": [{"id": HANDLER_ID, "name": HANDLER, "version": UCP_VERSION,
                                  "config": {"approval": "phone_call", "settles_in": "tech_bazaar_pay", "payee": payee_for(shop["id"])}}]},
        "tech_bazaar": {"label": LABEL, "shop_id": shop["id"], "shop_name": shop["name"], "origin": shop.get("origin", "SIM")},
    }


def _cents(x: float) -> int:
    return int(round(x * 100))


def _error(code: str, content: str, path: str = "") -> dict:
    return {"type": "error", "code": code, "content": content, **({"path": path} if path else {})}


def _lines(shop: dict, raw: Any) -> tuple[list[dict], list[dict]]:
    """Line items priced from the shop's own listings, and error messages for any that cannot be sold."""
    if not isinstance(raw, list) or not raw:
        return [], [_error("invalid_line_items", "line_items must be a non-empty list", "$.line_items")]
    if len(raw) > MAX_LINE_ITEMS:
        return [], [_error("invalid_line_items", f"at most {MAX_LINE_ITEMS} line items", "$.line_items")]
    out, errors = [], []
    for i, li in enumerate(raw):
        at = f"$.line_items[{i}]"
        item = li.get("item") if isinstance(li, dict) else None
        sku = item.get("id") if isinstance(item, dict) else None
        qty = li.get("quantity", 1) if isinstance(li, dict) else None
        if not isinstance(sku, str) or not sku.strip():
            errors.append(_error("invalid_item", "item.id must name one of the shop's listings", f"{at}.item.id"))
            continue
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= MAX_QUANTITY:
            errors.append(_error("invalid_quantity", f"quantity must be a whole number from 1 to {MAX_QUANTITY}", f"{at}.quantity"))
            continue
        listing = shop["listings"].get(sku.strip().lower())
        price = list_price(listing, shop.get("pricing") or {}) if isinstance(listing, dict) else None
        if price is None or not price > 0:
            errors.append(_error("item_unavailable", f"{sku!r} is not sold by this shop", f"{at}.item.id"))
            continue
        unit = _cents(price)
        out.append({"id": f"li_{i + 1}", "item": {"id": sku.strip().lower(), "title": listing.get("attrs", {}).get("chipset") or sku,
                                                  "price": unit, "condition": listing.get("condition", "")},
                    "quantity": qty, "totals": [{"type": "subtotal", "amount": unit * qty}]})
    return out, errors


def _totals(lines: list[dict], shipping: float) -> list[dict]:
    sub = sum(t["amount"] for li in lines for t in li["totals"] if t["type"] == "subtotal")
    ship = _cents(shipping) if lines else 0
    return [{"type": "subtotal", "amount": sub}, {"type": "fulfillment", "amount": ship}, {"type": "total", "amount": sub + ship}]


class Sessions:
    """Checkout sessions in memory, per app: capped, expiring, one lock around every change."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._by_id: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.clock = clock

    def _sweep(self) -> None:
        now = self.clock()
        for k in [k for k, s in self._by_id.items() if s["_expires"] <= now]:
            del self._by_id[k]

    def create(self, shop: dict, body: dict) -> tuple[int, dict]:
        lines, errors = _lines(shop, body.get("line_items"))
        with self._lock:
            self._sweep()
            if len(self._by_id) >= MAX_SESSIONS:
                return 503, {"messages": [_error("busy", "too many open checkout sessions, try again later")]}
            sid = "cs_" + secrets.token_hex(12)
            s = {"id": sid, "shop_id": shop["id"], "currency": "USD", "buyer": _buyer(body.get("buyer")), "_expires": self.clock() + SESSION_TTL_S}
            self._by_id[sid] = s
            _retotal(s, shop, lines, errors)
            return 201, view(s)

    def get(self, shop: dict, sid: str) -> Optional[dict]:
        with self._lock:
            self._sweep()
            s = self._by_id.get(sid)
            return s if s and s["shop_id"] == shop["id"] else None

    def update(self, shop: dict, sid: str, body: dict) -> tuple[int, dict]:
        with self._lock:
            s = self._live(shop, sid)
            if isinstance(s, tuple):
                return s
            if "buyer" in body:
                s["buyer"] = _buyer(body.get("buyer"))
            if "line_items" in body:
                lines, errors = _lines(shop, body.get("line_items"))
                _retotal(s, shop, lines, errors)
            return 200, view(s)

    def complete(self, shop: dict, sid: str, body: dict, verify: Callable[[dict], Any]) -> tuple[int, dict]:
        with self._lock:
            s = self._live(shop, sid)
            if isinstance(s, tuple):
                return s
            if s["status"] != "ready_for_complete":
                return 409, {**view(s), "messages": [_error("not_ready", "the session has errors or no line items")]}
            why = _mandate_problem(s, shop, body, verify)
            if why:
                return 402, {**view(s), "messages": [_error("payment_required", why, "$.payment")]}
            m = body["payment"]["instrument"]["credential"]["mandate"]
            s["status"] = "complete_in_progress"
            s["order"] = {"mandate_hash": m["hash"], "mandate_id": m["id"], "settlement": "tech_bazaar_pay_after_phone_approval",
                          "money_moved_here": False, "origin": "SIM"}
            s["messages"] = [{"type": "info", "code": "held_for_approval", "content": HELD}]
            return 200, view(s)

    def cancel(self, shop: dict, sid: str) -> tuple[int, dict]:
        with self._lock:
            s = self._live(shop, sid)
            if isinstance(s, tuple):
                return s
            if s["status"] == "complete_in_progress":
                return 409, {**view(s), "messages": [_error("held", "the order is held for the buyer's mandate; deny the call instead")]}
            s["status"] = "canceled"
            return 200, view(s)

    def _live(self, shop: dict, sid: str):
        self._sweep()
        s = self._by_id.get(sid)
        if not s or s["shop_id"] != shop["id"]:
            return 404, {"messages": [_error("not_found", "no such checkout session for this shop")]}
        if s["status"] == "canceled":
            return 409, {**view(s), "messages": [_error("canceled", "the session is canceled")]}
        return s


def _buyer(raw: Any) -> dict:
    """Only a display name and an email are kept, short and plain; nothing else from the buyer object is stored."""
    if not isinstance(raw, dict):
        return {}
    return {k: str(raw[k])[:120] for k in ("full_name", "email") if isinstance(raw.get(k), str) and raw[k].strip()}


def _retotal(s: dict, shop: dict, lines: list[dict], errors: list[dict]) -> None:
    s["line_items"] = lines
    s["totals"] = _totals(lines, float(shop.get("shipping") or 0))
    s["messages"] = errors
    s["status"] = "ready_for_complete" if lines and not errors else "incomplete"


def _mandate_problem(s: dict, shop: dict, body: Any, verify: Callable[[dict], Any]) -> Optional[str]:
    """Why the payment instrument is not a Tech Bazaar mandate for exactly this session, or None."""
    try:
        inst = body["payment"]["instrument"]
        m = inst["credential"]["mandate"]
    except (KeyError, TypeError):
        return f"payment.instrument with handler_id {HANDLER_ID} and credential.mandate is required"
    if not isinstance(inst, dict) or inst.get("handler_id") != HANDLER_ID or not isinstance(m, dict):
        return f"the only payment handler is {HANDLER_ID}"
    ok = verify(m)
    if not ok:
        return f"the mandate does not verify ({getattr(ok, 'reason', 'invalid')})"
    total = next(t["amount"] for t in s["totals"] if t["type"] == "total")
    amount = m.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or _cents(float(amount)) != total:
        return "the mandate amount is not this session's total"
    if m.get("payee") != payee_for(shop["id"]):
        return "the mandate payee is not this shop"
    if m.get("deal_id") != s["id"] or m.get("currency") != s["currency"]:
        return "the mandate is not for this checkout session"
    return None


def view(s: dict) -> dict:
    """The session as UCP returns it, with the Tech Bazaar label; internal fields stay out."""
    out = {k: v for k, v in s.items() if not k.startswith("_") and k != "shop_id"}
    out["ucp"] = {"version": UCP_VERSION, "capabilities": [{"name": "dev.ucp.shopping.checkout", "version": UCP_VERSION}]}
    out["expires_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s["_expires"]))
    out["tech_bazaar"] = {"label": LABEL, "origin": "SIM"}
    return out


def load_shop(folder: Path, shop_id: str, validate: Callable[[dict], dict]) -> Optional[dict]:
    """A kit shop by id, or None. Only a plain file in the shops folder, valid as a seller config."""
    if not isinstance(shop_id, str) or not shop_id or "/" in shop_id or "\\" in shop_id or shop_id.startswith("."):
        return None
    path = folder / f"{shop_id}.json"
    if path.parent != folder or path.is_symlink() or not path.is_file():
        return None
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, RecursionError):
        return None
