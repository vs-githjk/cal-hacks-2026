"""#449 RT-26: the buyer's local REST chat (/chat) answers loopback callers only.

uagents binds its server to 0.0.0.0 (uagents.asgi.HOST) and hands a REST handler only the parsed body: no client
host, no headers. So the check cannot live in the handler. install() puts it in front of the agent's own ASGI
server, for the REST endpoints the agent registered (not /submit, which other agents use).

A request is allowed when ALL of these hold:
- the TCP peer is loopback. uagents runs uvicorn with forwarded_allow_ips="*", which rewrites the client host from
  X-Forwarded-For, so any proxy header at all (X-Forwarded-*, Forwarded, X-Real-IP) is refused: it could be a stranger
  claiming to be 127.0.0.1;
- there is no Origin header. uagents answers CORS preflight with Access-Control-Allow-Origin *, so a web page the
  owner has open could otherwise POST to localhost. Browsers always send Origin; web_chat.py and curl do not;
- when BUYER_REST_TOKEN is set, `Authorization: Bearer <token>` matches it (constant-time compare). web_chat.py
  sends it when the variable is set.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from typing import Any, Mapping

TOKEN_ENV = "BUYER_REST_TOKEN"
RESERVED = {"/submit", "/messages", "/agent_info", "/connect", "/disconnect"}   # uagents.asgi.RESERVED_ENDPOINTS
PROXY_HEADERS = {b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"x-forwarded-port", b"forwarded",
                 b"x-real-ip"}


def _loopback(client: Any) -> bool:
    try:
        host = client[0]
        ip = ipaddress.ip_address(host)
    except (TypeError, IndexError, ValueError):
        return False       # no client (unix socket), not an address: refused
    return ip.is_loopback or bool(getattr(ip, "ipv4_mapped", None) and ip.ipv4_mapped.is_loopback)


def permitted(scope: Mapping, environ: Mapping[str, str] = os.environ) -> bool:
    """True when this HTTP scope may reach the buyer's REST chat."""
    if not _loopback(scope.get("client")):
        return False
    names = {bytes(k).lower() for k, _ in scope.get("headers", [])}
    if names & PROXY_HEADERS or b"origin" in names:
        return False
    token = (environ.get(TOKEN_ENV) or "").strip()
    if not token:
        return True
    supplied = b""
    for k, v in scope.get("headers", []):
        if bytes(k).lower() == b"authorization":
            scheme, _, value = bytes(v).decode("latin-1").partition(" ")
            if scheme.lower() == "bearer":
                supplied = value.strip().encode("utf-8")
            break
    return hmac.compare_digest(supplied, token.encode("utf-8"))


async def _forbidden(send) -> None:
    body = b'{"error":"forbidden"}'
    await send({"type": "http.response.start", "status": 403,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def install(agent: Any) -> None:
    """Wrap the agent's ASGI server so its registered REST endpoints pass permitted() first. Raises RuntimeError when
    the server is not the uagents shape this was written for (uagents==0.26.1): no gate means no start, never an open chat."""
    server = getattr(agent, "_server", None)
    if server is None or not callable(server) or not isinstance(getattr(server, "_rest_handler_map", None), dict):
        raise RuntimeError("cannot gate the buyer's REST chat: the uagents server has an unexpected shape")
    base = type(server)
    if getattr(base, "_rest_gated", False):
        return

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            guarded = {end for (_, _, end) in self._rest_handler_map} - RESERVED
            if scope.get("path") in guarded and not permitted(scope):
                return await _forbidden(send)
        return await base.__call__(self, scope, receive, send)

    server.__class__ = type("Gated" + base.__name__, (base,), {"__call__": __call__, "_rest_gated": True})
