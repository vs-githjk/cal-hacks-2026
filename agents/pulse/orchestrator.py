"""Market Pulse orchestrator (#260): the week and the month, for sellers and for buyers.

Given a finished round (market `round_result` rows, from a JSON file or read from the market), it builds
  - for every losing seller: the market_pulse note (what to change, inside the seller's own floor and policy) plus its own
    7-day and 30-day record from Tiger Data (rounds entered, won, win rate, median gap band);
  - for every SKU in the round: the 7-day and 30-day price trend from Tiger Data (lowest, median, now, direction) and how
    many sellers listing that SKU are CRS verified (from the CRS signals cache).
It also answers two kinds of ASI:One chat question ("how is the RTX 5070 Ti trending?", "why does seller_3 keep losing?").

Closed schema, like market_pulse: every sentence is a fixed phrase filled with numbers, ids and counts that this code read
from a source. No model text and no user text reaches a seller or a buyer. A seller note carries only that seller's own
band, reason and record: never a rival's price, the winning price, the buyer's cap or another seller's record.
Every line names its source in brackets (Tiger Data table, CRS signals cache, round id) and its origin (LIVE, MIRROR, SIM).

Where Tiger Data holds fewer days than a window, the line says "only N days of data" and shows only what Tiger returned.
With TIGER_DATA_SERVICE_URL unset the windows come from a deterministic fixture, every line of it labelled SIM
(`--no-sim` shows "not configured" and no numbers instead).

    python3 -m agents.pulse.orchestrator --round-file agents/pulse/fixtures/round1_sample.json

Nothing here registers an agent or starts one unless `--serve` is given (see docs/changes/1730-D-market-pulse-orchestrator.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.crs import CACHE_MAX_AGE  # noqa: E402
from agents.pulse import coaching  # noqa: E402
from agents.pulse import fair_band as FB  # noqa: E402
from agents.pulse import market_pulse as MP  # noqa: E402
from data.tiger import store, trends  # noqa: E402

WINDOWS = trends.WINDOWS
BAND_TEXT = MP.BAND_TEXT
SELLERS_JSON = ROOT / "agents" / "sellers" / "sellers.json"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
LOSS_REASONS = ("price", "fit", "condition", "delivery", "record", "advocate_veto")
GAP_BANDS = ("within5", "within10", "within20", "over20")
# a disqualified bid's rule id prefix (round_result.reasons) -> the loss reason a seller is told
REASON_PREFIX = {"price": "price", "fit": "fit", "condition": "condition", "delivery": "delivery", "record": "record",
                 "advocate": "advocate_veto"}
DIRECTION_TEXT = {"up": "trending up", "down": "trending down", "flat": "holding flat",
                  "not_enough_days": "not enough days to call a direction", "no_data": "no prices recorded in this window"}
TIGER_RECORD_SRC = "Tiger Data bid_ticks and loss_reports"
TIGER_PRICE_SRC = "Tiger Data price_obs"
SIM_SRC = "SIM fixture"
NOTE_KEYS = {"seller_id", "round_id", "sku", "gap_band", "reason", "source_url", "action", "price_step", "what_to_change",
             "what_to_change_origin", "market", "record", "lines", "gap_pct", "fair_band"}
BAND_KEYS = ("low", "median", "high", "n", "as_of", "source", "origin", "window_days")
PRICE_WORDS = {"price", "prices", "pricing", "cost", "costs", "going", "worth", "fair", "much", "pay", "paying", "rate", "afford",
               "cheap", "expensive", "deal", "market"}
TREND_WORDS = {"trend", "trends", "trending", "week", "month", "history", "direction", "lately"}
SKU_SHAPE = re.compile(r"^[a-z0-9][a-z0-9 .+/-]{0,39}$")
MAX_BAND_SKUS = 20
HELP = ("I am Market Pulse. Ask me the going price of a part, for example \"what's the going price for an RTX 5070 Ti?\", how a "
        "part is trending, for example \"how is the RTX 5070 Ti trending?\", or why a seller keeps losing, for example \"why does "
        "seller_3 keep losing?\". I answer from Tiger Data, dated MIRROR snapshots, the CRS signals cache and finished rounds, and "
        "I name the source of every number. I cannot place bids or approve purchases.")


class PulseError(ValueError):
    """A round file or market row this module will not read; the message is safe to print."""


# ---------------------------------------------------------------- round rows

def _snake(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).lower()


def _line(raw: Any) -> dict:
    """One bid line: an object (sku_spec or skuSpec) or, as SpacetimeDB sql returns it, the positional array
    [sku_spec, offered_spec, offered_condition, unit_price, quantity], of which only index 0 is read."""
    if isinstance(raw, (list, tuple)):
        raw = {"sku_spec": raw[0]} if raw else {}
    if not isinstance(raw, Mapping):
        raise PulseError("a bid line is not an object or a row")
    line = {_snake(k): v for k, v in raw.items()}
    sku = line.get("sku_spec")
    if not isinstance(sku, str) or not sku.strip():
        raise PulseError("a bid line has no sku_spec")
    return {"sku_spec": sku.strip().lower(), "listing_url": line.get("listing_url") if isinstance(line.get("listing_url"), str) else ""}


def _number(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def normalize_rows(rows: Any) -> list[dict]:
    """round_result rows as {round_id, seller_id, rank, landed, adjusted, reasons, lines, origin}. camelCase or snake_case in.
    PulseError for anything that is not a list of readable rows: a half-read round never produces notes."""
    if not isinstance(rows, list) or not rows:
        raise PulseError("round_result must be a non-empty list of rows")
    out = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise PulseError("a round_result row is not an object")
        r = {_snake(k): v for k, v in raw.items()}
        rid, sid = r.get("round_id"), r.get("seller_id")
        if not isinstance(rid, str) or not ID_RE.match(rid) or not isinstance(sid, str) or not ID_RE.match(sid):
            raise PulseError("a round_result row has a missing or unsafe round_id or seller_id")
        rank, landed = r.get("rank"), _number(r.get("landed"))
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0 or landed is None or landed < 0:
            raise PulseError("a round_result row has a bad rank or landed price")
        adjusted = _number(r.get("adjusted_total"))
        reasons = r.get("reasons")
        lines = r.get("lines")
        if not isinstance(lines, list) or not lines:
            raise PulseError("a round_result row has no lines")
        out.append({"round_id": rid, "seller_id": sid, "rank": rank, "landed": landed,
                    "adjusted": adjusted if adjusted and adjusted > 0 else landed,
                    "reasons": [str(x) for x in reasons] if isinstance(reasons, list) else [],
                    "lines": [_line(x) for x in lines], "origin": r.get("origin") if r.get("origin") in ("LIVE", "MIRROR", "SIM") else "SIM"})
    if len({r["round_id"] for r in out}) != 1:
        raise PulseError("round_result rows belong to more than one round")
    return out


def skus_of(rows: list[dict]) -> list[str]:
    seen: dict[str, None] = {}
    for r in rows:
        for line in r["lines"]:
            seen.setdefault(line["sku_spec"])
    return list(seen)


def _gap_band(pct: float) -> str:
    return trends.gap_band(max(0.0, pct))


def derive_reports(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """LossReport-shaped reports from round_result alone, for a round whose referee reports are not at hand: rank 1 won;
    every other row lost by its banded gap to the winner's adjusted total. A disqualified row gets the reason of its first
    rule id prefix. A row whose reason cannot be read is returned in the second list (no note, never a guess)."""
    winners = [r for r in rows if r["rank"] == 1]
    if len(winners) != 1:
        raise PulseError("the round needs exactly one rank 1 row to derive loss reports")
    win = winners[0]["adjusted"]
    reports, skipped = [], []
    for r in rows:
        if r["rank"] == 1:
            continue
        if r["rank"] == 0:
            prefix = (r["reasons"][0].split(":", 1)[0].strip().lower() if r["reasons"] else "")
            reason = REASON_PREFIX.get(prefix)
        else:
            reason = "price"
        if reason is None or win <= 0:
            skipped.append({"seller_id": r["seller_id"], "why": "no readable loss reason"})
            continue
        gap = (r["adjusted"] - win) / win * 100
        url = r["lines"][0]["listing_url"]
        reports.append({"id": f"lr-{r['round_id']}-{r['seller_id']}", "round_id": r["round_id"], "seller_id": r["seller_id"],
                        "won": False, "gap_band": _gap_band(gap), "reason": reason,
                        "source_url": url if url.startswith(("http://", "https://")) else ""})
    return reports, skipped


def read_reports(raw: Any, round_id: str) -> list[dict]:
    """The referee's loss reports for this round, only the fields a note uses; anything unreadable raises."""
    if not isinstance(raw, list):
        raise PulseError("loss_reports must be a list")
    out = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise PulseError("a loss report is not an object")
        r = {_snake(k): v for k, v in item.items()}
        if (r.get("round_id") != round_id or not isinstance(r.get("seller_id"), str) or not ID_RE.match(r["seller_id"])
                or r.get("won") is not False or r.get("gap_band") not in GAP_BANDS or r.get("reason") not in LOSS_REASONS):
            raise PulseError("a loss report is for another round or has an unknown band or reason")
        url = r.get("source_url") if isinstance(r.get("source_url"), str) else ""
        out.append({"id": str(r.get("id") or f"lr-{round_id}-{r['seller_id']}"), "round_id": round_id, "seller_id": r["seller_id"],
                    "won": False, "gap_band": r["gap_band"], "reason": r["reason"],
                    "source_url": url if url.startswith(("http://", "https://")) else ""})
    return out


