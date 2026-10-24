"""FastAPI app for Bazaar Shield. Run: python3 -m uvicorn shield.api:app --port 8787

POST /v1/shield/screen          screen one message (also at /screen for Lane A's agents)
POST /v1/shield/verify-mandate  verify a signed payment request against its mandate
GET  /v1/shield/rules           the rule ids
GET  /v1/shield/health
Lane C wraps this core with OpenAPI docs, keys, rate limits and metering.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from fastapi import Body, FastAPI

from pay.replay import NonceStore
from shield import VERSION, service
from shield.rules import RULES


def create_app(keys: Optional[Mapping] = None, store: Optional[NonceStore] = None) -> FastAPI:
    keys = service.keys_from_env() if keys is None else keys
    store = service.store_from_env() if store is None else store
    app = FastAPI(title="Bazaar Shield", version=VERSION)

    @app.post("/v1/shield/screen")
    def screen_route(payload: dict[str, Any] = Body(...)):
        return service.handle_screen(payload)

    @app.post("/screen", include_in_schema=False)
    def screen_alias(payload: dict[str, Any] = Body(...)):
        return service.handle_screen(payload)

    @app.post("/v1/shield/verify-mandate")
    def verify_route(payload: dict[str, Any] = Body(...)):
        return service.handle_verify_mandate(payload, keys, store)

    @app.get("/v1/shield/rules")
    def rules_route():
        return {"version": VERSION, "rules": [
            {"id": r.id, "action": r.action, "severity": r.severity, "describe": r.describe} for r in RULES]}

    @app.get("/v1/shield/health")
    def health_route():
        return {"status": "ok", "version": VERSION}

    return app


app = create_app()
