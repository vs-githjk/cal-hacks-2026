"""Bright Data Scraper API as a real, env-gated price source (c11, issue #47; night run 2 T6).

observations() returns the same row dicts as data.baselines.observations() with provider "brightdata" and origin "LIVE"
(LIVE only at fetch time: once stored it is MIRROR, dated), so baseline() needs no change. Without BRIGHT_DATA_API_KEY it
raises NotConfigured before any network attempt.

How it fails, always visibly through status()["last_result"] and never with an invented price:
  ok | slow (202, still running after 3 polls) | empty (no record, dead page or no price) | blocked (429, one request,
  then a 5 minute cooldown with no calls) | not_active (HTTP 400 "Customer is not active", no retry) | error | budget
  (BRIGHT_DATA_MAX_CALLS scrape calls per process, default 8) | not_configured.

The key is read from the environment at call time, sent only as `Authorization: Bearer <key>`, and never put in a status,
a log line or an exception text (errors are recorded by class name only).
"""
from __future__ import annotations

import json
import math
import os
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TARGETS_FILE = HERE / "brightdata_targets.json"
API = "https://api.brightdata.com/datasets/v3"
FIELDS = "url|title|final_price|availability|sku"
DEFAULT_SKU = "rtx 5070 ti"
DEFAULT_MAX_CALLS = 8
MAX_POLLS = 3
DEFAULT_RETRY_AFTER = 3.0
MAX_RETRY_AFTER = 10.0
COOLDOWN_SECONDS = 300.0  # 25 requests in 5 minutes blocks the IP; after a 429 we make no call for this long
TIMEOUT = httpx.Timeout(60.0, connect=15.0)  # the live smoke took about 20 s
HOSTS = {"bestbuy.com": "bestbuy", "newegg.com": "newegg", "microcenter.com": "microcenter", "bhphotovideo.com": "bh"}
PRIORITY = ("blocked", "not_active", "slow", "error", "empty", "budget")


class NotConfigured(RuntimeError):
    pass


_state: dict = {"calls": 0, "last_call": None, "last_result": None, "blocked_until": 0.0, "error": None}


def reset() -> None:
    """Forget the per-process call count, cooldown and last result (tests; a fresh process starts like this)."""
    _state.update({"calls": 0, "last_call": None, "last_result": None, "blocked_until": 0.0, "error": None})


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _key() -> str | None:
    return os.environ.get("BRIGHT_DATA_API_KEY") or None


def max_calls() -> int:
    raw = os.environ.get("BRIGHT_DATA_MAX_CALLS")
    try:
        return max(0, int(raw)) if raw not in (None, "") else DEFAULT_MAX_CALLS
    except ValueError:
        return DEFAULT_MAX_CALLS


def load_stores() -> dict:
    return json.loads(TARGETS_FILE.read_text())["stores"]


def load_targets() -> list[dict]:
    return json.loads(TARGETS_FILE.read_text())["targets"]


def last_error() -> str | None:
    """The class name of the last transport or parse failure (never a message, so it cannot carry the key)."""
    return _state["error"]


def status() -> dict:
    configured = _key() is not None
    last = _state["last_result"]
    if last is None and not configured:
        last = "not_configured"
    return {"sponsor": "brightdata", "configured": configured, "last_call": _state["last_call"], "last_result": last}


