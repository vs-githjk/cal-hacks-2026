"""Market Pulse fair-price band: what a part really costs, from sourced history, published before each round.

    from agents.pulse.fair_band import fair_band          # or: from pulse.fair_band import fair_band (agents/ on sys.path)
    fair_band("rtx 5070 ti") -> {"low": 1250.0, "median": 1279.0, "high": 1300.0, "n": 12, "as_of": "2026-10-25",
                                 "source": "Tiger Data price_obs, last 7 days (...)", "source_url": "https://...", ...}
                                or None when there is no DATED price data (unknown part, only SIM prices). Advisory: it never ranks.
    FairBands().band("rtx 5070 ti")   # the same, but never None: SIM and "no data" answers too (what Pulse chat uses)

low, median and high are the 25th, 50th and 75th percentile of in-stock retail asks, in US dollars (a typical range, so one
trap price or one gouger does not move it). n is how many prices they come from. as_of is the date of the newest one.
Extra keys: sku, origin (MIRROR, SIM, MIRROR+SIM or "no data"), label (one readable sentence with the source), window_days,
windows ({"7": ..., "30": ...}), thin (fewer than 3 prices), tiger (not_configured, error, no_rows or rows).

Where the numbers come from, in order (the first source with prices wins; nothing is ever padded or invented):
  1. Tiger Data price_obs, the last 7 and 30 days. The headline is the 7-day band, or the 30-day band when the week is thin.
  2. Dated MIRROR snapshots (data/baselines/feed.json: retail asks in stock, new or condition unstated). Real listings, dated.
  3. The SIM seller listings in agents/sellers/sellers.json. A simulation: origin SIM, and the label says there is no history.
  4. Nothing: n 0, no numbers, origin "no data".
An origin is the origin of the rows read: a stored LIVE reads as MIRROR (dated), anything unknown reads as SIM. Every Pulse number
is SIM until Tiger Data has rows or a dated snapshot backs it.

    python3 -m agents.pulse.fair_band "rtx 5070 ti"        # print one band
    python3 -m agents.pulse.fair_band --tiger-check         # does Tiger Data hold price rows? (needs TIGER_DATA_SERVICE_URL)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.tiger import store  # noqa: E402

WINDOWS = (7, 30)
MIN_N = 3                         # fewer prices than this is a thin band: shown, labelled, never headline when 30 days is fuller
MAX_ROWS = 5000                   # one SKU's 30 days of asks, never an unbounded read
FEED = ROOT / "data" / "baselines" / "feed.json"
SELLERS_JSON = ROOT / "agents" / "sellers" / "sellers.json"
RETAIL = {"bestbuy", "microcenter", "bh", "newegg"}   # = data.baselines.RETAIL: the comparable retail stores
COMPARABLE_CONDITIONS = {"new", "unknown", "", None}  # = data.tiger.load: new, or condition unstated by the store
ORIGINS = ("MIRROR", "SIM")
PULSE_MAX_AGE_S = 6 * 3600        # a published pulse older than this is not read: it would price a new round with an old market
PULSE_FILE = "latest.json"
TIGER_SRC = "Tiger Data price_obs"
SNAPSHOT_SRC = "MIRROR snapshots (data/baselines feed)"
SIM_SRC = "SIM seller listings (agents/sellers/sellers.json)"

_PRICES_SQL = ("SELECT price_cents, ts, origin, url FROM price_obs WHERE sku = %s AND in_stock "
               "AND ts >= now() - make_interval(days => %s) ORDER BY ts DESC LIMIT " + str(MAX_ROWS))
_COUNTS_SQL = "SELECT origin, count(*), max(ts) FROM price_obs GROUP BY origin"


# ---------------------------------------------------------------- small helpers

def _sku(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("part_sku must be a non-empty string")
    return value.strip().lower()


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return _aware(ts)
    try:
        return _aware(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
    except ValueError:
        return None


def _iso_day(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _origin(raw: Any) -> str:
    """MIRROR or SIM. A stored LIVE is a dated read, so MIRROR; anything unknown is SIM and never reads as real."""
    return "MIRROR" if raw in ("MIRROR", "LIVE") else "SIM"


def _percentile(sorted_vals: list[float], q: float) -> float:
    """percentile_cont: linear interpolation between the two nearest ranks."""
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _usd(v: float) -> str:
    return f"${v:,.2f}"


def _dollars(v: float) -> float:
    return round(v + 1e-9, 2)


def _stats(obs: list[tuple[datetime, float, str]], window: Optional[int]) -> dict:
    """The band block for observations (time, dollars, origin) already cut to the window."""
    prices = sorted(o[1] for o in obs)
    block = {"window_days": window, "n": len(prices), "low": None, "median": None, "high": None, "days_of_data": 0, "as_of": None,
             "origins": []}
    if not prices:
        return block
    times = [o[0] for o in obs]
    span = (max(times) - min(times)).days + 1
    block.update(low=_dollars(_percentile(prices, 0.25)), median=_dollars(_percentile(prices, 0.5)),
                 high=_dollars(_percentile(prices, 0.75)), as_of=_iso_day(max(times)),
                 days_of_data=min(span, window) if window else span, origins=sorted({o[2] for o in obs}))
    return block


def _window_obs(obs: list[tuple[datetime, float, str]], now: datetime, days: int) -> list[tuple[datetime, float, str]]:
    start = now - timedelta(days=days)
    return [o for o in obs if start <= o[0] <= now]


def _short(block: dict) -> str:
    d, w = block["days_of_data"], block["window_days"]
    return f", only {d} day{'' if d == 1 else 's'} of data" if w and 0 < d < w else ""


# ---------------------------------------------------------------- the three sources

def tiger_prices(sku: str, days: int, *, connect: Optional[Callable] = None) -> dict:
    """{status, rows: [{price_cents, ts, origin, url}]} for one SKU's in-stock asks in the last `days`. Not configured and error
    answers carry no rows. The connection string is never in an answer."""
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(_PRICES_SQL, (sku, int(days)))
            return cur.fetchall()
    try:
        raw = store._run(connect, work)
    except store.NotConfigured:
        return {"status": "not_configured", "rows": []}
    except store.TigerError:
        return {"status": "error", "rows": []}
    rows = [{"price_cents": int(c), "ts": ts, "origin": o, "url": u if isinstance(u, str) else ""} for c, ts, o, u in raw
            if isinstance(c, (int, float)) and not isinstance(c, bool) and c > 0 and isinstance(ts, datetime)]
    return {"status": "ok", "rows": rows}


def tiger_row_counts(*, connect: Optional[Callable] = None) -> dict:
    """Does Tiger Data hold price rows? {status, rows, by_origin, newest}. Read-only; no row content is returned."""
    def work(conn):
        with conn.cursor() as cur:
            cur.execute(_COUNTS_SQL)
            return cur.fetchall()
    empty = {"rows": 0, "by_origin": {}, "newest": None}
    try:
        raw = store._run(connect, work)
    except store.NotConfigured:
        return {"status": "not_configured", **empty}
    except store.TigerError:
        return {"status": "error", **empty}
    by_origin = {str(o): int(n) for o, n, _ in raw}
    stamps = [ts for _, _, ts in raw if isinstance(ts, datetime)]
    return {"status": "ok", "rows": sum(by_origin.values()), "by_origin": by_origin, "newest": _iso_day(max(stamps)) if stamps else None}


def default_snapshots() -> list[dict]:
    """The dated MIRROR observations in data/baselines/feed.json ([] when it cannot be read)."""
    try:
        rows = json.loads(FEED.read_text(encoding="utf-8")).get("rows", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [r for r in rows if isinstance(r, dict)]


def default_catalog() -> list[dict]:
    """The SIM sellers' listings as [{seller, sku, price}], from sellers.json. A MIRROR seller's listing is not SIM and is left out."""
    try:
        sellers = json.loads(SELLERS_JSON.read_text(encoding="utf-8")).get("sellers", {})
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for sid, s in sellers.items():
        if not isinstance(s, dict) or s.get("origin") != "SIM":
            continue
        for sku, listing in (s.get("listings") or {}).items():
            price = listing.get("price") if isinstance(listing, dict) else None
            if isinstance(price, (int, float)) and not isinstance(price, bool) and math.isfinite(price) and price > 0:
                out.append({"seller": sid, "sku": str(sku).lower(), "price": float(price)})
    return out


def _url(value: Any) -> str:
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else ""


def _snapshot_obs(rows: list[dict], sku: str) -> list[tuple[datetime, float, str, str]]:
    """Comparable observations of one SKU: retail asks in stock, new or condition unstated. Sold prices, marketplace asks, the
    local store's own listings and out-of-stock rows never enter (the baselines rule: an outlier must not set a fair price)."""
    out = []
    for r in rows:
        price, at = r.get("price"), _parse(r.get("observed_at"))
        if (str(r.get("sku", "")).strip().lower() != sku or r.get("kind") != "ask" or r.get("store") not in RETAIL
                or not r.get("in_stock") or r.get("condition") not in COMPARABLE_CONDITIONS or at is None
                or isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0):
            continue
        out.append((at, float(price), _origin(r.get("origin")), _url(r.get("url"))))
    return out


