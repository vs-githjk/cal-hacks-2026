"""FastAPI app for Bazaar Shield. Run: python3 -m uvicorn shield.api:app --port 8787

POST /v1/shield/screen          screen one message (also at /screen for Lane A's agents)
POST /v1/shield/verify-mandate  verify a signed payment request against its mandate
POST /v1/advocate/reason       advocate verdict in, closed-schema call reason out (a10, templates only)
POST /v1/shield/verify-agent    check an agent address, claimed role and seller of record against the registry
GET  /v1/shield/rules           the rule ids
GET  /v1/shield/health
Lane C wraps this core with OpenAPI docs, keys, rate limits and metering.

SHIELD_API_TOKEN (optional, #449 RT-26): unset, this core is open (our own agents on loopback, as before). Set, every
route except GET /v1/shield/health needs `Authorization: Bearer <token>`; agents/common.py screen() sends it. The keyed
product (shield/product.py) has its own API keys and builds its core without this token.
"""
from __future__ import annotations

import hmac
import os
from typing import Any, Mapping, Optional

from fastapi import Body, FastAPI

from pay.replay import NonceStore
from shield import VERSION, service
from shield.registry import Registry
from shield.rules import RULES


MAX_BODY_BYTES = 64 * 1024  # larger request bodies get 413; callers must treat any non-200 as block
_DEFAULT_RECEIPT_KEY = object()
_TOKEN_FROM_ENV = object()
OPEN_PATHS = {"/v1/shield/health"}   # a liveness probe needs no secret; it answers status and version only


class BodyLimit:
    """ASGI middleware: refuse request bodies over `limit` bytes with 413 before any parsing."""

    def __init__(self, app, limit: int = MAX_BODY_BYTES):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.limit:
            return await self._reject(send)
        messages, size = [], 0
        while True:
            msg = await receive()
            messages.append(msg)
            if msg["type"] != "http.request":
                break
            size += len(msg.get("body", b""))
            if size > self.limit:
                return await self._reject(send)
            if not msg.get("more_body"):
                break
        it = iter(messages)

        async def replay():
            try:
                return next(it)
            except StopIteration:
                return await receive()

        return await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send):
        body = b'{"detail":"request body too large"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class TokenGate:
    """ASGI middleware (#449 RT-26): refuse any request but OPEN_PATHS that lacks `Authorization: Bearer <token>`, with
    a constant-time compare, before any body is read. Added after BodyLimit, so it is the outer layer."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in OPEN_PATHS:
            return await self.app(scope, receive, send)
        supplied = b""
        for name, value in scope["headers"]:
            if name.lower() == b"authorization":
                scheme, _, rest = value.decode("latin-1").partition(" ")
                if scheme.lower() == "bearer":
                    supplied = rest.strip().encode("utf-8")
                break
        if hmac.compare_digest(supplied, self.token):
            return await self.app(scope, receive, send)
        body = b'{"detail":"missing or wrong bearer token"}'
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"www-authenticate", b"Bearer")]})
        await send({"type": "http.response.body", "body": body})


def create_app(keys: Optional[Mapping] = None, store: Optional[NonceStore] = None,
               registry: Optional[Registry] = None, receipt_private_key=_DEFAULT_RECEIPT_KEY,
               api_token=_TOKEN_FROM_ENV) -> FastAPI:
    keys = service.keys_from_env() if keys is None else keys
    store = service.store_from_env() if store is None else store
    registry = service.registry_from_env() if registry is None else registry
    if receipt_private_key is _DEFAULT_RECEIPT_KEY:
        receipt_private_key = service.receipt_private_key_from_env()
    app = FastAPI(title="Smell Test", version=VERSION)
    app.add_middleware(BodyLimit)
    token = (os.environ.get("SHIELD_API_TOKEN") if api_token is _TOKEN_FROM_ENV else api_token) or ""
    if token.strip():
        app.add_middleware(TokenGate, token=token.strip())   # last added = outermost: it runs before BodyLimit

    @app.post("/v1/shield/screen")
    def screen_route(payload: dict[str, Any] = Body(...)):
        return service.handle_screen(payload)

    @app.post("/v1/shield/screen-payment")
    def screen_payment_route(payload: dict[str, Any] = Body(...)):
        return service.handle_screen_payment(payload, registry, receipt_private_key)

    @app.post("/screen", include_in_schema=False)
    def screen_alias(payload: dict[str, Any] = Body(...)):
        return service.handle_screen(payload)

    @app.post("/v1/shield/verify-mandate")
    def verify_route(payload: dict[str, Any] = Body(...)):
        return service.handle_verify_mandate(payload, keys, store)

    @app.post("/v1/shield/verify-agent")
    def verify_agent_route(payload: dict[str, Any] = Body(...)):
        return service.handle_verify_agent(payload, registry)

    @app.post("/v1/advocate/reason")
    def advocate_reason_route(payload: dict[str, Any] = Body(...)):
        return service.handle_advocate_reason(payload)

    @app.get("/v1/shield/rules")
    def rules_route():
        return {"version": VERSION, "rules": [
            {"id": r.id, "action": r.action, "severity": r.severity, "describe": r.describe} for r in RULES]}

    @app.get("/v1/shield/health")
    def health_route():
        return {"status": "ok", "version": VERSION}

    return app


app = create_app()