def load_round(path: str | os.PathLike) -> dict:
    """A round file: {"round_id"?, "round_result": [...], "loss_reports"?: [...]}. PulseError for anything else."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PulseError(f"cannot read a round from {Path(path).name}") from None
    if not isinstance(data, Mapping):
        raise PulseError("a round file is a JSON object")
    return round_from_rows(data.get("round_result"), data.get("loss_reports"))


def round_from_rows(rows: Any, reports: Any = None) -> dict:
    rows = normalize_rows(rows)
    round_id = rows[0]["round_id"]
    skipped: list[dict] = []
    if reports is None:
        reports, skipped = derive_reports(rows)
        derived = True
    else:
        reports, derived = read_reports(reports, round_id), False
    return {"round_id": round_id, "rows": rows, "reports": reports, "skipped": skipped, "reports_from": "derived from round_result" if derived else "referee loss reports"}


_RESULT_SQL = ("SELECT round_id, bid_id, seller_id, rank, landed, reasons, lines, origin, adjusted_total "
               "FROM round_result WHERE round_id = '{}'")        # no ORDER BY: SpacetimeDB sql answers 400 Unsupported
_RESULT_COLS = ("round_id", "bid_id", "seller_id", "rank", "landed", "reasons", "lines", "origin", "adjusted_total")


def round_from_market(round_id: str, client: Any) -> dict:
    """Read one round's round_result rows through an existing market client (`client.sql(query)`, e.g. market/scripts/stdb.py
    Market with a token file you already have). round_result is public, so any identity can read it. Not exercised against
    the live market in this change: the tests use a fake client."""
    if not isinstance(round_id, str) or not ID_RE.match(round_id):
        raise PulseError("round id must be one safe token")
    try:
        raw = client.sql(_RESULT_SQL.format(round_id))
    except Exception:  # noqa: BLE001  (the market's error text is not passed on)
        raise PulseError("the market could not be read") from None
    rows = []
    for item in raw if isinstance(raw, list) else []:
        row = dict(zip(_RESULT_COLS, item)) if isinstance(item, (list, tuple)) else dict(item)
        for key in ("reasons", "lines"):
            if isinstance(row.get(key), str):
                try:
                    row[key] = json.loads(row[key])
                except ValueError:
                    raise PulseError("a round_result row could not be decoded") from None
        rows.append(row)
    if not rows:
        raise PulseError("no round_result rows for that round: is the round closed?")
    rows.sort(key=lambda r: (r.get("rank") if isinstance(r.get("rank"), int) and not isinstance(r.get("rank"), bool) else 1 << 30,
                             str(r.get("seller_id"))))
    return round_from_rows(rows)


# ---------------------------------------------------------------- sources (Tiger Data or a labelled SIM fixture)

def _safe(call: Callable[[], dict], empty: dict) -> dict:
    try:
        return call()
    except (ValueError, TypeError):
        return {**empty, "status": "error"}


class TigerSource:
    """Tiger Data through data.tiger.trends. Not configured and error answers carry no numbers."""
    name = "Tiger Data"
    sim = False

    def price(self, sku: str, days: int) -> dict:
        return _safe(lambda: trends.price_trend(sku, days), {"sku": sku, "window_days": days, "days_of_data": 0, "n": 0, "rows": [],
                                                              "min_cents": None, "median_cents": None, "now_cents": None, "direction": "no_data", "origins": []})

    def record(self, seller_id: str, days: int) -> dict:
        return _safe(lambda: trends.seller_record(seller_id, days), {"seller_id": seller_id, "window_days": days, "days_of_data": 0,
                                                                     "rounds_entered": 0, "rounds_won": 0, "rounds_lost": 0, "win_rate": None,
                                                                     "median_gap_band": None, "gap_samples": 0, "origins": []})

    def demand(self) -> dict:
        return trends.demand_by_sku()

    def coach(self, seller_id: str) -> dict:
        return trends.loss_coach(seller_id)


def _h(*parts: Any) -> int:
    return int.from_bytes(hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()[:4], "big")


class SimSource(TigerSource):
    """A deterministic fixture for the week and the month, used only when Tiger Data is not configured. Ten days of history,
    so the 7-day window is full and the 30-day window says "only 10 days of data". Prices start from the SIM listings in
    sellers.json. Every block it returns says origin SIM and source "SIM fixture"; demand and coach stay honest (Tiger)."""
    name = "SIM fixture"
    sim = True
    HELD = 10

    def __init__(self, base_prices: Optional[Mapping[str, float]] = None):
        self.base = dict(base_prices if base_prices is not None else catalog_prices())

    def price(self, sku: str, days: int) -> dict:
        base = self.base.get(sku.lower())
        held = min(days, self.HELD)
        if base is None:
            return {"status": "ok", "sku": sku, "window_days": days, "days_of_data": 0, "n": 0, "rows": [], "min_cents": None,
                    "median_cents": None, "now_cents": None, "direction": "no_data", "origins": ["SIM"], "sim": True}
        drift = (_h(sku, "drift") % 9 - 4) / 100            # -4 percent to +4 percent over the ten days
        rows = []
        for i in range(held):
            day = self.HELD - held + i                      # position in the ten days, oldest first; the window keeps the newest
            mid = base * (1 + drift * day / (self.HELD - 1) + ((_h(sku, day) % 5) - 2) / 400)
            rows.append({"bucket": f"day {day - self.HELD + 1}", "min_cents": int(round(mid * 98)), "median_cents": int(round(mid * 100)), "n": 3})
        meds = sorted(r["median_cents"] for r in rows)
        first, last = rows[0]["median_cents"], rows[-1]["median_cents"]
        move = (last - first) / first if len(rows) > 1 else 0
        direction = "not_enough_days" if len(rows) < 2 else "up" if move > trends.FLAT_BAND else "down" if move < -trends.FLAT_BAND else "flat"
        return {"status": "ok", "sku": sku, "window_days": days, "days_of_data": held, "n": 3 * held,
                "min_cents": min(r["min_cents"] for r in rows), "median_cents": meds[len(meds) // 2], "now_cents": last,
                "direction": direction, "origins": ["SIM"], "rows": rows, "sim": True}

    def record(self, seller_id: str, days: int) -> dict:
        held = min(days, self.HELD)
        entered = sum(1 + _h(seller_id, d) % 2 for d in range(held))
        won = entered * (_h(seller_id, "win") % 31) // 100
        band = GAP_BANDS[_h(seller_id, "band") % 3] if entered > won else None
        return {"status": "ok", "seller_id": seller_id, "window_days": days, "days_of_data": held, "rounds_entered": entered,
                "rounds_won": won, "rounds_lost": entered - won, "win_rate": round(won / entered, 3) if entered else None,
                "median_gap_band": band, "gap_samples": entered - won, "origins": ["SIM"], "sim": True}


def tiger_configured() -> bool:
    return bool(store._url())


def default_source(*, sim_fallback: bool = True) -> TigerSource:
    """Tiger Data when TIGER_DATA_SERVICE_URL is set; else the SIM fixture (or Tiger's "not configured" with no numbers)."""
    if tiger_configured() or not sim_fallback:
        return TigerSource()
    return SimSource()


# ---------------------------------------------------------------- the catalog and CRS

def load_catalog(path: str | os.PathLike = SELLERS_JSON) -> dict:
    """{seller_id: {"name", "skus": [lowercase sku_spec, ...]}} from sellers.json (SIM sellers and their listings)."""
    try:
        sellers = json.loads(Path(path).read_text(encoding="utf-8")).get("sellers", {})
    except (OSError, ValueError, AttributeError):
        return {}
    out = {}
    for sid, cfg in sellers.items() if isinstance(sellers, dict) else []:
        if isinstance(cfg, Mapping) and isinstance(cfg.get("listings"), Mapping) and ID_RE.match(str(sid)):
            out[sid] = {"name": str(cfg.get("name") or sid), "skus": [str(k).lower() for k in cfg["listings"]]}
    return out


def catalog_prices(path: str | os.PathLike = SELLERS_JSON) -> dict[str, float]:
    """Mean SIM listing price per SKU in sellers.json: the starting point of the SIM fixture, never shown as a real price."""
    try:
        sellers = json.loads(Path(path).read_text(encoding="utf-8")).get("sellers", {})
    except (OSError, ValueError, AttributeError):
        return {}
    acc: dict[str, list[float]] = {}
    for cfg in sellers.values() if isinstance(sellers, dict) else []:
        for sku, listing in (cfg.get("listings") or {}).items():
            price = _number(listing.get("price")) if isinstance(listing, Mapping) else None
            if price and price > 0:
                acc.setdefault(str(sku).lower(), []).append(price)
    return {k: sum(v) / len(v) for k, v in acc.items()}


def crs_cache_path() -> Path:
    return Path(os.environ.get("CRS_SIGNAL_CACHE_PATH") or ROOT / ".cache" / "crs-signals.json")


def _utc(value: str) -> datetime:
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("naive timestamp")
    return t.astimezone(timezone.utc)


def read_crs(path: Optional[Path] = None, now: Optional[datetime] = None) -> Optional[dict]:
    """{seller_id: signal} for every fresh, well-formed signal in the CRS cache (same checks as agents/crs.py: exactly the four
    SupplierSignal fields, a known stability and source, not older than CACHE_MAX_AGE, not from the future). None when the
    cache cannot be read. An entry that fails a check is left out: it counts as "no current check", never as verified."""
    path = path or crs_cache_path()
    now = now or datetime.now(timezone.utc)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    out = {}
    for sid, entry in data.items():
        signal = entry.get("signal") if isinstance(entry, dict) else None
        if not isinstance(signal, dict) or set(signal) != {"supplier_id", "stability", "checked_at", "source"}:
            continue
        if (signal["supplier_id"] != sid or signal["stability"] not in ("verified_stable", "caution", "not_verified")
                or signal["source"] not in ("sandbox", "recorded") or not isinstance(signal["checked_at"], str)):
            continue
        try:
            age = now - _utc(signal["checked_at"])
        except (ValueError, OverflowError):
            continue
        if age < timedelta(0) or age > CACHE_MAX_AGE:
            continue
        out[sid] = signal
    return out


def crs_counts(sellers: list[str], signals: Optional[dict]) -> dict:
    """How many of `sellers` are CRS verified. Sellers with no fresh signal (SIM sellers have no business profile to check)
    are counted as no current check, never as verified."""
    counts = {"sellers": len(sellers), "verified": 0, "caution": 0, "not_verified": 0, "no_current_check": 0, "checked_at": None}
    stamps = []
    for sid in sellers:
        sig = (signals or {}).get(sid)
        if sig is None:
            counts["no_current_check"] += 1
            continue
        counts[{"verified_stable": "verified", "caution": "caution", "not_verified": "not_verified"}[sig["stability"]]] += 1
        stamps.append(sig["checked_at"])
    counts["checked_at"] = max(stamps) if stamps else None
    counts["available"] = signals is not None
    counts["source"] = "CRS signals cache (sandbox check)"
    return counts


# ---------------------------------------------------------------- lines (fixed phrases)

def _usd(cents: Optional[int]) -> str:
    return f"${cents / 100:,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _tag(source: str, origin: str) -> str:
    return f" [{source}; {origin}]"


def _short(block: dict) -> str:
    d, w = block["days_of_data"], block["window_days"]
    return f" (only {_plural(d, 'day')} of data)" if 0 < d < w else ""


def record_origin(rec: dict, sim: bool) -> str:
    """The origin a record line carries: SIM for the fixture; for a Tiger read, the origins of the rows it was built from
    ("no data" when it was built from none: a real, empty read is not SIM); SIM for rows that state none."""
    if sim:
        return "SIM"
    if not rec["rounds_entered"]:
        return "no data"
    return "+".join(rec.get("origins") or []) or "SIM"


def record_block(rec: dict) -> dict:
    sim = bool(rec.get("sim"))
    state = rec.get("status") or "error"
    block = {"window_days": rec["window_days"], "state": state, "days_of_data": rec["days_of_data"], "rounds_entered": rec["rounds_entered"],
             "rounds_won": rec["rounds_won"], "win_rate": rec["win_rate"], "median_gap_band": rec["median_gap_band"],
             "origin": record_origin(rec, sim), "source": SIM_SRC if sim else TIGER_RECORD_SRC}
    block["line"] = record_line(block)
    return block


def record_line(b: dict) -> str:
    w, tag = b["window_days"], _tag(b["source"], b["origin"])
    if b["state"] != "ok":
        why = "not configured" if b["state"] == "not_configured" else "not available right now"
        return f"Last {w} days: no record to show, Tiger Data is {why}.{_tag('Tiger Data', b['state'].replace('_', ' '))}"
    if not b["rounds_entered"]:
        return f"Last {w} days{_short(b)}: no rounds recorded for you yet.{tag}"
    pct = round(b["win_rate"] * 100)
    gap = (f", a typical loss was by {BAND_TEXT[b['median_gap_band']]}" if b["median_gap_band"] else ", no loss gap on record")
    return (f"Last {w} days{_short(b)}: you entered {_plural(b['rounds_entered'], 'round')}, won {b['rounds_won']} ({pct}%){gap}.{tag}")


def price_block(p: dict) -> dict:
    sim = bool(p.get("sim"))
    origin = "SIM" if sim else "no data" if not p["n"] else "+".join(p.get("origins") or []) or "SIM"
    block = {"window_days": p["window_days"], "state": p.get("status") or "error", "days_of_data": p["days_of_data"], "n": p["n"],
             "min_cents": p["min_cents"], "median_cents": p["median_cents"], "now_cents": p["now_cents"], "direction": p["direction"],
             "origin": origin, "source": SIM_SRC if sim else TIGER_PRICE_SRC}
    block["line"] = price_line(block)
    return block


def price_line(b: dict) -> str:
    w = b["window_days"]
    if b["state"] != "ok":
        why = "not configured" if b["state"] == "not_configured" else "not available right now"
        return f"Last {w} days: no price history to show, Tiger Data is {why}.{_tag('Tiger Data', b['state'].replace('_', ' '))}"
    if not b["n"]:
        return f"Last {w} days: no prices recorded for this part yet.{_tag(b['source'], b['origin'])}"
    return (f"Last {w} days{_short(b)}: lowest {_usd(b['min_cents'])}, median {_usd(b['median_cents'])}, now {_usd(b['now_cents'])}, "
            f"{DIRECTION_TEXT[b['direction']]}.{_tag(b['source'], b['origin'])}")


def crs_line(c: dict) -> str:
    if not c["sellers"]:
        return "CRS: no seller lists this part yet."
    if not c["available"]:
        return (f"CRS: signals are not available, so none of the {_plural(c['sellers'], 'seller')} listing this part is counted as "
                f"verified. [CRS signals cache; not read]")
    stamp = f", last check {c['checked_at']}" if c["checked_at"] else ""
    return (f"CRS: {c['verified']} of {_plural(c['sellers'], 'seller')} listing this part are verified ({c['not_verified']} not verified, "
            f"{c['caution']} caution, {c['no_current_check']} with no current check).{_tag(c['source'] + stamp, 'sandbox')}")


# ---------------------------------------------------------------- the orchestrator

class Pulse:
    """Holds a source, the seller catalog and the CRS cache path; turns a finished round into notes and answers chat."""

    def __init__(self, source: Optional[TigerSource] = None, *, catalog: Optional[dict] = None, crs_path: Optional[Path] = None,
                 now: Optional[Callable[[], datetime]] = None, writer: Optional[Callable[[dict], Any]] = None,
                 bands: Optional[FB.FairBands] = None):
        self.source = source or default_source()
        self.catalog = load_catalog() if catalog is None else catalog
        self.crs_path = crs_path
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.writer = writer
        # Tiger Data reads the band only for the real Tiger source; a fixture or fake source never reaches the network
        self.bands = bands or FB.FairBands(tiger=type(self.source) is TigerSource, now=self.now)
        self.latest: dict = {}
        self.latest_pulse: dict = {}

    # sellers listing a SKU: the catalog plus whoever bid on it this round
    def sellers_for(self, sku: str, rows: Optional[list[dict]] = None) -> list[str]:
        ids = [sid for sid, c in self.catalog.items() if sku in c["skus"]]
        for r in rows or []:
            if any(line["sku_spec"] == sku for line in r["lines"]) and r["seller_id"] not in ids:
                ids.append(r["seller_id"])
        return sorted(ids)

    def band_for(self, sku: str) -> Optional[dict]:
        """The sku's fair band, or None when reading it failed: a band never stops a note or an answer."""
        try:
            return self.bands.band(sku)
        except Exception:  # noqa: BLE001
            return None

    def seller_note(self, report: dict, sku: str, gap_pct: Optional[float] = None) -> dict:
        d, c = self.source.demand(), self.source.coach(report["seller_id"])
        base = MP.note_for(report, sku, d, c, writer=self.writer)
        record = {str(w): record_block(self.source.record(report["seller_id"], w)) for w in WINDOWS}
        band = self.band_for(sku)
        gap = gap_pct if report["reason"] == "price" else None      # only a seller priced out has a gap to report
        coach_line = coaching.coaching_line(gap, band) if gap is not None and band else None
        lines = [f"Round {report['round_id']}: {base['what_to_change']} [round {report['round_id']}]",
                 *([coach_line] if coach_line else []), *(record[str(w)]["line"] for w in WINDOWS)]
        note = {k: base[k] for k in ("seller_id", "round_id", "gap_band", "reason", "source_url", "action", "price_step",
                                     "what_to_change", "what_to_change_origin", "market")}
        note.update(sku=sku, record=record, lines=lines, gap_pct=gap if coach_line else None,
                    fair_band={k: band[k] for k in BAND_KEYS} if band else None)
        return note

    def buyer_trend(self, sku: str, rows: Optional[list[dict]] = None, signals: Any = "read") -> dict:
        windows = {str(w): price_block(self.source.price(sku, w)) for w in WINDOWS}
        sig = read_crs(self.crs_path, self.now()) if signals == "read" else signals
        counts = crs_counts(self.sellers_for(sku, rows), sig)
        lines = [windows[str(w)]["line"] for w in WINDOWS] + [crs_line(counts)]
        band = self.band_for(sku)
        return {"sku": sku, "windows": windows, "crs": counts, "lines": lines,
                "fair_band": {k: band[k] for k in BAND_KEYS} if band else None}

    def process_round(self, rnd: dict) -> dict:
        """Notes for every losing seller and a trend for every SKU of the round. Remembers them for chat."""
        rows = rnd["rows"]
        sku_of = {r["seller_id"]: r["lines"][0]["sku_spec"] for r in rows}
        signals = read_crs(self.crs_path, self.now())
        gaps = coaching.exact_gaps(rows)
        notes, skipped = [], list(rnd["skipped"])
        for rep in rnd["reports"]:
            try:
                notes.append(self.seller_note(rep, sku_of.get(rep["seller_id"], skus_of(rows)[0]), gaps.get(rep["seller_id"])))
            except ValueError:
                skipped.append({"seller_id": rep["seller_id"], "why": "unknown band or reason"})
        trends_ = [self.buyer_trend(s, rows, signals) for s in skus_of(rows)]
        result = {"round_id": rnd["round_id"], "reports_from": rnd["reports_from"], "tiger": self.source.name, "seller_notes": notes,
                  "buyer_trends": trends_, "skipped": skipped}
        self.latest = {"round_id": rnd["round_id"], "notes": {n["seller_id"]: n for n in notes}}
        return result

    # ------------------------------------------------------------ chat
    def known_skus(self) -> list[str]:
        """Every part this Pulse can speak about: the catalog's, and any part with a dated MIRROR snapshot."""
        skus = {s for c in self.catalog.values() for s in c["skus"]}
        try:
            skus |= {str(r.get("sku", "")).strip().lower() for r in self.bands.snapshots() if r.get("kind") == "ask"} - {""}
        except Exception:  # noqa: BLE001
            pass
        return sorted(s for s in skus if SKU_SHAPE.match(s))

    def publish_before_round(self, skus: list[str], *, path: Optional[Path] = None) -> dict:
        """Publish the fair band of every part of the coming round as one public, sourced pulse (a JSON file the Buyer can read,
        and the answer to a PulseBandRequest). Remembers it for chat."""
        self.latest_pulse = FB.publish_pulse(skus, path=path, bands=self.bands)
        return self.latest_pulse

    def price_answer(self, sku: str) -> str:
        """The going price: the band's sentence with its source, when it was published (if it was), and Tiger's demand for the part."""
        band = self.band_for(sku)
        if band is None:
            return f"{sku.upper()}: I could not read a price for this part right now. [Market Pulse; not available]"
        lines = [band["label"]]
        published = (self.latest_pulse.get("bands") or {}).get(sku)
        if published and self.latest_pulse.get("published_at"):
            lines.append(f"Published before the round at {self.latest_pulse['published_at']}.")
        try:
            demand = MP.market_facts(sku, self.source.demand(), {"status": "error"}).get("demand", {})
        except Exception:  # noqa: BLE001
            demand = {}
        if "round_hours_24h" in demand:
            hours = demand["round_hours_24h"]
            lines.append(f"Demand: {hours} round-hour{'' if hours == 1 else 's'} with bids for this part in the last 24 hours. "
                         f"[{demand['source']}; {demand['origin']}]" if hours else
                         f"Demand: no rounds with bids for this part in the last 24 hours. [Tiger Data bid_curve_10s; no data]")
        return "\n".join(lines)

    def answer(self, text: str, sender_allowed: Callable[[str], bool] = lambda seller_id: True) -> str:
        """A fixed-phrase answer to a chat question. The user's words only choose which known SKU or seller id to talk about;
        none of them are repeated."""
        words = re.findall(r"[a-z0-9]+", str(text).lower())
        sku = match_sku(words, self.known_skus())
        seller = match_seller(str(text).lower(), self.catalog)
        asks_losing = bool(set(words) & {"lose", "losing", "lost", "loss", "losses", "win", "winning", "record", "behind"})
        if seller and (asks_losing or not sku):
            if not sender_allowed(seller):
                return "I only answer a seller's record to that seller's own agent."
            return self.seller_answer(seller)
        if sku and set(words) & PRICE_WORDS and not set(words) & TREND_WORDS:
            return self.price_answer(sku)
        if sku:
            return "\n".join([f"{sku.upper()}: the week and the month.", *self.buyer_trend(sku)["lines"]])
        if asks_losing:
            ids = ", ".join(sorted(self.catalog)) or "your seller id"
            return f"Tell me which seller, for example \"why does seller_3 keep losing?\". Sellers I know: {ids}."
        return HELP

    def seller_answer(self, seller_id: str) -> str:
        lines = [f"{self.catalog.get(seller_id, {}).get('name', seller_id)} ({seller_id}): your record."]
        for w in WINDOWS:
            lines.append(record_block(self.source.record(seller_id, w))["line"])
        note = (self.latest.get("notes") or {}).get(seller_id)
        if note:
            lines.append(f"Latest round {self.latest['round_id']}: {note['what_to_change']} [round {self.latest['round_id']}]")
        elif self.latest:
            lines.append(f"You have no loss on record in the latest round {self.latest['round_id']} (you won it or did not enter it). [round {self.latest['round_id']}]")
        else:
            lines.append("No finished round has reached me since I started, so there is no round note yet.")
        return "\n".join(lines)


def match_sku(words: list[str], skus: list[str]) -> Optional[str]:
    """The known SKU whose words are all in the question (longest wins). A SKU's brand word (rtx, rx, gtx) may be left out."""
    brand = {"rtx", "rx", "gtx"}
    have, best = set(words), None
    for sku in skus:
        toks = re.findall(r"[a-z0-9]+", sku)
        core = [t for t in toks if t not in brand]
        if (set(toks) <= have or (core and set(core) <= have and any(t.isdigit() for t in core))) and (best is None or len(toks) > best[0]):
            best = (len(toks), sku)
    return best[1] if best else None


def match_seller(lowered: str, catalog: dict) -> Optional[str]:
    """The catalog seller the question names, by id (seller_3 or "seller 3") or by name. Longest id first, so seller_1 never
    matches inside seller_10."""
    squashed = re.sub(r"[^a-z0-9]+", "", lowered)
    for sid in sorted(catalog, key=len, reverse=True):
        name = re.sub(r"[^a-z0-9]+", "", catalog[sid]["name"].lower())
        tokens = re.findall(r"[a-z0-9]+", lowered)
        id_toks = re.findall(r"[a-z0-9]+", sid.lower())
        if any(tokens[i:i + len(id_toks)] == id_toks for i in range(len(tokens))) or (len(name) > 3 and name in squashed):
            return sid
    return None


# ---------------------------------------------------------------- output

def render(result: dict) -> str:
    out = [f"MARKET PULSE {result['round_id']}  (Tiger source: {result['tiger']}; loss reports: {result['reports_from']})"]
    if result["tiger"] == SIM_SRC:
        out.append("Tiger Data is not configured: every week and month figure below is a SIM fixture until real rounds accumulate.")
    out.append("")
    out.append("SELLERS")
    if not result["seller_notes"]:
        out.append("  no losing seller has a note")
    for n in result["seller_notes"]:
        out.append(f"  {n['seller_id']}  ({n['gap_band']}, {n['reason'].replace('_', ' ')})")
        out.extend(f"    {line}" for line in n["lines"])
    for s in result["skipped"]:
        out.append(f"  {s['seller_id']}  no note: {s['why']}")
    out.append("")
    out.append("BUYERS")
    for t in result["buyer_trends"]:
        out.append(f"  {t['sku'].upper()}")
        out.extend(f"    {line}" for line in t["lines"])
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m agents.pulse.orchestrator", description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--round-file", help="a JSON file: {round_result: [...], loss_reports?: [...]}")
    src.add_argument("--market-round", help="a closed round id to read from the market (needs --token-file)")
    src.add_argument("--serve", action="store_true", help="run the Market Pulse uAgent (long-running; not used by tests)")
    src.add_argument("--publish-pulse", nargs="+", metavar="SKU",
                     help="publish the fair band of these parts as the public pulse (PULSE_PUBLIC_PATH or .run/pulse/latest.json)")
    ap.add_argument("--token-file", help="an existing market identity file (never created here)")
    ap.add_argument("--crs-cache", help="path to crs-signals.json (default: CRS_SIGNAL_CACHE_PATH or .cache/crs-signals.json)")
    ap.add_argument("--no-sim", action="store_true", help="without Tiger Data, show 'not configured' instead of the SIM fixture")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)
    pulse = Pulse(default_source(sim_fallback=not args.no_sim), crs_path=Path(args.crs_cache) if args.crs_cache else None)
    if args.serve:
        build_agent(pulse).run()
        return 0
    if args.publish_pulse:
        try:
            out = pulse.publish_before_round([s.strip().lower() for s in args.publish_pulse])
        except ValueError as e:
            print(f"market pulse: {e}", file=sys.stderr)
            return 2
        for b in out["bands"].values():
            print(b["label"])
        print(f"published {len(out['bands'])} band(s) at {out['published_at']} to {FB.pulse_path()}")
        return 0
    try:
        if args.round_file:
            rnd = load_round(args.round_file)
        else:
            if not args.token_file or not Path(args.token_file).exists():
                raise PulseError("--market-round needs an existing --token-file (this never creates an identity)")
            scripts = str(ROOT / "market" / "scripts")
            if scripts not in sys.path:
                sys.path.insert(0, scripts)
            from stdb import Market  # noqa: PLC0415
            rnd = round_from_market(args.market_round, Market(token_file=args.token_file))
    except PulseError as e:
        print(f"market pulse: {e}", file=sys.stderr)
        return 2
    result = pulse.process_round(rnd)
    print(json.dumps(result, indent=1, sort_keys=True) if args.json else render(result))
    return 0


