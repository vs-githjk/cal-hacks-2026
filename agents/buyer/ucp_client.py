"""The buyer agent's side of UCP (#261): discover a shop's /.well-known/ucp profile and check out through its endpoint.
Label: UCP draft spec 2026-01-11, not certified.

Discovery refuses a profile that does not declare UCP 2026-01-11 with the dev.ucp.shopping.checkout capability and
the Tech Bazaar phone-approval payment handler, and an endpoint on another host than the profile (a shop's profile
must not point the buyer agent at someone else's server). `complete` sends only a mandate the buyer side already made;
it approves nothing. The charge stays in pay/, after the owner's phone call.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

UCP_VERSION = "2026-01-11"
CHECKOUT = "dev.ucp.shopping.checkout"
HANDLER = "dev.techbazaar.phone_approval"
MAX_BODY = 256 * 1024
Transport = Callable[[str, str, Optional[bytes]], tuple]   # (method, url, body) -> (status, payload)


class UcpError(ValueError):
    """The shop does not speak the UCP we implement, or answered with something we will not act on."""


def http_transport(method: str, url: str, body: Optional[bytes]) -> tuple:
    req = urllib.request.Request(url, data=body, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:   # noqa: S310  (http(s) only, checked by _url)
            return r.status, json.loads(r.read(MAX_BODY + 1)[:MAX_BODY] or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read(MAX_BODY))
        except ValueError:
            return e.code, None


def _url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UcpError(f"not an http(s) URL: {url[:80]}")
    return url.rstrip("/")


def discover(shop_url: str, *, transport: Optional[Transport] = None) -> dict:
    """{endpoint, handler_id, payee, shop_id, label} from the shop's profile, or UcpError."""
    base = _url(shop_url)
    status, p = (transport or http_transport)("GET", f"{base}/.well-known/ucp", None)
    if status != 200 or not isinstance(p, dict) or not isinstance(p.get("ucp"), dict):
        raise UcpError(f"no UCP profile at {base} (status {status})")
    u = p["ucp"]
    if u.get("version") != UCP_VERSION:
        raise UcpError(f"the shop declares UCP {u.get('version')!r}, this agent speaks {UCP_VERSION}")
    caps = u.get("capabilities") if isinstance(u.get("capabilities"), list) else []
    if not any(isinstance(c, dict) and c.get("name") == CHECKOUT and c.get("version") == UCP_VERSION for c in caps):
        raise UcpError("the shop does not offer the checkout capability")
    try:
        endpoint = _url(u["services"]["dev.ucp.shopping"]["rest"]["endpoint"])
    except (KeyError, TypeError):
        raise UcpError("the profile has no dev.ucp.shopping REST endpoint") from None
    if urlsplit(endpoint).netloc != urlsplit(base).netloc:
        raise UcpError("the profile points at another host than the shop")
    handlers = ((p.get("payment") or {}).get("handlers") or []) if isinstance(p.get("payment"), dict) else []
    h = next((x for x in handlers if isinstance(x, dict) and x.get("name") == HANDLER), None)
    if h is None or not isinstance(h.get("id"), str):
        raise UcpError("the shop has no Tech Bazaar phone-approval payment handler, so it cannot be paid safely")
    tb = p.get("tech_bazaar") if isinstance(p.get("tech_bazaar"), dict) else {}
    return {"endpoint": endpoint, "handler_id": h["id"], "payee": (h.get("config") or {}).get("payee"),
            "shop_id": tb.get("shop_id"), "label": "UCP draft spec 2026-01-11, not certified"}


def _call(transport: Optional[Transport], method: str, url: str, body: Optional[dict] = None) -> tuple:
    status, payload = (transport or http_transport)(method, url, json.dumps(body).encode() if body is not None else None)
    if not isinstance(payload, dict):
        raise UcpError(f"the shop answered {status} with no JSON object")
    return status, payload


def create_checkout(shop: dict, items: list[tuple[str, int]], *, transport: Optional[Transport] = None) -> dict:
    """A checkout session for [(sku, quantity), ...]. UcpError unless it is ready to complete."""
    status, s = _call(transport, "POST", f"{shop['endpoint']}/checkout-sessions",
                      {"line_items": [{"item": {"id": sku}, "quantity": q} for sku, q in items]})
    if status != 201 or s.get("status") != "ready_for_complete":
        msgs = "; ".join(str(m.get("content")) for m in s.get("messages") or [] if isinstance(m, dict))
        raise UcpError(f"checkout not ready ({status}): {msgs or s.get('status')}")
    return s


def total_dollars(session: dict) -> float:
    """The session total in dollars (UCP amounts are cents). UcpError when there is no whole-cent total."""
    t = next((x.get("amount") for x in session.get("totals") or [] if isinstance(x, dict) and x.get("type") == "total"), None)
    if isinstance(t, bool) or not isinstance(t, int) or t <= 0:
        raise UcpError("the session has no positive total in cents")
    return t / 100


def complete(shop: dict, session: dict, mandate: dict, *, transport: Optional[Transport] = None) -> dict:
    """Hand the shop the buyer's mandate for this session. The order is only held (complete_in_progress): nothing is
    paid until pay/ charges after the phone approval."""
    status, s = _call(transport, "POST", f"{shop['endpoint']}/checkout-sessions/{session['id']}/complete",
                      {"payment": {"instrument": {"handler_id": shop["handler_id"], "credential": {"mandate": mandate}}}})
    if status != 200 or s.get("status") != "complete_in_progress":
        msgs = "; ".join(str(m.get("content")) for m in s.get("messages") or [] if isinstance(m, dict))
        raise UcpError(f"the shop did not hold the order ({status}): {msgs or s.get('status')}")
    return s
