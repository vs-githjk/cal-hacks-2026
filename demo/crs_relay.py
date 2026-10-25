"""Relay the real CRS sandbox signals into the market, so /buyer and /market can show each seller's band.

    python3 -m demo.crs_relay [--dry-run] [--cache PATH] [--tokens-dir DIR]

agents/crs.py keeps the sanitized result of every sandbox check (the band, its time and its source, nothing about the
identity) in .cache/crs-signals.json. This reads that cache and, as the referee, calls the market's record_supplier_signal
reducer once per seller (docs/changes/1437-B-supplier-signal-missing.md, Lane B PR 320). The reducer is referee only, so no
seller or buyer can write a band.

Fail closed: only a signal that is complete, exactly the four contract fields, for a seller that has a market id, no older
than 24 hours and not from the future is relayed. Everything else is skipped with its reason. A seller with no relayed signal
has no row, and the market shows no row as "not verified", never as verified. A caution or not_verified band is relayed as
itself.

Feature detection: the market's schema lists its reducers. Until PR 320 is deployed the reducer is missing: the relay says so
and stops without a call. demo/bridge.py and demo/build.py call relay_best_effort right before each round opens; it never raises
and never stops a round.

Exit code: 0 every usable signal was sent (or --dry-run listed some), 1 a call was refused, 2 nothing was sent (no usable
signal, or the market has no record_supplier_signal yet).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REDUCER = "record_supplier_signal"
# The one place that maps a CRS supplier id (agents/crs.py, the cache keys) to the market seller id its bids carry. The same
# mapping the seller agents use (agents/sellers/seller_agent.py _MARKET_SELLER_SUBJECT); a test keeps the two equal.
MARKET_SELLER = {"seller_1": "seller-a", "seller_2": "seller-b", "seller_3": "seller-c"}
FIELDS = {"supplier_id", "stability", "checked_at", "source"}
BANDS = {"verified_stable", "caution", "not_verified"}
SOURCES = {"sandbox", "recorded"}          # the sources a cached CRS result can truthfully carry
MAX_AGE = timedelta(hours=24)              # agents/crs.py CACHE_MAX_AGE
MAX_SKEW = timedelta(minutes=5)            # the market refuses a checked_at further ahead than this
DEFAULT_CACHE = ROOT / ".cache" / "crs-signals.json"
_DETECT = object()                         # "look the reducers up from the market's schema"


def _time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None   # a time without a zone is not trusted


def plan(cache: Any, *, now: datetime, verify: Optional[Callable[[str, Any], bool]] = None) -> tuple[list[dict], list[tuple[str, str]]]:
    """(reducer arguments to send, [(cache key, why it was skipped)]). Pure: no market, no clock but `now`. `verify`
    (agents/crs.py entry_verified, #449 RT-25) is asked about every entry: one without a valid CRS_CACHE_SECRET tag is
    skipped, so a forged or hand-edited cache file never puts a band on the market. None means no check (the pure tests)."""
    calls: list[dict] = []
    skipped: list[tuple[str, str]] = []
    if not isinstance(cache, dict):
        return calls, skipped
    for key in sorted(k for k in cache if isinstance(k, str)):
        market_id = MARKET_SELLER.get(key)
        if market_id is None:
            skipped.append((key, "no market seller id for it"))
            continue
        entry = cache[key]
        if verify is not None and not verify(key, entry):
            skipped.append((key, "cache entry has no valid CRS_CACHE_SECRET tag (run agents/crs.py --live with the secret set)"))
            continue
        signal = entry.get("signal") if isinstance(entry, dict) else None
        if not isinstance(signal, dict):
            skipped.append((key, "no signal in the cache entry"))
            continue
        if set(signal) != FIELDS:
            skipped.append((key, "signal must be exactly the four fields"))
        elif signal["supplier_id"] != key:
            skipped.append((key, "signal supplier id does not match its key"))
        elif signal["stability"] not in BANDS:
            skipped.append((key, "unknown stability band"))
        elif signal["source"] not in SOURCES:
            skipped.append((key, "source must be sandbox or recorded"))
        else:
            at = _time(signal["checked_at"])
            if at is None:
                skipped.append((key, "unreadable checked_at time"))
            elif now - at > MAX_AGE:
                skipped.append((key, "stale (older than 24 hours): run agents/crs.py --live"))
            elif at - now > MAX_SKEW:
                skipped.append((key, "checked_at is in the future"))
            else:
                calls.append({"supplier_id": market_id, "stability": signal["stability"],
                              "checked_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": signal["source"]})
    return calls, skipped


def read_cache(path: Path) -> dict:
    """The cache as a dict; a missing, unreadable or odd file is empty (nothing to relay), never an error."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_cache_path(explicit: Optional[str] = None) -> Path:
    """--cache, else CRS_SIGNAL_CACHE_PATH (the same name agents/crs.py reads), else .cache/crs-signals.json."""
    chosen = explicit or os.environ.get("CRS_SIGNAL_CACHE_PATH")
    return Path(chosen) if chosen else DEFAULT_CACHE


def detect_reducers(http: str, db: str, opener: Callable = urllib.request.urlopen) -> Optional[set]:
    """The reducer names the market's module exports, from its schema; None when the schema cannot be read."""
    try:
        with opener(f"{http.rstrip('/')}/v1/database/{db}/schema?version=9", timeout=6) as resp:
            schema = json.loads(resp.read())
        return {r["name"] for r in schema["reducers"]}
    except Exception:  # noqa: BLE001  (down, refused, odd body: unknown, not "missing")
        return None


def _env_market() -> tuple[str, str]:
    from demo import market_target
    return (os.environ.get("SPACETIMEDB_HTTP") or market_target.DEFAULTS["SPACETIMEDB_HTTP"],
            os.environ.get("SPACETIMEDB_DB") or market_target.DEFAULTS["SPACETIMEDB_DB"])


def _say(call: dict, extra: str = "") -> str:
    return f"CRS relay: {call['supplier_id']} {call['stability']} (checked {call['checked_at']}, source {call['source']}){extra}"


NO_REDUCER = (f"CRS relay skipped: this market has no {REDUCER} yet (Lane B PR 320 adds it); /buyer and /market show no CRS band "
              "until it is deployed")


def tag_verifier() -> Callable[[str, Any], bool]:
    """agents/crs.py entry_verified, from the one shared loader (demo/bridge.py crs_module)."""
    from demo import bridge
    return bridge.crs_module().entry_verified


def relay(client: Any, cache: Any, *, reducers: Optional[set], now: datetime, note: Callable[[str], None] = print,
          dry_run: bool = False, verify: Optional[Callable[[str, Any], bool]] = None) -> dict:
    """Send every usable signal. `reducers` is the market's reducer names, or None when unknown (then a 404 from the first call
    says the reducer is missing). Returns {status, sent, failed, skipped}; status is one of dry_run, nothing, no_reducer, sent,
    partial, failed. One refused seller never stops the others."""
    calls, skipped = plan(cache, now=now, verify=verify)
    report: dict = {"status": "nothing", "sent": [], "failed": [], "skipped": skipped}
    for key, why in skipped:
        note(f"CRS relay: {key} not relayed, {why}")
    if not calls:
        note("CRS relay: no usable CRS signal to send (run `python3 agents/crs.py --live` for a fresh check)")
        return report
    if dry_run:
        for call in calls:
            note(f"would call {REDUCER} as the referee: " + json.dumps(call, sort_keys=True))
        report["status"] = "dry_run"
        return report
    if reducers is not None and REDUCER not in reducers:
        note(NO_REDUCER)
        report["status"] = "no_reducer"
        return report
    for call in calls:
        try:
            client.call(REDUCER, **call)
        except Exception as e:  # noqa: BLE001  (a refusal or a dead market: this seller only)
            text = str(e)[:200] or type(e).__name__
            if reducers is None and "(404)" in text:
                note(NO_REDUCER)
                report["status"] = "no_reducer"
                return report
            report["failed"].append((call["supplier_id"], text))
            note(_say(call, f" REFUSED: {text}"))
            continue
        report["sent"].append(call["supplier_id"])
        note(_say(call))
    report["status"] = ("sent" if not report["failed"] else "partial" if report["sent"] else "failed")
    return report


def relay_best_effort(client: Any, *, note: Callable[[str], None] = print, cache_path: Optional[Path] = None,
                      reducers: Any = _DETECT, now: Optional[datetime] = None, http: Optional[str] = None,
                      db: Optional[str] = None) -> dict:
    """What a round calls right before it opens: the same relay, but it can never raise. A problem is one note and the
    round opens anyway; the market keeps whatever bands it already has."""
    try:
        if reducers is _DETECT:
            h, d = (http, db) if http and db else _env_market()
            reducers = detect_reducers(h, d)
        return relay(client, read_cache(cache_path or resolve_cache_path()), reducers=reducers,
                     now=now or datetime.now(timezone.utc), note=note, verify=tag_verifier())
    except Exception as e:  # noqa: BLE001
        try:
            note(f"CRS relay skipped ({type(e).__name__}); the round opens anyway")
        except Exception:  # noqa: BLE001
            pass
        return {"status": "failed", "sent": [], "failed": [], "skipped": []}


def referee_client(tokens_dir: Optional[str]) -> Any:
    """The referee identity of the market this process targets (the same resolution as demo/bridge.py live runs)."""
    from demo import bridge, market_target
    from demo.run_demo import DEFAULT_ENV_FILE
    try:
        target = market_target.resolve(DEFAULT_ENV_FILE)
    except market_target.TargetError as e:
        raise SystemExit(f"market target refused: {e}") from None
    market_target.export(target)
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    from stdb import Market
    tokens = bridge.find_tokens_dir(tokens_dir, target)
    return Market(token_file=str(tokens / bridge.REFEREE_TOKEN))


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Relay the CRS sandbox signals into the market's record_supplier_signal (referee)")
    ap.add_argument("--dry-run", action="store_true", help="print the reducer calls only; no market client is opened")
    ap.add_argument("--cache", default=None, help="the CRS signal cache (default CRS_SIGNAL_CACHE_PATH, else .cache/crs-signals.json)")
    ap.add_argument("--tokens-dir", default=None, help="folder with referee.json (default: auto-detect, as demo/bridge.py)")
    args = ap.parse_args(argv)
    cache = read_cache(resolve_cache_path(args.cache))
    now = datetime.now(timezone.utc)
    if args.dry_run:
        report = relay(None, cache, reducers=None, now=now, dry_run=True, verify=tag_verifier())
        return 0 if report["status"] == "dry_run" else 2
    client = referee_client(args.tokens_dir)
    http, db = _env_market()
    report = relay(client, cache, reducers=detect_reducers(http, db), now=now, verify=tag_verifier())
    return {"sent": 0, "partial": 1, "failed": 1}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
