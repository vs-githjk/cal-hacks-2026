"""Bazaar Shield product layer (Lane C, c9): API keys, a rate limit per key, a usage meter, OpenAPI docs.
Wraps a fresh instance of Lane D's core (`shield.api.create_app()`); the core module is not changed and stays
keyless for our own agents. Serve the keyed API with:

    python3 -m uvicorn shield.product:create_product_app --factory --port 8788
    python3 -m shield.product new-key <caller>        # prints the key once; only its sha256 is stored

Every /v1 call needs `X-API-Key: <key>` or `Authorization: Bearer <key>`, except health and the docs
(/docs, /openapi.json). A key-less or unknown key gets 401, over the limit gets 429. The meter stores the key's
hash, caller name, endpoint, status and time: never a key and never a message body (invariant 10). The pricing
unit is one successful (status below 400) call; the price is set after a design partner.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse

from data.claim_check import check_claim
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
        """Billable calls by endpoint: only responses below 400 count (a 401, 413, 422 or 429 is never billed)."""
        with self._lock:
            rows = self._db.execute("SELECT endpoint, COUNT(*) FROM usage WHERE key_hash = ? AND status < 400 GROUP BY endpoint",
                                    (_hash(key),))
            return dict(rows.fetchall())

    def refused(self, key: str) -> dict:
        """Calls that were not billed, by endpoint and status."""
        out: dict = {}
        with self._lock:
            for endpoint, status, n in self._db.execute(
                    "SELECT endpoint, status, COUNT(*) FROM usage WHERE key_hash = ? AND status >= 400 GROUP BY endpoint, status",
                    (_hash(key),)):
                out.setdefault(endpoint, {})[str(status)] = n
        return out


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


MAX_PAGE_BYTES = 2 * 1024 * 1024  # a listing page larger than 2 MB is refused (could not verify)
MAX_REDIRECTS = 3
UA = "TechBazaar-claim-check/0.1 (hackathon research)"
CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _allowed(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text.split("%")[0])
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or (ip.version == 4 and ip in CGNAT))


def _resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {host}") from e


def _request(scheme: str, host: str, port: int, path: str, ip: str, timeout: float):
    """One GET to the already-checked IP (no second DNS lookup), with Host and TLS SNI set to the name."""
    import http.client
    import ssl
    sock = socket.create_connection((ip, port), timeout=timeout)
    if scheme == "https":
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        conn.sock = ctx.wrap_socket(sock, server_hostname=host)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock
    conn.request("GET", path, headers={"Host": host, "User-Agent": UA})
    r = conn.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read


def guarded_get(url: str, *, resolve=_resolve, request=_request, max_bytes: int = MAX_PAGE_BYTES,
                max_redirects: int = MAX_REDIRECTS, timeout: float = 15.0) -> bytes:
    """Fetch a caller-supplied URL safely: http(s) only; every hop's host is resolved and EVERY address must be public
    (no localhost, private, link-local or cloud metadata, CGNAT, reserved, multicast); we connect to the checked IP
    itself, so DNS cannot change between check and connect; redirects are followed by hand and re-checked; the body
    is capped at max_bytes. Any refusal raises ValueError, which the claim check reports as could not verify."""
    from urllib.parse import urljoin
    for _ in range(max_redirects + 1):
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ValueError("only http and https URLs with a host are fetched")
        ips = resolve(p.hostname)
        if not ips or not all(_allowed(ip) for ip in ips):
            raise ValueError("address not allowed")
        port = p.port or (443 if p.scheme == "https" else 80)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        status, headers, read = request(p.scheme, p.hostname, port, path, ips[0], timeout)
        if status in (301, 302, 303, 307, 308):
            if not headers.get("location"):
                raise ValueError("redirect without a location")
            url = urljoin(url, headers["location"])
            continue
        if status != 200:
            raise ValueError(f"http {status}")
        body = read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError(f"page too large (over {max_bytes} bytes)")
        return body
    raise ValueError("too many redirects")


public_fetch = guarded_get


def _key_from(request: Request) -> Optional[str]:
    key = request.headers.get("x-api-key")
    auth = request.headers.get("authorization", "")
    if not key and auth.lower().startswith("bearer "):
        key = auth[7:].strip()
    return key or None


def create_product_app(keys: Optional[KeyStore] = None, meter: Optional[Meter] = None,
                       per_minute: int = int(os.environ.get("SHIELD_RATE_PER_MINUTE", DEFAULT_PER_MINUTE)),
                       claim_fetch: Optional[Callable[[str], bytes]] = None):
    keys, meter, limit = keys or KeyStore(), meter or Meter(), RateLimit(per_minute)
    claim_fetch = claim_fetch or public_fetch
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
        if path != "/v1/usage" and not limit.allow(_hash(key)):  # reading your own usage is never rate limited
            meter.record(key, caller, path, 429)
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
        request.state.caller, request.state.key = caller, key
        response = await call_next(request)
        if path != "/v1/usage":
            meter.record(key, caller, path, response.status_code)
        return response

    @app.post("/v1/check-claim")
    def check_claim_route(claim: dict[str, Any] = Body(...)):
        """Check one seller claim against its live page: verified, unverified or false, with evidence URL, time,
        method, page hash and a neutral reason. A page we cannot or may not read is unverified, never false."""
        for name in ("id", "bid_id", "text", "kind", "evidence_url", "field"):
            if name in claim and not isinstance(claim[name], str):
                raise HTTPException(status_code=422, detail=f"{name} must be a string")
        if "value" in claim and not isinstance(claim["value"], (str, int, float, bool)):
            raise HTTPException(status_code=422, detail="value must be a string, number or boolean")
        return check_claim(claim, fetch=claim_fetch)

    @app.get("/v1/usage")
    def usage(request: Request):
        """Your own billable calls by endpoint (the pricing unit: one successful call), plus refused calls by status."""
        return {"caller": request.state.caller, "calls": meter.counts(request.state.key), "refused": meter.refused(request.state.key)}

    return app


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "new-key":
        print(KeyStore().new(sys.argv[2]))
    else:
        sys.exit("usage: python3 -m shield.product new-key <caller>")