def _tls() -> ssl.SSLContext:
    """Normal certificate checking, never disabled. certifi when installed (the python.org build has no system CAs)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _price(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        v = re.sub(r"[^0-9.]", "", v)
    try:
        p = float(v)
    except (TypeError, ValueError):
        return None
    return round(p, 2) if math.isfinite(p) and p > 0 else None


def _in_stock(availability) -> bool:
    """Unknown or unreadable availability is NOT in stock, so it can never enter a median or win a bid."""
    a = re.sub(r"[^a-z]", "", str(availability or "").lower())
    if not a or any(w in a for w in ("outofstock", "soldout", "unavailable", "notavailable", "preorder", "comingsoon", "backorder", "discontinued")):
        return False
    return "instock" in a or "available" in a or "limitedstock" in a


def _rows_from(records, target: dict, store_info: dict, now: datetime, snapshot_id: str | None) -> list[dict]:
    rows = []
    for rec in records if isinstance(records, list) else []:
        if not isinstance(rec, dict) or rec.get("error") or rec.get("error_code"):
            continue  # include_errors=true returns dead pages as error records: show nothing, fill nothing in
        price = _price(rec.get("final_price"))
        if price is None:
            continue
        rows.append({"provider": "brightdata", "store": target["store"], "sku": target.get("sku", DEFAULT_SKU), "price": price,
                     "in_stock": _in_stock(rec.get("availability")), "condition": "new", "kind": "ask",
                     "observed_at": _iso(now), "url": target["url"], "snapshot_id": snapshot_id, "origin": "LIVE",
                     "title": rec.get("title") if isinstance(rec.get("title"), str) else None,
                     "retailer_sku": str(rec["sku"]) if rec.get("sku") not in (None, "") else None,
                     "mapping": store_info.get("mapping", "unverified")})
    return rows


def _retry_after(resp: httpx.Response) -> float:
    try:
        return min(max(float(resp.headers.get("retry-after", DEFAULT_RETRY_AFTER)), 0.0), MAX_RETRY_AFTER)
    except ValueError:
        return DEFAULT_RETRY_AFTER


def _one(client: httpx.Client, headers: dict, target: dict, store_info: dict, now: datetime) -> tuple[str, list[dict]]:
    """One target, one scrape request. Returns (state, rows). Never retries a failure; only a 202 is polled."""
    resp = client.post(f"{API}/scrape", params={"dataset_id": store_info["dataset_id"], "format": "json", "include_errors": "true"},
                       json={"input": [{"url": target["url"]}], "custom_output_fields": FIELDS}, headers=headers)
    if resp.status_code == 429:
        return "blocked", []
    if resp.status_code == 400 and "not active" in resp.text.lower():
        return "not_active", []
    snapshot_id = None
    if resp.status_code == 202:
        try:
            snapshot_id = str(resp.json()["snapshot_id"])
        except (ValueError, KeyError, TypeError):
            return "error", []
        wait = _retry_after(resp)
        for i in range(MAX_POLLS):
            _sleep(wait)
            prog = client.get(f"{API}/progress/{snapshot_id}", headers=headers)
            if prog.status_code == 429:
                return "blocked", []
            if prog.status_code != 200:
                return "error", []
            try:
                phase = str(prog.json().get("status", "")).lower()
            except (ValueError, AttributeError):
                return "error", []
            if phase == "ready":
                resp = client.get(f"{API}/snapshot/{snapshot_id}", params={"format": "json"}, headers=headers)
                if resp.status_code == 429:
                    return "blocked", []
                break
            if phase in ("failed", "error"):
                return "error", []
            wait = _retry_after(prog)
        else:
            return "slow", []
    if resp.status_code != 200:
        return "error", []
    try:
        records = resp.json()
    except ValueError:
        return "error", []
    rows = _rows_from(records, target, store_info, now, snapshot_id)
    return ("ok" if rows else "empty"), rows


def _target_for(url: str, sku: str) -> dict | None:
    for t in load_targets():
        if t["url"] == url:
            return t
    host = re.sub(r"^www\.", "", httpx.URL(url).host or "")
    store = next((s for h, s in HOSTS.items() if host == h or host.endswith("." + h)), None)
    return {"store": store, "sku": sku, "name": url, "url": url} if store else None


def observations(skus=(DEFAULT_SKU,), *, client: httpx.Client | None = None, now: datetime | None = None,
                 urls=None) -> list[dict]:
    """Live asks for the SKUs' target pages (brightdata_targets.json), or only for `urls` (the re-check path).

    Raises NotConfigured with no BRIGHT_DATA_API_KEY and makes no request. Every other outcome returns the rows found
    (maybe []), with the reason in status()["last_result"]."""
    key = _key()
    if not key:
        _state["last_result"] = "not_configured"
        raise NotConfigured("BRIGHT_DATA_API_KEY is not set")
    skus = tuple(skus)
    if urls is not None:
        targets = [t for t in (_target_for(u, skus[0] if skus else DEFAULT_SKU) for u in urls) if t]
    else:
        targets = [t for t in load_targets() if t.get("sku", DEFAULT_SKU) in skus]
    now = now or datetime.now(timezone.utc)
    if time.monotonic() < _state["blocked_until"]:
        _state["last_result"] = "blocked"
        return []
    stores = load_stores()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    own = client is None
    http = client or httpx.Client(verify=_tls(), timeout=TIMEOUT)
    rows: list[dict] = []
    states: list[str] = []
    try:
        for t in targets:
            if _state["calls"] >= max_calls():
                states.append("budget")
                break
            _state["calls"] += 1
            _state["last_call"] = _iso(now)
            try:
                state, got = _one(http, headers, t, stores[t["store"]], now)
            except (httpx.HTTPError, KeyError) as e:
                _state["error"] = type(e).__name__
                state, got = "error", []
            states.append(state)
            rows.extend(got)
            if state == "blocked":
                _state["blocked_until"] = time.monotonic() + COOLDOWN_SECONDS
                break
            if state == "not_active":
                break
    finally:
        if own:
            http.close()
    if "blocked" in states or "not_active" in states:
        result = "blocked" if "blocked" in states else "not_active"
    elif rows:
        result = "ok"
    else:
        result = next((s for s in PRIORITY if s in states), "empty")
    _state["last_result"] = result
    return rows
