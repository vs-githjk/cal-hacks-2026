"""Seller Kit API (Lane D). Run from the repo root: python3 -m uvicorn seller_kit.api:app --port 8791

POST /v1/sellers   a SellerConfig (contracts/SellerConfig.schema.json) -> 201 {id, name, origin, config_path, run_command}
                   text the Listing Injection Screen flags -> 422 {errors: [{field, message}]} with the rule id; a screen that
                   cannot run -> 503 (fails closed); either way nothing is written (seller_kit/screen.py)
                   a config agents/sellers/factory.py refuses -> 422 {errors: [{field, message}]} with every bad field
GET  /v1/sellers   the shops written so far
GET  /v1/needs/open  open needs a shop could bid on, each with an origin label (SIM when nothing real is wired in)

Configs are written only to agents/sellers/custom/<id>.json (gitignored). The id is a schema-checked slug, so it cannot
name another folder; the path is checked again before writing and a symlink in the way is refused. A shop written here
is SIM: the kit cannot verify a real shop, so origin LIVE is refused. Nothing here starts an agent.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import shlex
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / "agents"
CUSTOM_DIR = AGENTS / "sellers" / "custom"
MAX_CUSTOM = 200  # shops on disk; a full folder refuses new ids instead of filling the disk
ORIGINS = ("LIVE", "MIRROR", "SIM")
SEALED_KEYS = ("spend_limit", "cap", "max_price", "budget")  # the buyer's cap never leaves the buyer side

sys.path.insert(0, str(AGENTS / "sellers"))
from factory import ConfigError, validate_config  # noqa: E402

from shield.api import BodyLimit  # noqa: E402  (413 before any parsing, same limit as the other local APIs)
from seller_kit import screen as shop_screen  # noqa: E402
from seller_kit import ucp  # noqa: E402

# SIM sample needs shown when no real source is wired in. Same SKUs the demo sellers list.
SIM_NEEDS: list[dict] = [
    {"id": "need-sim-gpu", "buyer_id": "vidyut", "sku_spec": "rtx 5070 ti", "allowed_conditions": ["new", "open-box"],
     "quantity": 1, "unit": "each", "delivery_window": "by Friday", "origin": "SIM"},
    {"id": "need-sim-psu", "buyer_id": "vidyut", "sku_spec": "psu 750w", "allowed_conditions": ["new", "open-box", "refurbished"],
     "quantity": 1, "unit": "each", "delivery_window": "by Friday", "origin": "SIM"},
    {"id": "need-sim-gpu-2", "buyer_id": "studio-pixel-forge", "sku_spec": "rtx 4070 super 12gb", "allowed_conditions": ["new"],
     "quantity": 4, "unit": "each", "delivery_window": "within 7 days", "origin": "SIM"},
    {"id": "need-sim-case", "buyer_id": "vidyut", "sku_spec": "case", "allowed_conditions": ["new", "used"],
     "quantity": 1, "unit": "each", "delivery_window": "within 10 days", "origin": "SIM"},
]


def sim_needs() -> list[dict]:
    return [dict(n, allowed_conditions=list(n["allowed_conditions"])) for n in SIM_NEEDS]


def _clean_need(row: Any) -> dict | None:
    """One source row as the page may show it: sealed keys dropped, an origin that is not LIVE/MIRROR/SIM read as SIM."""
    if not isinstance(row, dict) or not row.get("sku_spec"):
        return None
    out = {k: v for k, v in row.items() if k not in SEALED_KEYS}
    out["origin"] = row.get("origin") if row.get("origin") in ORIGINS else "SIM"
    return out


def open_needs(source: Callable[[], Any] | None) -> list[dict]:
    """Needs from the source function; any failure, empty or unusable answer gives the labelled SIM samples instead."""
    if source is not None:
        try:
            rows = source()
        except Exception:
            rows = None
        if isinstance(rows, list):
            cleaned = [n for n in map(_clean_need, rows) if n]
            if cleaned:
                return cleaned
    return sim_needs()


def run_command(config_path: Path) -> str:
    return f"cd {shlex.quote(str(AGENTS))} && .venv/bin/python sellers/seller_agent.py --config {shlex.quote(str(config_path))}"


ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,39}")  # fullmatch only: the schema's ^...$ lets a trailing newline through


def _no_constant(name: str):
    raise ValueError(f"{name} is not a JSON number")  # NaN, Infinity and -Infinity pass every <, > check, so refuse them at parse time


def _errors(status: int, errors: list[dict]):
    return JSONResponse({"errors": errors}, status_code=status)


def _one(status: int, field: str, message: str):
    return _errors(status, [{"field": field, "message": message}])


OPERATOR_ENV = "SELLER_KIT_OPERATOR_TOKEN"
OPERATOR_HEADER = "x-operator-token"


def fold_id(seller_id: str) -> str:
    """The id as seeds and agent names see it (agents/sellers/factory.py): - becomes _ and a trailing _agent goes."""
    return seller_id.replace("-", "_").removesuffix("_agent")


def create_app(custom_dir: Path | str | None = None, needs_source: Callable[[], Any] | None = None,
               operator_token: str | None = None, screener: Callable[[str], dict] | None = None):
    folder = Path(os.path.abspath(custom_dir or CUSTOM_DIR))
    # replace=true overwrites a shop's config, and the kit cannot tell one shop from another: only the operator may.
    operator = operator_token if operator_token is not None else os.environ.get(OPERATOR_ENV, "")
    operator = operator.strip()   # a blank or whitespace token is unset: replace stays refused (#237)
    lock = threading.Lock()
    app = FastAPI(title="Tech Bazaar Seller Kit", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit)
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", allow_methods=["GET", "POST", "PUT"],
                       allow_headers=["content-type", OPERATOR_HEADER])

    @app.get("/v1/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/v1/sellers")
    async def add_seller(request: Request, replace: bool = False):
        if not (request.headers.get("content-type") or "").lower().startswith("application/json"):
            return _one(415, "config", "send the config as application/json")
        try:
            cfg = json.loads(await request.body(), parse_constant=_no_constant)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return _one(422, "config", "not valid JSON")
        # #412: the Listing Injection Screen reads the shop's text before the factory sees it and before anything is written.
        try:
            screened = shop_screen.screen_shop(cfg, screener)
        except shop_screen.TooDeep:
            return _one(422, "config", "nested too deeply")
        except shop_screen.ShopScreenUnavailable:
            return _one(503, "config", shop_screen.UNAVAILABLE)   # fail closed: no screen, no shop
        if screened:
            return _errors(422, screened)
        errors: list[dict] = []
        try:
            norm = validate_config(cfg)
        except ConfigError as e:
            norm, errors = None, list(e.errors)
        except RecursionError:
            # attrs is free-form, so a body under the size limit can still nest past the recursion limit in the factory
            return _one(422, "config", "nested too deeply")
        if norm is not None and not ID_RE.fullmatch(norm["id"]):
            errors.append({"field": "id", "message": "must be 2 to 40 characters: lowercase letters, digits, - and _, starting with a letter or digit"})
        if isinstance(cfg, dict) and cfg.get("origin") == "LIVE":
            errors.append({"field": "origin", "message": "must be SIM: the Seller Kit cannot verify a real shop, so a shop it writes is SIM"})
        if errors:
            return _errors(422, errors)
        if replace:
            given = request.headers.get(OPERATOR_HEADER) or ""
            if not operator or not hmac.compare_digest(given.encode(), operator.encode()):
                return _one(403, "replace", f"replace=true needs the operator token ({OPERATOR_HEADER} header, set by {OPERATOR_ENV})")
        return _write(norm, replace)

    def _write(norm: dict, replace: bool):
        path = folder / f"{norm['id']}.json"
        with lock:
            if path.parent != folder or path.is_symlink():
                return _one(422, "id", "does not name a plain file in the custom sellers folder")
            existing = list(folder.glob("*.json")) if folder.is_dir() else []
            twin = next((p.stem for p in existing if p != path and fold_id(p.stem) == fold_id(norm["id"])), None)
            if twin is not None:   # corner_pc and corner-pc_agent would share corner-pc's seed and agent name
                return _one(409, "id", f"{norm['id']} is the same shop id as {twin} (- and _ and a trailing _agent fold together); pick another id")
            if path.exists():
                if not replace:
                    return _one(409, "id", f"{norm['id']} is already a shop here; pick another id or send replace=true")
            elif len(existing) >= MAX_CUSTOM:
                return _one(409, "id", f"limit of {MAX_CUSTOM} custom shops reached; remove one from the folder first")
            folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".new-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(norm, f, indent=2)
                    f.write("\n")
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        return JSONResponse({"id": norm["id"], "name": norm["name"], "origin": norm["origin"], "config_path": str(path),
                             "run_command": run_command(path)}, status_code=201)

    @app.get("/v1/sellers")
    def list_sellers() -> list[dict]:
        rows = []
        for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                cfg = validate_config(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue  # a file the agent would refuse is not a shop
            rows.append({"id": cfg["id"], "name": cfg["name"], "archetype": cfg["archetype"], "origin": cfg["origin"],
                         "skus": list(cfg["listings"]), "config_path": str(p)})
        return rows

    @app.get("/v1/needs/open")
    def needs() -> list[dict]:
        return open_needs(needs_source)

    # ---- #261: UCP on each kit shop (UCP draft spec 2026-01-11, not certified). No money moves through these routes.
    sessions = ucp.Sessions()

    def _shop(shop_id: str):
        shop = ucp.load_shop(folder, shop_id, validate_config)
        return shop if shop is not None and shop["id"] == shop_id else None

    async def _body(request: Request):
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError, RecursionError):
            return None
        return body if isinstance(body, dict) else None

    def _no_shop():
        return JSONResponse({"messages": [ucp._error("not_found", "no such shop")]}, status_code=404)

    def _bad_body():
        return JSONResponse({"messages": [ucp._error("invalid_request", "the body must be a JSON object")]}, status_code=400)

    @app.get("/ucp/{shop_id}/.well-known/ucp")
    def ucp_profile(shop_id: str, request: Request):
        shop = _shop(shop_id)
        return JSONResponse(ucp.profile(shop, str(request.base_url))) if shop else _no_shop()

    @app.post("/ucp/{shop_id}/checkout-sessions")
    async def ucp_create(shop_id: str, request: Request):
        shop, body = _shop(shop_id), await _body(request)
        if not shop:
            return _no_shop()
        if body is None:
            return _bad_body()
        status, out = sessions.create(shop, body)
        return JSONResponse(out, status_code=status)

    @app.get("/ucp/{shop_id}/checkout-sessions/{session_id}")
    def ucp_get(shop_id: str, session_id: str):
        shop = _shop(shop_id)
        s = sessions.get(shop, session_id) if shop else None
        return JSONResponse(ucp.view(s)) if s else JSONResponse({"messages": [ucp._error("not_found", "no such checkout session")]},
                                                               status_code=404)

    @app.put("/ucp/{shop_id}/checkout-sessions/{session_id}")
    async def ucp_update(shop_id: str, session_id: str, request: Request):
        shop, body = _shop(shop_id), await _body(request)
        if not shop:
            return _no_shop()
        if body is None:
            return _bad_body()
        status, out = sessions.update(shop, session_id, body)
        return JSONResponse(out, status_code=status)

    @app.post("/ucp/{shop_id}/checkout-sessions/{session_id}/complete")
    async def ucp_complete(shop_id: str, session_id: str, request: Request):
        from pay.mandate import verify
        shop, body = _shop(shop_id), await _body(request)
        if not shop:
            return _no_shop()
        if body is None:
            return _bad_body()
        status, out = sessions.complete(shop, session_id, body, verify)
        return JSONResponse(out, status_code=status)

    @app.post("/ucp/{shop_id}/checkout-sessions/{session_id}/cancel")
    def ucp_cancel(shop_id: str, session_id: str):
        shop = _shop(shop_id)
        if not shop:
            return _no_shop()
        status, out = sessions.cancel(shop, session_id)
        return JSONResponse(out, status_code=status)

    return app


app = create_app()
