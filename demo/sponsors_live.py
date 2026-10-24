"""Bright Data and Tiger Data in the live run (#269), next to the CRS check and the call.

On --live-call the bridge loads the sponsor keys from the same env file the call uses (load_sponsor_env; the process
environment wins and nothing is printed). Right before the call it re-checks the winner's price with Bright Data
(price_recheck, bounded by a timeout: a slow or failed read keeps the quoted MIRROR price and says so), and after the
round it stores the round's prices in Tiger Data (round_ticks, write_round_ticks). Tiger is never on the money path:
a failed write is one console line and the deal goes on.
"""
from __future__ import annotations

import concurrent.futures as cf
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from demo.common import LIVE, MIRROR, money

SPONSOR_ENV = ("BRIGHT_DATA_API_KEY", "BRIGHT_DATA_MAX_CALLS", "TIGER_DATA_SERVICE_URL")
RECHECK_TIMEOUT_S = 45.0   # a Bright Data scrape takes about 20 s in smoke runs; its own read timeout is 75 s
TIGER_TIMEOUT_S = 10.0


def load_sponsor_env(path: Optional[Path]) -> list[str]:
    """Put the sponsor names from the env file into os.environ when the process does not set them already.
    Returns the names taken from the file (never the values)."""
    import os
    taken: list[str] = []
    if path is None:
        return taken
    try:
        lines = Path(path).expanduser().read_text(encoding="utf-8").splitlines()
    except OSError:
        return taken
    for line in lines:
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k in SPONSOR_ENV and v and not os.environ.get(k):
            os.environ[k] = v
            taken.append(k)
    return taken


def _bounded(fn: Callable, timeout: float):
    pool = cf.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=timeout)
    finally:
        pool.shutdown(wait=False)


def price_recheck(listing: dict, *, fetch: Optional[Callable] = None, timeout: float = RECHECK_TIMEOUT_S,
                  now: Optional[datetime] = None) -> dict:
    """demo.recheck.recheck for the winner's listing, within `timeout` seconds. Over time it is state "slow" with the
    quoted MIRROR price kept. No key and no injected fetch: "not_configured", and no request is made."""
    from demo import recheck as R
    if fetch is None and not R.will_fetch():
        return {"state": "not_configured", "price": None, "fetched_at": None, "origin": MIRROR}
    try:
        return _bounded(lambda: R.recheck(listing, fetch=fetch, now=now), timeout)
    except cf.TimeoutError:
        return {"state": "slow", "price": None, "fetched_at": None, "origin": MIRROR, "detail": f"over {timeout:g} s"}
    except Exception as e:  # noqa: BLE001  (never a crash, never a fake LIVE price)
        return {"state": "empty", "price": None, "fetched_at": None, "origin": MIRROR, "detail": type(e).__name__}


def is_live(result: dict) -> bool:
    return result.get("origin") == LIVE and result.get("price") is not None


def price_note(result: dict, quoted: float, *, now: Optional[datetime] = None) -> str:
    """One console line for the re-check."""
    if is_live(result):
        ago = ""
        try:
            at = datetime.fromisoformat(str(result["fetched_at"]).replace("Z", "+00:00"))
            secs = max(0, int(((now or datetime.now(timezone.utc)) - at).total_seconds()))
            ago = f" {secs} s ago"
        except (ValueError, TypeError):
            pass
        return f"price checked live{ago} via Bright Data: {money(result['price'])} (LIVE; quoted {money(quoted)})"
    why = {"not_configured": "not configured", "slow": "too slow"}.get(result.get("state"), result.get("detail") or result.get("state"))
    return f"Bright Data: live price not read ({why}); the quoted MIRROR price stays: {money(quoted)}"


def round_ticks(rows: list, sku: str, *, now: Optional[datetime] = None) -> list[dict]:
    """round_result rows (id, round_id, bid_id, seller_id, persona, rank, landed, reasons) as Tiger bid_ticks:
    rank 1 is the "win", the rest are "bid", prices in whole cents."""
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for r in rows:
        try:
            if isinstance(r[6], bool):
                continue
            price = float(r[6])
            if not (math.isfinite(price) and price > 0):
                continue                     # never a zero, negative or infinite price in the history
        except (TypeError, ValueError, IndexError):
            continue
        rank = str(r[5])
        event = "win" if rank == "1" else "blocked" if rank == "0" else "bid"   # rank 0: disqualified at the close
        out.append({"ts": ts, "round_id": str(r[1]), "sku": sku, "seller_id": str(r[3]), "price_cents": int(round(price * 100)),
                    "event": event})
    return out


def write_round_ticks(ticks: list[dict], *, timeout: float = TIGER_TIMEOUT_S) -> dict:
    """data.tiger.store.write_bid_ticks, within `timeout`. {"state": written | not_configured | error, ...}."""
    from data.tiger import store
    if not store.status()["configured"]:
        return {"state": "not_configured", "n": 0}
    if not ticks:
        return {"state": "empty", "n": 0}
    try:
        res = _bounded(lambda: store.write_bid_ticks(ticks), timeout)
        n = res.get("inserted", 0) if isinstance(res, dict) else 0
        return {"state": "written" if n else "empty", "n": int(n), "result": res}
    except cf.TimeoutError:   # the write may still finish in the background: unconfirmed, not "not written"
        return {"state": "unconfirmed", "n": 0, "detail": f"over {timeout:g} s"}
    except Exception as e:  # noqa: BLE001  (the connection string never reaches the message: store redacts it)
        return {"state": "error", "n": 0, "detail": type(e).__name__}


def tiger_note(result: dict, round_id: str) -> str:
    state = result.get("state")
    if state == "written":
        return (f"Tiger Data: wrote {result.get('n', 0)} bid ticks for {round_id} (bid_ticks; the price history curve is "
                f"market_1h and bid_curve_10s)")
    if state == "not_configured":
        return "Tiger Data: not configured (TIGER_DATA_SERVICE_URL), so the round's prices were not stored"
    if state == "empty":
        return f"Tiger Data: stored 0 bid ticks for {round_id} (nothing new to store)"
    if state == "unconfirmed":
        return f"Tiger Data: write not confirmed ({result.get('detail')}); the deal goes on"
    return f"Tiger Data: not written ({result.get('detail') or 'error'}); the deal goes on"