# ---------------------------------------------------------------- the band

class FairBands:
    """Reads the three sources through three small providers, so a test (or a Pulse with its own source) swaps any of them."""

    def __init__(self, *, tiger_rows: Optional[Callable[[str, int], dict]] = None, snapshots: Optional[Callable[[], list]] = None,
                 catalog: Optional[Callable[[], list]] = None, now: Optional[Callable[[], datetime]] = None, tiger: bool = True):
        self.tiger_rows = tiger_rows or (tiger_prices if tiger else (lambda sku, days: {"status": "not_configured", "rows": []}))
        self.snapshots = snapshots or default_snapshots
        self.catalog = catalog or default_catalog
        self.now = now or (lambda: datetime.now(timezone.utc))

    def band(self, part_sku: str) -> dict:
        sku, now = _sku(part_sku), self.now()
        try:
            got = self.tiger_rows(sku, max(WINDOWS))
        except Exception:  # noqa: BLE001  (a provider that raises is an error answer, never a crash before a round)
            got = {"status": "error", "rows": []}
        status = got.get("status") if isinstance(got, dict) else "error"
        tiger_obs = [(_aware(r["ts"]), r["price_cents"] / 100, _origin(r["origin"]), _url(r.get("url"))) for r in (got.get("rows") or [])
                     if isinstance(got, dict) and isinstance(r.get("ts"), datetime) and isinstance(r.get("price_cents"), int)]
        tiger_obs = _window_obs(tiger_obs, now, max(WINDOWS))
        if tiger_obs:
            return self._windowed(sku, now, tiger_obs, TIGER_SRC, "rows")
        state = "no_rows" if status == "ok" else status if status in ("not_configured", "error") else "error"
        snaps = _window_obs(_snapshot_obs(self.snapshots(), sku), now, max(WINDOWS))
        if snaps:
            dated = _iso_day(max(o[0] for o in snaps))
            return self._windowed(sku, now, snaps, f"{SNAPSHOT_SRC}, dated {dated}", state, note=f"Tiger Data has no rows to use ({state.replace('_', ' ')})")
        sim = sorted(c["price"] for c in self.catalog() if c.get("sku") == sku)
        if sim:
            block = _stats([(now, p, "SIM", "") for p in sim], None)
            return self._result(sku, block, {}, SIM_SRC, "SIM", state,
                                f"{sku.upper()}: simulated price from {len(sim)} SIM listing{'' if len(sim) == 1 else 's'}, "
                                f"no price history yet [{SIM_SRC}; SIM]")
        block = _stats([], None)
        return self._result(sku, block, {}, "no source", "no data", state,
                            f"{sku.upper()}: no data, I have no price for this part yet [no source; no data]")

    def _windowed(self, sku: str, now: datetime, obs: list, source: str, tiger: str, note: str = "") -> dict:
        windows = {str(w): _stats(_window_obs(obs, now, w), w) for w in WINDOWS}
        head = next((windows[str(w)] for w in WINDOWS if windows[str(w)]["n"] >= MIN_N), None)
        head = head or max((windows[str(w)] for w in WINDOWS), key=lambda b: (b["n"], -b["window_days"]))
        origins = head["origins"]
        origin = "+".join(origins) if origins else "SIM"
        src = f"{source}, last {head['window_days']} days" + (f"; {note}" if note else "")
        label = (f"{sku.upper()}: typical {_usd(head['median'])}, range {_usd(head['low'])} to {_usd(head['high'])} "
                 f"({head['n']} price{'' if head['n'] == 1 else 's'}, last {head['window_days']} days{_short(head)}, "
                 f"as of {head['as_of']}) [{source}; {origin}]" + (" Thin: fewer than 3 prices." if head["n"] < MIN_N else "")
                 + (f" {note}." if note else ""))
        in_head = _window_obs(obs, now, head["window_days"])
        newest = max((o for o in in_head if o[3]), key=lambda o: o[0], default=None)   # the newest price that names its page
        return self._result(sku, head, windows, src, origin, tiger, label, newest[3] if newest else "")

    @staticmethod
    def _result(sku: str, head: dict, windows: dict, source: str, origin: str, tiger: str, label: str, source_url: str = "") -> dict:
        return {"sku": sku, "low": head["low"], "median": head["median"], "high": head["high"], "n": head["n"], "as_of": head["as_of"],
                "source": source, "source_url": source_url, "origin": origin, "label": label, "window_days": head["window_days"],
                "windows": {k: {kk: v[kk] for kk in ("window_days", "n", "low", "median", "high", "days_of_data", "as_of")}
                            for k, v in windows.items()},
                "thin": 0 < head["n"] < MIN_N, "tiger": tiger}


