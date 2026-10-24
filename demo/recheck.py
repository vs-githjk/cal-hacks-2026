"""Live re-check of the winning price right before the call (night run 2, T7; claim C5).

recheck() asks Bright Data (data.baselines.brightdata, one scrape of the winner's page, inside its call budget) what the
winning listing costs NOW. The answer is LIVE at fetch time only. With no key, or when the live price cannot be read,
the quoted MIRROR price stays and says so: nothing is guessed and no price is invented.

States: ok (same price, in stock) | price_changed | out_of_stock | stock_unknown (price read, availability missing or
unrecognised: never called sold out) | slow | empty | not_configured | skipped (live re-check off in this run). `detail` carries the
brightdata reason (blocked, not_active, error, budget, ...) when a fetch returned nothing, so it is never hidden.
stop_reason() turns a result into the one sentence that stops the call, or None when the call may go on.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable, Optional

from demo.common import LIVE, MIRROR, money

CENT = 0.005


def _status_default() -> dict:
    from data.baselines import brightdata
    return brightdata.status()


def _fetch_default(*, urls):
    from data.baselines import brightdata
    return brightdata.observations(urls=urls)


def _live_price(v) -> Optional[float]:
    """The row's price as a positive finite number, or None. NaN compares false against every price and 0 or a negative
    reads as 'cheaper', so either would let the call go on as a LIVE read; a bool is not a price."""
    if isinstance(v, bool):
        return None
    try:
        p = float(v)
    except (TypeError, ValueError):
        return None
    return p if math.isfinite(p) and p > 0 else None


def will_fetch(fetch: Optional[Callable] = None) -> bool:
    """True when recheck() is about to make a network call (a key is set, or a fetch was injected)."""
    return fetch is not None or bool(_status_default()["configured"])


def recheck(listing: dict, *, fetch: Optional[Callable] = None, status: Optional[Callable] = None,
            now: Optional[datetime] = None) -> dict:
    """listing: {url, price (the quoted unit price)}. Returns {state, price, fetched_at, origin, detail?}."""
    from data.baselines import brightdata
    now = now or datetime.now(timezone.utc)
    if fetch is None:
        fetch = _fetch_default
        status = status or _status_default
    status = status or (lambda: {"last_result": "empty"})
    try:
        rows = fetch(urls=[listing["url"]])
    except brightdata.NotConfigured:
        return {"state": "not_configured", "price": None, "fetched_at": None, "origin": MIRROR}
    here = [r for r in rows if r.get("url") == listing["url"] and r.get("price") is not None]
    mine = [r for r in here if _live_price(r["price"]) is not None]
    if not mine:
        reason = "unreadable_price" if here else str(status().get("last_result") or "empty")
        state = "slow" if reason == "slow" else "empty"
        out = {"state": state, "price": None, "fetched_at": None, "origin": MIRROR}
        if state == "empty":
            out["detail"] = reason
        return out
    r = mine[0]
    price = _live_price(r["price"])
    raw = r.get("availability")
    if r.get("in_stock"):
        state = "ok" if abs(price - float(listing["price"])) < CENT else "price_changed"
    elif brightdata.stock_state(raw) == "out":
        state = "out_of_stock"
    else:
        state = "stock_unknown"   # in_stock is False for a missing or unrecognised availability too: say so, do not stop on it
    return {"state": state, "price": price, "fetched_at": r.get("observed_at") or now.isoformat(), "origin": LIVE,
            "quoted": float(listing["price"]), "availability": raw if isinstance(raw, str) else None}


def skipped() -> dict:
    """The result when the live re-check is switched off (bridge, stage and rehearse stay offline)."""
    return {"state": "skipped", "price": None, "fetched_at": None, "origin": MIRROR}


def raw_text(result: dict) -> str:
    """The availability value as read, for the stock_unknown line: short, one line, 'no value' when empty."""
    v = " ".join(str(result.get("availability") or "").split())[:40]
    return f"'{v}'" if v else "no value"


def stop_reason(result: dict, quoted: float, cap: float) -> Optional[str]:
    """The reason the call must not be placed, or None. Out of stock stops it. A live price above the quote stops it
    (the mandate is for the quoted amount), also when the stock could not be read, and the line says when it is also
    above the cap. A cheaper live price does not stop it. Unreadable stock alone does not stop it."""
    state, price = result.get("state"), result.get("price")
    if state == "out_of_stock":
        return f"the winning listing is out of stock now ({money(price)} live)"
    if state in ("price_changed", "stock_unknown") and price is not None and price > quoted + CENT:
        if price > cap + CENT:
            return f"the live price rose to {money(price)}, above the {money(cap)} cap (quoted {money(quoted)})"
        return f"the live price rose to {money(price)} from the quoted {money(quoted)}, and the mandate covers only the quote"
    return None


def clock(result: dict) -> str:
    """HH:MM:SS UTC of the fetch."""
    try:
        return datetime.fromisoformat(result["fetched_at"].replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%H:%M:%S UTC")
    except (ValueError, TypeError, AttributeError):
        return "time unknown"
