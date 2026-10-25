"""Load dated price observations into Tiger's price_obs (T13).

    python3 -m data.tiger.load --dry-run     # counts only: no env var, no connection, no network
    python3 -m data.tiger.load               # needs TIGER_DATA_SERVICE_URL: schema, then rows, once
    python3 -m data.tiger.load --brightdata  # also one Bright Data fetch (credits); never in a dry run

Only comparable retail asks go in (same rule as data.baselines: a retail store, kind ask, new or condition unstated).
eBay sold and marketplace rows would drag the hourly median, so they are counted as skipped, never written.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from data.tiger import store

RETAIL = {"bestbuy", "microcenter", "bh", "newegg"}  # same set as data.baselines.RETAIL
ORIGINS = store.ORIGINS


def normalize_origin(x) -> str:
    """LIVE, MIRROR or SIM. Anything else is SIM: unknown origin never shows as LIVE."""
    return x if x in ORIGINS else "SIM"


def _cents(price):
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    c = int((Decimal(str(price)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return c if c > 0 else None


def _aware(ts) -> bool:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def convert(rows: list[dict]) -> tuple[list[dict], dict]:
    """Observation rows (Apify MIRROR or Bright Data shape) to price_obs rows, plus {reason: count} for rows left out."""
    out, skipped = [], Counter()
    for r in rows:
        if not r.get("sku"):
            skipped["no sku"] += 1
        elif r.get("kind") != "ask" or r.get("store") not in RETAIL:
            skipped["not a retail ask"] += 1
        elif r.get("condition") not in ("new", "unknown"):
            skipped["not new"] += 1
        elif (cents := _cents(r.get("price"))) is None:
            skipped["no price"] += 1
        elif not _aware(r.get("observed_at")):
            skipped["bad time"] += 1
        else:
            out.append({"ts": r["observed_at"], "sku": r["sku"], "store": r["store"], "provider": r.get("provider") or "unknown",
                        "price_cents": cents, "in_stock": bool(r.get("in_stock")), "origin": normalize_origin(r.get("origin")),
                        "url": r.get("url") or ""})
    return out, dict(skipped)


def to_price_obs(rows: list[dict]) -> list[dict]:
    return convert(rows)[0]


def snapshot_rows() -> list[dict]:
    """The dated Apify MIRROR snapshots on disk (no network)."""
    from data.baselines import observations
    return observations()


def _brightdata_rows() -> tuple[list[dict], str]:
    """One Bright Data fetch. Returns (rows, note); never raises."""
    try:
        from data.baselines import brightdata
        rows = brightdata.observations()
        return rows, f"brightdata: {len(rows)} live rows ({brightdata.status()['last_result']})"
    except Exception as e:  # NotConfigured, network, anything: the snapshot rows still load
        return [], f"brightdata: not fetched ({type(e).__name__})"


def _summary(rows: list[dict]) -> str:
    by = Counter((r["provider"], r["origin"]) for r in rows)
    return ", ".join(f"{p}/{o} {n}" for (p, o), n in sorted(by.items())) or "none"


_PLAN_LIMIT = re.compile(r"not (supported|available)|\bplan\b|\btier\b|upgrade|licen[sc]e|enterprise", re.I)


def optional_lines(schema: dict) -> list[str]:
    """One line per optional schema statement that did not apply, with the server's reason (redacted by the store):
    "optional, skipped (...)", never a bare failure. A columnstore policy refused for the plan says so."""
    reasons = schema.get("optional_reasons") or {}
    out = []
    for name in schema.get("optional_failed") or []:
        why = str(reasons.get(name) or "no reason given")
        if name == "add_columnstore_policy":
            what = "plan does not support columnstore" if _PLAN_LIMIT.search(why) else f"the server has no columnstore policy: {why}"
        else:
            what = why
        out.append(f"{name}: optional, skipped ({what})")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m data.tiger.load")
    ap.add_argument("--dry-run", action="store_true", help="print counts only; make no connection and no network call")
    ap.add_argument("--brightdata", action="store_true", help="also fetch live rows once through Bright Data")
    args = ap.parse_args(argv)

    if not args.dry_run and not store.status()["configured"]:
        print(f"Tiger Data not configured ({store.ENV} is not set); nothing written")
        return 2

    source = snapshot_rows()
    notes = []
    if args.brightdata:
        if args.dry_run:
            notes.append("brightdata: not fetched in a dry run")
        else:
            extra, note = _brightdata_rows()
            source += extra
            notes.append(note)
    rows, skipped = convert(source)
    head = f"{len(source)} source rows, {len(rows)} price_obs rows ({_summary(rows)}), skipped {skipped or 'none'}"
    for n in notes:
        print(n)
    if args.dry_run:
        print(f"dry run: {head}; no connection made")
        return 0
    try:
        schema = store.apply_schema()
        res = store.write_price_obs(rows)
    except store.TigerError as e:
        print(f"Tiger Data error: {e}")
        return 1
    print(f"{head}")
    print(f"inserted {res['inserted']} of {res['submitted']} price_obs rows (market_1h: {schema['market_1h']}; "
          f"optional statements skipped: {len(schema['optional_failed']) or 'none'})")
    for line in optional_lines(schema):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
