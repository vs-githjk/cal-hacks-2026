"""Memory store for the #123 dashboard panel (#189): past goals, purchases, vetoes and seller lessons.

Every entry follows contracts/MemoryEntry.schema.json and comes from a file or a row that exists: a demo run
(demo/out/run-*.json) or a market snapshot (demo/out/market-memory-*.json, written by `snapshot` from owner SQL at
the end of a rehearsal). Nothing is invented: a run or snapshot that can't be read is listed as an error with no rows.

Labels: purchases are SIM this weekend (no real money moves; a Stripe test charge is still test mode), with the
listing's own label in `listing_origin`. A demo run's goal and lessons are SIM (typed goal, stand-in learner). A market
row keeps its own origin, and an origin outside LIVE, MIRROR and SIM reads as SIM. Lessons carry bands only.

    python3 -m demo.memory snapshot         # owner SQL on the local market -> demo/out/market-memory-<time>.json
    python3 -m demo.memory show [--sample]  # what GET /v1/memory returns
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"
ORIGINS = ("LIVE", "MIRROR", "SIM")
BANDS = ("within5", "within10", "within20", "over20")
SAMPLE = "sample-run.json"
MAX_FILE_BYTES = 5_000_000   # a bigger snapshot or run file is an error source, never read (#273)
SNAPSHOT_BUDGET_S = 30.0     # the whole market read; one hanging query past it is the most a rehearsal waits
EMPTY_NOTE = "no demo runs or market snapshots recorded yet"

# owner SQL, explicit columns so positional rows map to names (snake_case, as `spacetime sql` prints them)
QUERIES = {
    "goal": "SELECT id, buyer_id, cap, deadline, origin, created_at FROM goal",
    "goal_item": "SELECT goal_id, sku_spec, condition, quantity FROM goal_item",
    "mandate": "SELECT hash, id, deal_id, buyer_id, amount, payee, origin FROM mandate",
    "approval": "SELECT mandate_hash, method, at FROM approval",
    "payment": "SELECT mandate_hash, payment_ref, amount, at, mode FROM payment",
    "bid": "SELECT id, seller_id, persona FROM bid",
    "bid_check": "SELECT bid_id, kind, result, detail, evidence_url, origin, at FROM bid_check",
    "loss_report": "SELECT id, round_id, seller_id, won, gap_band, reason, what_to_change, origin, created_at FROM loss_report",
}


def _origin(value: Any) -> str:
    v = str(value or "").strip().upper()
    return v if v in ORIGINS else "SIM"


def _num(x: Any) -> float:
    """A finite number, or ValueError: an infinite cap or amount is never shown (nor sent as invalid JSON)."""
    v = float(x)
    if not math.isfinite(v):
        raise ValueError(f"not a finite number: {x!r}")
    return v


def _same_amount(a: Any, b: Any) -> bool:
    """Both real numbers (never a bool) within half a cent."""
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    return abs(a - b) <= 0.005   # "<=" is False for nan


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _entry(id_: str, kind: str, at: str, origin: str, source: str, ref: str, buyer: str, seller: str, summary: str,
           detail: dict) -> dict:
    return {"id": id_, "kind": kind, "at": str(at or ""), "origin": _origin(origin), "source": source, "source_ref": ref,
            "buyer_id": buyer or "", "seller_id": seller or "", "summary": summary, "detail": detail}


# ---------------------------------------------------------------- demo run files

def from_demo_run(run: Any, ref: str) -> list[dict]:
    """Entries from one demo/run_demo.py JSON file. A file without the expected shape gives no rows."""
    try:
        return _demo_entries(run, ref)
    except Exception:  # noqa: BLE001  (any odd shape or value, e.g. an overflowing number: no rows, never a 500)
        return []


def _demo_entries(run: dict, ref: str) -> list[dict]:
    a = run["artifacts"]
    at_run = str(run.get("generated_at") or "")
    out: list[dict] = []
    goal = a.get("goal") or {}
    buyer = str(goal.get("buyer_id") or "")
    if goal:
        items = [{"sku_spec": str(i["sku_spec"]), "condition": str(i.get("condition") or ""), "quantity": _num(i.get("quantity", 1))}
                 for i in goal.get("items") or []]
        text = str(goal.get("notes") or "").strip().strip("'\"")
        out.append(_entry(f"{ref}:goal:{goal['id']}", "goal", goal.get("created_at"), "SIM", "demo_run", ref, buyer, "",
                          f"Goal: {text or ', '.join(i['sku_spec'] for i in items)} (cap {_money(_num(goal['cap']))})",
                          {"goal_id": str(goal["id"]), "items": items, "cap": _num(goal["cap"]),
                           "deadline": str(goal.get("deadline") or ""), "text": text}))
    sellers = {b["id"]: b["seller_id"] for b in a.get("bids") or []}
    names = {b["seller_id"]: b.get("persona") or b["seller_id"] for b in a.get("bids") or []}
    m, rec, charge = a.get("mandate") or {}, a.get("approval_record") or {}, a.get("charge") or {}
    paid_cents = charge.get("amount_cents") if isinstance(charge, dict) else None
    # the approval names this mandate and read back its payee and amount; the charge is for this mandate at its amount (#273)
    matches = (m and m.get("hash") and rec.get("mandate_hash") == m.get("hash") and rec.get("mandate_id") == m.get("id")
               and rec.get("payee_read_back") == m.get("payee") and _same_amount(rec.get("amount_read_back"), m.get("amount"))
               and str(charge.get("status") or "").lower().startswith("succeeded") and charge.get("idempotency_key") == f"mandate:{m.get('hash')}"
               and isinstance(paid_cents, int) and not isinstance(paid_cents, bool) and _num(m["amount"]) > 0
               and paid_cents == round(_num(m["amount"]) * 100))
    if m and rec.get("result") == "approved" and charge and matches:   # approved, and charged for this mandate at its amount
        mode = str(charge.get("mode") or "").strip().lower()
        pay_mode = "sim" if mode.startswith("sim") else "stripe_test" if mode.startswith("stripe test") else "none"
        bid_id = str(m["deal_id"])[5:] if str(m["deal_id"]).startswith("deal-") else str(m["deal_id"])
        seller = sellers.get(bid_id, "")
        amount = _num(m["amount"])
        out.append(_entry(f"{ref}:purchase:{m['id']}", "purchase", rec.get("decided_at"), "SIM", "demo_run", ref,
                          str(m.get("buyer_id") or buyer), seller,
                          f"Bought from {names.get(seller) or 'the winner'} for {_money(amount)} before tax (SIM payment, no money moved)",
                          {"mandate_id": str(m["id"]), "deal_id": str(m["deal_id"]), "amount_before_tax": amount,
                           "currency": str(m.get("currency") or "USD"), "payee": str(m.get("payee") or ""),
                           "approval_method": "sim_script", "payment_mode": pay_mode,
                           "payment_ref": str(charge.get("id") or ""), "listing_origin": _origin(m.get("origin"))}))
    for card in (a.get("verdicts") or {}).get("advocate_cards") or []:
        if card.get("recommendation") != "veto":
            continue
        why = card.get("call_reason") or {}
        seller = sellers.get(card["bid_id"], "")
        bid_origin = next((b.get("origin") for b in a.get("bids") or [] if b["id"] == card["bid_id"]), "SIM")
        out.append(_entry(f"{ref}:veto:{card['bid_id']}", "veto", at_run, bid_origin, "demo_run", ref, buyer, seller,
                          f"Vetoed {names.get(seller) or card['bid_id']}: {why.get('summary') or why.get('rule_id')}",
                          {"bid_id": str(card["bid_id"]), "rule_id": str(why.get("rule_id") or ""),
                           "reason": str(why.get("summary") or ""), "source_url": str(why.get("source_url") or "")}))
    for lr in a.get("loss_reports") or []:
        if lr.get("gap_band") not in BANDS:
            continue
        out.append(_lesson(lr["id"], lr["round_id"], lr["seller_id"], bool(lr["won"]), lr["gap_band"], lr["reason"],
                           str(a.get("what_to_change") or "") if lr["seller_id"] == _learner(a) else "",
                           "SIM", lr.get("created_at"), "demo_run", ref, names.get(lr["seller_id"])))
    return out


def _learner(a: dict) -> str:
    return next((s["id"] for s in a.get("seller_agents") or [] if s.get("learning")), "")


def _lesson(id_, round_id, seller, won, band, reason, change, origin, at, source, ref, name=None) -> dict:
    verb = "won" if won else f"lost on {str(reason).replace('_', ' ')}"
    gap = f", price gap {band.replace('within', 'within ').replace('over', 'over ')} percent" if reason == "price" and not won else ""
    return _entry(f"{ref}:lesson:{id_}", "lesson", at, origin, source, ref, "", seller,
                  f"{name or seller} {verb} in {round_id}{gap}",
                  {"round_id": str(round_id), "won": won, "reason": str(reason), "gap_band": band,
                   "what_to_change": str(change or "")})


# ---------------------------------------------------------------- market rows

def _val(cell: Any) -> str:
    s = str(cell).strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def _rows(sql: Callable[[str], list], table: str, width: int, stats: dict) -> list[list[str]]:
    rows = sql(QUERIES[table])
    good = [[_val(c) for c in r] for r in rows if len(r) == width]
    stats["dropped"] = stats.get("dropped", 0) + len(rows) - len(good)   # a "|" inside a cell splits it: counted, never guessed
    return good


def from_market(sql: Callable[[str], list], ref: str, stats: Optional[dict] = None) -> list[dict]:
    """Entries from the market's own rows (owner SQL). A failing read raises: the caller records the error.
    `stats["dropped"]` counts rows that could not be read (and purchases whose rows disagree)."""
    stats = {} if stats is None else stats
    _r = lambda table, width: _rows(sql, table, width, stats)  # noqa: E731
    out: list[dict] = []
    items: dict[str, list[dict]] = {}
    for gid, sku, cond, qty in _r("goal_item", 4):
        items.setdefault(gid, []).append({"sku_spec": sku, "condition": cond, "quantity": _num(qty or 1)})
    for gid, buyer, cap, deadline, origin, at in _r("goal", 6):
        its = items.get(gid, [])
        out.append(_entry(f"{ref}:goal:{gid}", "goal", at, origin, "market", ref, buyer, "",
                          f"Goal: {', '.join(i['sku_spec'] for i in its) or gid} (cap {_money(_num(cap))})",
                          {"goal_id": gid, "items": its, "cap": _num(cap), "deadline": deadline}))
    bids = {r[0]: (r[1], r[2] or r[1]) for r in _r("bid", 3)}
    approvals = {r[0]: r[1] for r in _r("approval", 3)}
    payments = {r[0]: r for r in _r("payment", 5)}
    for h, mid, deal, buyer, amount, payee, origin in _r("mandate", 7):
        if h not in payments:
            continue                                    # a mandate with no payment row is not a purchase
        _, ref_, paid, at, mode = payments[h]
        if h not in approvals or not abs(float(paid) - float(amount)) <= 0.005 or not float(amount) > 0:   # "not" also refuses nan
            stats["dropped"] = stats.get("dropped", 0) + 1   # paid with no approval row, or a different amount: not shown
            continue
        bid_id = deal[5:] if deal.startswith("deal-") else deal
        seller, name = bids.get(bid_id, ("", ""))
        amt = _num(amount)
        pay_mode = mode if mode in ("sim", "stripe_test") else "none"
        note = "Stripe test mode, no real money" if pay_mode == "stripe_test" else "SIM payment, no money moved"
        out.append(_entry(f"{ref}:purchase:{mid}", "purchase", at, "SIM", "market", ref, buyer, seller,
                          f"Bought from {name or 'the winner'} for {_money(amt)} before tax ({note})",
                          {"mandate_id": mid, "deal_id": deal, "amount_before_tax": amt, "currency": "USD", "payee": payee,
                           "approval_method": approvals[h], "payment_mode": pay_mode, "payment_ref": ref_,
                           "listing_origin": _origin(origin)}))
    for bid_id, kind, result, detail, url, origin, at in _r("bid_check", 7):
        if kind != "advocate" or result != "veto":
            continue
        rule, _, text = detail.partition(" ")
        seller, name = bids.get(bid_id, ("", ""))
        out.append(_entry(f"{ref}:veto:{bid_id}", "veto", at, origin, "market", ref, "", seller,
                          f"Vetoed {name or bid_id}: {text or rule}",
                          {"bid_id": bid_id, "rule_id": rule, "reason": text, "source_url": url}))
    for id_, round_id, seller, won, band, reason, change, origin, at in _r("loss_report", 9):
        if band not in BANDS:
            continue                                    # a band we can't name is dropped, never guessed
        out.append(_lesson(id_, round_id, seller, won.lower() == "true", band, reason, change, origin, at, "market", ref))
    return out


def _budgeted(sql: Callable[[str], list], budget_s: float, clock: Callable[[], float]) -> Callable[[str], list]:
    """sql that refuses to start a query once budget_s has passed, so a hanging `spacetime sql` costs one timeout at most
    past the budget instead of one per table (#273)."""
    deadline = clock() + budget_s

    def run(query: str) -> list:
        if clock() >= deadline:
            raise TimeoutError(f"market read took over {budget_s:.0f} s; stopped before: {query[:40]}")
        return sql(query)
    return run


def snapshot(sql: Callable[[str], list], out_dir: Path, *, db: str, now: Optional[str] = None,
             budget_s: float = SNAPSHOT_BUDGET_S, clock: Callable[[], float] = time.monotonic) -> Path:
    """Write demo/out/market-memory-<time>.json from the market. A failed read is written as an error with no rows."""
    now = now or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ref = f"market:{db}@{now}"
    stats: dict = {}
    try:
        entries, error = from_market(_budgeted(sql, budget_s, clock), ref, stats), None
    except Exception as e:  # recorded, never a fake row
        entries, error = [], f"{type(e).__name__}: {e}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"market-memory-{now}.json"
    path.write_text(json.dumps({"taken_at": now, "db": db, "entries": entries, "error": error,
                                "dropped": stats.get("dropped", 0)}, indent=2) + "\n")
    return path


# ---------------------------------------------------------------- what GET /v1/memory returns

def _encodable(x: Any) -> bool:
    try:
        json.dumps(x, ensure_ascii=False, allow_nan=False).encode("utf-8")   # Infinity or NaN drops the row (#273)
        return True
    except (UnicodeEncodeError, ValueError, TypeError, RecursionError):
        return False


def _well_formed(e: Any) -> bool:
    return (isinstance(e, dict) and all(isinstance(e.get(k), str) for k in ("id", "kind", "at", "origin", "summary"))
            and e["origin"] in ORIGINS and isinstance(e.get("detail"), dict))


def load(out_dir: Path = OUT_DIR, *, include_sample: bool = False, kind: Optional[str] = None,
         limit: Optional[int] = None) -> dict:
    """The newest market snapshot plus every demo run file (the committed sample only when asked), newest first."""
    out_dir = Path(out_dir)
    entries: list[dict] = []
    sources: list[dict] = []
    snaps = sorted(out_dir.glob("market-memory-*.json")) if out_dir.is_dir() else []
    if snaps:
        newest = snaps[-1]
        try:
            if newest.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("snapshot too large")
            saved = json.loads(newest.read_text())
            rows = [e for e in saved.get("entries") or [] if _well_formed(e)]
            state = "error" if saved.get("error") else "ok"
            dropped = int(saved.get("dropped") or 0) + len(saved.get("entries") or []) - len(rows)
        except Exception:  # noqa: BLE001  (bad JSON, deep nesting, an overflowing count: an error source, never a 500)
            rows, state, dropped = [], "error", 0
        entries += rows
        sources.append({"ref": newest.name, "kind": "market", "state": state, "sample": False, "rows": len(rows),
                        "dropped": dropped})
    runs = sorted(out_dir.glob("run-*.json")) if out_dir.is_dir() else []
    if include_sample and (out_dir / SAMPLE).exists():
        runs.append(out_dir / SAMPLE)
    for f in runs:
        try:
            if f.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("run file too large")
            run = json.loads(f.read_text())
            ref = str(run.get("run_id") or f.stem)
        except Exception:  # noqa: BLE001
            sources.append({"ref": f.name, "kind": "demo_run", "state": "error", "sample": False, "rows": 0})
            continue
        rows = from_demo_run(run, ref)
        entries += rows
        sources.append({"ref": f.name, "kind": "demo_run", "state": "ok" if rows else "empty",
                        "sample": f.name == SAMPLE, "rows": len(rows)})
    if not sources:
        return {"entries": [], "sources": [], "note": EMPTY_NOTE}
    seen, unique = set(), []
    for e in entries:
        if not _encodable(e):
            continue                                    # a lone surrogate would make the JSON response fail
        if e["id"] not in seen:
            seen.add(e["id"])
            unique.append(e)
    unique.sort(key=lambda e: e["at"], reverse=True)
    if kind:
        unique = [e for e in unique if e["kind"] == kind]
    if limit is not None:
        unique = unique[:max(0, limit)]
    return {"entries": unique, "sources": [x if _encodable(x) else {**x, "ref": "(unreadable name)"} for x in sources],
            "note": ""}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Memory store for the dashboard panel (#189)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", help="read the local market as the owner and write demo/out/market-memory-<time>.json")
    show = sub.add_parser("show", help="print what GET /v1/memory returns")
    show.add_argument("--sample", action="store_true", help="include the committed sample run")
    args = ap.parse_args(argv)
    if args.cmd == "snapshot":
        from demo.rehearse import run_sql
        path = snapshot(run_sql, OUT_DIR, db=os.environ.get("SPACETIMEDB_DB", "tech-bazaar"))
        print(f"wrote {path.relative_to(ROOT)}")
        return 0
    print(json.dumps(load(OUT_DIR, include_sample=args.sample), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