def fair_band(part_sku: str, **providers) -> Optional[dict]:
    """The fair-price band of one part from DATED price data (Tiger Data rows, else dated MIRROR snapshots), or None when there is
    none: an unknown part, a blank or non-text sku, or only simulated prices. Never raises, never ranks anything: it is advice.

        {"low": 1250.0, "median": 1279.0, "high": 1300.0, "n": 12, "as_of": "2026-10-25", "source": "...", "source_url": "https://...",
         "origin": "MIRROR", "label": "...", "window_days": 7, "windows": {...}, "thin": False, "tiger": "rows"}

    low and high are the 25th and 75th percentile of in-stock retail asks, in dollars; source_url is the page of the newest price
    in the window ("" when none names a page). The same inputs and the same clock give the same answer. `providers` are FairBands'
    (tiger_rows, snapshots, catalog, now, tiger). For the full answer including SIM and "no data", use FairBands(...).band(sku)."""
    try:
        band = FairBands(**providers).band(part_sku)
    except ValueError:
        return None
    return band if band["n"] and band["origin"] not in ("SIM", "no data") else None


# ---------------------------------------------------------------- the public pulse

def build_pulse(skus: list[str], *, bands: Optional[FairBands] = None) -> dict:
    """One public, sourced pulse: a band for every part (each with its source and origin), stamped with the time. No seller, buyer
    or cap appears in it: it is the market's price, nothing about who bid."""
    bands = bands or FairBands()
    seen: dict[str, dict] = {}
    for raw in skus:
        sku = _sku(raw)
        if sku not in seen:
            seen[sku] = bands.band(sku)
    published = bands.now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"kind": "market-pulse", "published_at": published, "bands": seen,
            "labels": sorted({b["origin"] for b in seen.values()}), "sourced": all(b.get("source") for b in seen.values())}


