"""The buyer agent's side of UCP (#261): discover a shop's /.well-known/ucp profile and check out through its endpoint.
Label: UCP draft spec 2026-01-11, not certified.

Discovery refuses a profile that does not declare UCP 2026-01-11 with the dev.ucp.shopping.checkout capability and
the Tech Bazaar phone-approval payment handler, and an endpoint on another host than the profile (a shop's profile
must not point the buyer agent at someone else's server). `complete` sends only a mandate the buyer side already made;
it approves nothing. The charge stays in pay/, after the owner's phone call.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

UCP_VERSION = "2026-01-11"
CHECKOUT = "dev.ucp.shopping.checkout"
HANDLER = "dev.techbazaar.phone_approval"
MAX_BODY = 256 * 1024
_SESSION_ID = re.compile(r"cs_[0-9a-f]{8,64}")
Transport = Callable[[str, str, Optional[bytes]], tuple]   # (method, url, body) -> (status, payload)


class UcpError(ValueError):
    """The shop does not speak the UCP we implement, or answered with something we will not act on."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):   # a shop may not bounce the buyer agent to another host
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _json(raw: bytes) -> Any:
    if len(raw) > MAX_BODY:
        raise UcpError("the shop's answer is too large")
    try:
        return json.loads(raw or b"null")
    except (ValueError, RecursionError):
        raise UcpError("the shop's answer is not JSON") from None


def http_transport(method: str, url: str, body: Optional[bytes]) -> tuple:
    """(status, JSON) with no redirects followed. Network errors and bad bodies are UcpError."""
    req = urllib.request.Request(url, data=body, method=method, headers={"content-type": "application/json"})
    try:
        with _OPENER.open(req, timeout=5) as r:   # noqa: S310  (http(s) only, checked by _url)
            return r.status, _json(r.read(MAX_BODY + 1))
    except urllib.error.HTTPError as e:
        try:
            return e.code, _json(e.read(MAX_BODY + 1))
        except UcpError:
            return e.code, None
    except (urllib.error.URLError, OSError) as e:
        raise UcpError(f"the shop could not be reached ({type(e).__name__})") from None


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
    e, b = urlsplit(endpoint), urlsplit(base)
    if (e.scheme, e.netloc) != (b.scheme, b.netloc):   # same scheme too: an https shop may not send the mandate over http
        raise UcpError("the profile points at another host or scheme than the shop")
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
    if not isinstance(session.get("id"), str) or not _SESSION_ID.fullmatch(session["id"]):
        raise UcpError("the session id is not one this client will put in a URL")
    status, s = _call(transport, "POST", f"{shop['endpoint']}/checkout-sessions/{session['id']}/complete",
                      {"payment": {"instrument": {"handler_id": shop["handler_id"], "credential": {"mandate": mandate}}}})
    if status != 200 or s.get("status") != "complete_in_progress":
        msgs = "; ".join(str(m.get("content")) for m in s.get("messages") or [] if isinstance(m, dict))
        raise UcpError(f"the shop did not hold the order ({status}): {msgs or s.get('status')}")
    return s
