"""Bazaar Shield product layer (Lane C, c9): API keys, a rate limit per key, a usage meter, OpenAPI docs.
Wraps a fresh instance of Lane D's core (`shield.api.create_app()`); the core module is not changed and stays
keyless for our own agents. Serve the keyed API with:

    python3 -m uvicorn shield.product:create_product_app --factory --port 8788
    python3 -m shield.product new-key <caller>        # prints the key once; only its sha256 is stored

Every /v1 call needs `X-API-Key: <key>` or `Authorization: Bearer <key>`, except health and the docs
(/docs, /openapi.json). A key-less or unknown key gets 401, over the limit gets 429. The meter stores the key's
hash, caller name, endpoint, status and time: never a key and never a message body (invariant 10). The pricing
unit is one metered call; the price is set after a design partner.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from shield.api import create_app

HOME = Path(os.environ.get("SHIELD_PRODUCT_HOME", Path.home() / ".bazaar-shield"))  # outside the repo
PUBLIC = {"/v1/shield/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
DEFAULT_PER_MINUTE = 60


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class KeyStore:
    """API keys by sha256. The plain key is returned once by `new` and never written."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or HOME / "keys.json")
        self._lock = threading.Lock()

    def _load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def new(self, caller: str) -> str:
        key = "sk_shield_" + secrets.token_urlsafe(24)
        with self._lock:
            data = self._load()
            data[_hash(key)] = {"caller": caller, "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=1))
            os.chmod(self.path, 0o600)
        return key

    def caller(self, key: Optional[str]) -> Optional[str]:
        if not key:
            return None
        row = self._load().get(_hash(key))
        return row["caller"] if row else None


class Meter:
    """One row per call: key hash, caller, endpoint, status, time. Counts are the billing unit."""

    def __init__(self, path: Optional[Path] = None):
        self.path = str(path or HOME / "meter.sqlite")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.execute("CREATE TABLE IF NOT EXISTS usage (key_hash TEXT, caller TEXT, endpoint TEXT, status INTEGER, ts REAL)")
        self._lock = threading.Lock()

    def record(self, key: str, caller: str, endpoint: str, status: int) -> None:
        with self._lock:
            self._db.execute("INSERT INTO usage VALUES (?, ?, ?, ?, ?)", (_hash(key), caller, endpoint, status, time.time()))

    def counts(self, key: str) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT endpoint, COUNT(*) FROM usage WHERE key_hash = ? GROUP BY endpoint", (_hash(key),))
            return dict(rows.fetchall())


class RateLimit:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._seen: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key_hash: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._seen[key_hash]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def _key_from(request: Request) -> Optional[str]:
    key = request.headers.get("x-api-key")
    auth = request.headers.get("authorization", "")
    if not key and auth.lower().startswith("bearer "):
        key = auth[7:].strip()
    return key or None


def create_product_app(keys: Optional[KeyStore] = None, meter: Optional[Meter] = None,
                       per_minute: int = int(os.environ.get("SHIELD_RATE_PER_MINUTE", DEFAULT_PER_MINUTE))):
    keys, meter, limit = keys or KeyStore(), meter or Meter(), RateLimit(per_minute)
    app = create_app()
    app.title = "Bazaar Shield API"
    app.description = ("Screen agent-to-agent commerce messages for prompt injection, payee swaps and other attacks. "
                       "Send `X-API-Key` on every /v1 call. Any non-200 response must be treated as block.")

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path in PUBLIC:
            return await call_next(request)
        key = _key_from(request)
        caller = keys.caller(key)
        if caller is None:
            return JSONResponse({"detail": "missing or unknown API key"}, status_code=401)
        if not limit.allow(_hash(key)):
            meter.record(key, caller, path, 429)
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
        request.state.caller, request.state.key = caller, key
        response = await call_next(request)
        if path != "/v1/usage":
            meter.record(key, caller, path, response.status_code)
        return response

    @app.get("/v1/usage")
    def usage(request: Request):
        """Your own metered calls by endpoint (the pricing unit)."""
        return {"caller": request.state.caller, "calls": meter.counts(request.state.key)}

    return app


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "new-key":
        print(KeyStore().new(sys.argv[2]))
    else:
        sys.exit("usage: python3 -m shield.product new-key <caller>")