def pulse_path() -> Path:
    return Path(os.environ.get("PULSE_PUBLIC_PATH") or ROOT / ".run" / "pulse" / PULSE_FILE)


def publish_pulse(skus: list[str], *, path: Optional[Path] = None, bands: Optional[FairBands] = None) -> dict:
    """Build the pulse and write it as one JSON file (atomically, so a reader never sees half of it). Returns the pulse."""
    pulse = build_pulse(skus, bands=bands)
    target = Path(path) if path else pulse_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(pulse, f, indent=1, sort_keys=True)
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return pulse


def read_pulse(path: Optional[Path] = None, *, now: Optional[datetime] = None) -> Optional[dict]:
    """The published pulse, or None when it is missing, unreadable, not a pulse, or older than PULSE_MAX_AGE_S."""
    try:
        data = json.loads(Path(path or pulse_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("kind") != "market-pulse" or not isinstance(data.get("bands"), dict):
        return None
    at = _parse(data.get("published_at"))
    if at is None or (now or datetime.now(timezone.utc)) - at > timedelta(seconds=PULSE_MAX_AGE_S):
        return None
    return data


# ---------------------------------------------------------------- command line

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m agents.pulse.fair_band", description="The fair-price band for a part.")
    ap.add_argument("sku", nargs="?", help='a part, for example "rtx 5070 ti"')
    ap.add_argument("--json", action="store_true", help="print the band as JSON")
    ap.add_argument("--tiger-check", action="store_true", help="say whether Tiger Data holds price rows (needs TIGER_DATA_SERVICE_URL)")
    args = ap.parse_args(argv)
    if args.tiger_check:
        print(json.dumps(tiger_row_counts(), sort_keys=True))
        return 0
    if not args.sku:
        ap.error("give a part, or --tiger-check")
    try:
        band = fair_band(args.sku)
    except ValueError as e:
        print(f"fair band: {e}", file=sys.stderr)
        return 2
    print(json.dumps(band, indent=1, sort_keys=True) if args.json else band["label"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
