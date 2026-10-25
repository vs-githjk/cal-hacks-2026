"""Central Comp MIRROR (seller_6): a real, dated listing as a price anchor, re-checked every round.

Each bid request asks the existing Bright Data path (demo.recheck, which calls data.baselines.brightdata) what the
listing costs now. With no BRIGHT_DATA_API_KEY nothing is fetched: the bid is the dated snapshot, labelled with when it
was captured. A live read that comes back with a price replaces the snapshot price and the label says it was re-checked
live and when. A listing that is out of stock now is not bid. Anything else (empty, slow, blocked, budget, an error, or
no answer within TIMEOUT_S) keeps the snapshot and says why. No price is ever guessed.

Never orderable: the store never joined, the seller dict keeps orderable False, and no money path may pay it
(data.mirror.not_partners, the Advocate's mirror_not_orderable veto). Honest limit today: Bright Data has scrapers for
Best Buy, Newegg, Micro Center and B&H only, so for centralcomputers.com a keyed re-check comes back empty and the
snapshot stays, with that stated on the bid.
"""
from __future__ import annotations

import asyncio
import copy
import re
from datetime import datetime, timezone
from typing import Callable, Optional

from data.mirror import central_computers as cc
from demo import recheck as recheck_mod

TIMEOUT_S = 8.0
LIVE_STATES = {"ok", "price_changed", "stock_unknown"}
WHY = {"not_configured": "no Bright Data key is set",
       "skipped": "live re-check is off in this run",
       "empty": "Bright Data returned no record for this listing",
       "slow": "Bright Data was too slow",
       "timeout": "Bright Data did not answer in time",
       "error": "the live re-check failed"}


def capture_time(snapshot_id: str) -> str:
    """centralcomputers-20261024T2112Z -> 2026-10-24 21:12 UTC."""
    m = re.search(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})Z", snapshot_id or "")
    return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]} UTC" if m else "an unknown time"


def _clock(result: dict) -> str:
    return recheck_mod.clock(result)


def _snapshot(s: dict, state: str) -> tuple[dict, dict]:
    listing = s["listings"][cc.SKU]
    why = WHY.get(state, WHY["error"])
    label = (f"Snapshot captured {capture_time(s['mirror_snapshot_id'])} at ${listing['price']:,.2f}; live re-check "
             f"did not run: {why}.")
    anchor = {"source": "snapshot", "state": state, "price": listing["price"], "quoted": listing["price"],
              "as_of": capture_time(s["mirror_snapshot_id"]), "listing_url": listing["listing_url"], "label": label}
    return copy.deepcopy(s), anchor


def refresh(s: dict, *, recheck_fn: Optional[Callable] = None, now: datetime | None = None) -> tuple[dict | None, dict]:
    """(the seller dict to bid with, the price anchor). The dict is None when the listing is out of stock right now.
    `s` is never changed."""
    listing = s["listings"][cc.SKU]
    quoted = float(listing["price"])
    now = now or datetime.now(timezone.utc)
    try:
        result = (recheck_fn or recheck_mod.recheck)({"url": listing["listing_url"], "price": quoted}, now=now)
        state = result.get("state") if isinstance(result, dict) else "error"
    except Exception:  # noqa: BLE001  (a failing re-check never stops the bid; the snapshot says so)
        return _snapshot(s, "error")
    if state == "out_of_stock":
        return None, {"source": "live", "state": state, "price": None, "quoted": quoted, "as_of": _clock(result),
                      "listing_url": listing["listing_url"],
                      "label": f"Out of stock at the store when re-checked live at {_clock(result)}; no bid."}
    if state in LIVE_STATES and result.get("price") is not None and result.get("origin") == recheck_mod.LIVE:
        price = float(result["price"])
        out = copy.deepcopy(s)
        out["listings"][cc.SKU]["price"] = price
        out["listings"][cc.SKU]["floor"] = round(price * cc.FLOOR_OF_LIST, 2)
        moved = "unchanged" if abs(price - quoted) < recheck_mod.CENT else f"was ${quoted:,.2f} in the snapshot"
        label = f"Re-checked live through Bright Data at {_clock(result)}: ${price:,.2f} ({moved})."
        anchor = {"source": "live", "state": state, "price": price, "quoted": quoted, "as_of": _clock(result),
                  "listing_url": listing["listing_url"], "label": label}
        out["trace_prefix"] = f"{s['trace_prefix']} {label}"
        return out, anchor
    out, anchor = _snapshot(s, state if state in WHY else "error")
    out["trace_prefix"] = f"{s['trace_prefix']} {anchor['label']}"
    return out, anchor


async def refresh_async(s: dict, *, recheck_fn: Optional[Callable] = None, timeout: float = TIMEOUT_S,
                        now: datetime | None = None) -> tuple[dict | None, dict]:
    """refresh() in a worker thread with a hard time limit, so a slow scrape can never hold the sealed round."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(refresh, s, recheck_fn=recheck_fn, now=now), timeout)
    except asyncio.TimeoutError:
        out, anchor = _snapshot(s, "timeout")
        out["trace_prefix"] = f"{s['trace_prefix']} {anchor['label']}"
        return out, anchor


def annotate(bid: dict, anchor: dict) -> dict:
    """The bid with its price anchor (additive key: where the price came from and when)."""
    return {**bid, "price_anchor": dict(anchor)}