# ---------------------------------------------------------------- the uAgent

def round_senders() -> set[str]:
    """Agent addresses allowed to send a PulseRound (PULSE_ROUND_SENDERS, comma separated: the referee and the operator).
    Unset means nobody: a round replaces what chat answers about, so an unknown sender never gets to send one."""
    return {a.strip() for a in os.environ.get("PULSE_ROUND_SENDERS", "").split(",") if a.strip()}


def build_agent(pulse: Pulse, *, port: int = 8018):
    """The Market Pulse uAgent. uagents is imported here only, so the rest of this module runs without it. Local by default;
    PULSE_MAILBOX=1 (or AGENTS_MAILBOX=1) uses a mailbox and refuses the public dev seed. Nothing is registered by building it."""
    from uagents import Agent, Context, Model, Protocol
    from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

    import common  # agents/common.py: Shield screening (fails closed) and the shared env loading

    seed = os.environ.get("PULSE_AGENT_SEED") or "tech-bazaar-pulse-dev"
    mailbox = bool(os.environ.get("PULSE_MAILBOX") or os.environ.get("AGENTS_MAILBOX"))
    if mailbox and seed.endswith("-dev"):
        sys.exit("Set PULSE_AGENT_SEED to a private seed before putting Market Pulse on Agentverse: the default seed is public.")
    args: dict = dict(seed=seed, port=port, name="Market Pulse", publish_agent_details=True,
                      handle=os.environ.get("PULSE_AGENT_HANDLE") or "techbazaarpulse",
                      description="Teaches sellers and buyers the market's week and month: price trends from Tiger Data, "
                                  "CRS verified seller counts, and a note for every seller that lost a round.")
    if avatar := common.avatar_url("pulse"):
        args["avatar_url"] = avatar
    readme = Path(__file__).with_name("AGENTVERSE.md")
    if readme.exists():
        args["readme_path"] = str(readme)
    args.update(mailbox=True) if mailbox else args.update(endpoint=[f"http://localhost:{port}/submit"])
    agent = Agent(**args)

    class PulseRound(Model):
        round_json: str          # {"round_result": [...], "loss_reports"?: [...]}

    class PulseNotes(Model):
        notes_json: str

    class PulseBandRequest(Model):
        skus_json: str           # ["rtx 5070 ti", "psu 750w"]: at most MAX_BAND_SKUS parts

    class PulseBands(Model):
        pulse_json: str          # the public pulse ({"kind": "market-pulse", "bands": {...}}) or {"error": "..."}

    own_addresses: dict[str, str] = {}

    def allowed(sender: str):
        def check(seller_id: str) -> bool:
            if os.environ.get("PULSE_SELLER_CHAT") == "open":     # the default is own: a record goes to its own seller agent
                return True
            if seller_id not in own_addresses:
                try:
                    own_addresses[seller_id] = common.address(seller_id)
                except Exception:  # noqa: BLE001
                    return False
            return own_addresses[seller_id] == sender
        return check

    chat = Protocol(spec=chat_protocol_spec)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        verdict = common.screen(str(msg.msg_id), sender, msg.text())
        text = pulse.answer(msg.text(), allowed(sender)) if verdict.get("verdict") == "allow" else "Smell Test blocked this message. No action taken."
        await ctx.send(sender, ChatMessage(content=[TextContent(text=text)]))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    @agent.on_message(model=PulseRound, replies=PulseNotes)
    async def on_round(ctx: Context, sender: str, msg: PulseRound):
        if sender not in round_senders():       # only the referee or operator may feed a round: it replaces `latest`
            ctx.logger.warning(f"round from {sender} ignored: not in PULSE_ROUND_SENDERS")
            return
        verdict = common.screen(f"pulse-{ctx.session}", sender, msg.round_json)
        if verdict.get("verdict") != "allow":
            ctx.logger.warning(f"shield {verdict.get('verdict')} from {sender}")
            return
        try:
            data = json.loads(msg.round_json)
            result = pulse.process_round(round_from_rows(data.get("round_result"), data.get("loss_reports")))
        except (ValueError, AttributeError) as e:
            ctx.logger.warning(f"round not read: {e if isinstance(e, PulseError) else 'bad json'}")
            return
        await ctx.send(sender, PulseNotes(notes_json=json.dumps(result["seller_notes"])))
        try:   # the next round's buyers read a fresh market: publish the pulse for the parts this round priced
            pulse.publish_before_round([t["sku"] for t in result["buyer_trends"]])
        except Exception:  # noqa: BLE001
            ctx.logger.warning("pulse not refreshed after the round")

    @agent.on_message(model=PulseBandRequest, replies=PulseBands)
    async def on_band_request(ctx: Context, sender: str, msg: PulseBandRequest):
        """Open to any sender: the pulse is the market's public price, with no seller, buyer or cap in it. Shield first, then a
        fixed-shape request (a JSON list of known-shape part names); anything else gets a fixed error and runs nothing."""
        import asyncio

        def reply(body: dict) -> PulseBands:
            return PulseBands(pulse_json=json.dumps(body))
        verdict = await asyncio.to_thread(common.screen, f"pulse-band-{ctx.session}", sender, msg.skus_json)
        if verdict.get("verdict") != "allow":
            await ctx.send(sender, reply({"error": "shield_blocked"}))
            return
        try:
            skus = json.loads(msg.skus_json)
        except ValueError:
            skus = None
        ok = (isinstance(skus, list) and 0 < len(skus) <= MAX_BAND_SKUS
              and all(isinstance(s, str) and SKU_SHAPE.match(s.strip().lower()) for s in skus))
        if not ok:
            await ctx.send(sender, reply({"error": "bad_request"}))
            return
        try:
            body = await asyncio.to_thread(pulse.publish_before_round, [s.strip().lower() for s in skus])
        except Exception:  # noqa: BLE001
            body = {"error": "unavailable"}
        await ctx.send(sender, reply(body))

    agent.include(chat, publish_manifest=True)

    @agent.on_event("startup")
    async def announce(ctx: Context):
        ctx.logger.info(f"Market Pulse {agent.address} ({'mailbox' if mailbox else 'local'}), Tiger source: {pulse.source.name}")

    agent.pulse_models = (PulseRound, PulseNotes)
    agent.pulse_band_models = (PulseBandRequest, PulseBands)
    return agent


if __name__ == "__main__":
    raise SystemExit(main())
