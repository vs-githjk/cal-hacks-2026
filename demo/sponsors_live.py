"""Bright Data and Tiger Data in the live run (#269), next to the CRS check and the call.

On --live-call the bridge loads the sponsor keys from the same env file the call uses (load_sponsor_env; the process
environment wins and nothing is printed). Right before the call it re-checks the winner's price with Bright Data
(price_recheck, bounded by a timeout: a slow or failed read keeps the quoted MIRROR price and says so), and after the
round it stores the round's prices in Tiger Data (round_ticks, write_round_ticks). Tiger is never on the money path:
a failed write is one console line and the deal goes on.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import threading
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
    """fn() within `timeout` seconds: its value, its own exception, or cf.TimeoutError. It runs on a daemon thread, so a hung
    network call or database statement can never hold the process at exit (an executor's threads are joined at exit)."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001  (handed to the caller below, on its own thread)
            box["error"] = e

    worker = threading.Thread(target=run, daemon=True, name="sponsor-bounded")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise cf.TimeoutError()
    if "error" in box:
        raise box["error"]
    return box["value"]


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
    """round_result rows as Tiger bid_ticks, with each row's origin (data.tiger.history.round_ticks): rank 1 is the "win",
    rank 0 is "blocked", the rest are "bid", prices in whole cents."""
    from data.tiger import history
    return history.round_ticks(rows, sku, now=now)


def loss_rows(reports: list, rows: list, sku: str, *, now: Optional[datetime] = None) -> list[dict]:
    """A round's LossReports as Tiger loss_reports rows (data.tiger.history.loss_rows)."""
    from data.tiger import history
    return history.loss_rows(reports, rows, sku, now=now)


def _write(name: str, rows: list[dict], timeout: float) -> dict:
    from data.tiger import store
    if not store.status()["configured"]:
        return {"state": "not_configured", "n": 0}
    if not rows:
        return {"state": "empty", "n": 0}
    try:
        res = _bounded(lambda: getattr(store, name)(rows), timeout)
        n = res.get("inserted", 0) if isinstance(res, dict) else 0
        return {"state": "written" if n else "empty", "n": int(n), "result": res}
    except cf.TimeoutError:   # the write may still finish in the background: unconfirmed, not "not written"
        return {"state": "unconfirmed", "n": 0, "detail": f"over {timeout:g} s"}
    except store.TigerError as e:   # its message is redacted by the store: no connection string, password or host
        return {"state": "error", "n": 0, "detail": str(e)[:120]}
    except Exception as e:  # noqa: BLE001
        return {"state": "error", "n": 0, "detail": type(e).__name__}


def write_round_ticks(ticks: list[dict], *, timeout: float = TIGER_TIMEOUT_S) -> dict:
    """data.tiger.store.write_bid_ticks, within `timeout`. {"state": written | not_configured | error, ...}."""
    return _write("write_bid_ticks", ticks, timeout)


def write_loss_reports(rows: list[dict], *, timeout: float = TIGER_TIMEOUT_S) -> dict:
    """data.tiger.store.write_loss_reports, within `timeout`; the same states as write_round_ticks."""
    return _write("write_loss_reports", rows, timeout)


def tiger_note(result: dict, round_id: str, what: str = "bid ticks") -> str:
    """One console line for a Tiger write; it is also logged (logger demo.tiger) so a run's log shows the status."""
    state = result.get("state")
    ticks = what == "bid ticks"
    table, label, noun = ("bid_ticks", "", "prices") if ticks else ("loss_reports", f"{what} ", what)
    if state == "written":
        tail = "; the price history curve is market_1h and bid_curve_10s" if ticks else ""
        line = f"Tiger Data: wrote {result.get('n', 0)} {what} for {round_id} ({table}{tail})"
    elif state == "not_configured":
        line = f"Tiger Data: not configured (TIGER_DATA_SERVICE_URL), so the round's {noun} were not stored"
    elif state == "empty":
        line = f"Tiger Data: stored 0 {what} for {round_id} (nothing new to store)"
    elif state == "unconfirmed":
        line = f"Tiger Data: {label}write not confirmed ({result.get('detail')}); the deal goes on"
    else:
        line = f"Tiger Data: {label}not written ({result.get('detail') or 'error'}); the deal goes on"
    logging.getLogger("demo.tiger").info("%s", line)
    return line
