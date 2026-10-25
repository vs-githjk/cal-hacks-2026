#!/usr/bin/env python3
"""Set the demo sellers' private price floors on a market, so a round can have a winner.

The market refuses to pick a line the seller has no floor for ("no floor set for <sku> <condition>"), and the seller agents never call
set_floor (only demo/stage.py and demo/bridge.py do). On a fresh market a round therefore closes with "no eligible bid".

What it sets: for the market seller identities seller-a, seller-b, seller-c (the sellers.json sellers seller_1, seller_2, seller_3) one
floor per (sku, condition) in that seller's `floor_by_condition`, through set_floor_for_condition. That reducer is seller-only, so each
floor is written with that seller's own identity token. Re-running is safe: the reducer replaces the row for the same (sku, condition).
A floor is private to its seller (no view shows it), so this script cannot read floors back; it only writes them.

DRY RUN BY DEFAULT: it prints every call it would make and writes nothing. Pass --apply to write.

  python3 scripts/seed_floors.py                       # dry run, every demo SKU
  python3 scripts/seed_floors.py --sku "rtx 5070 ti"   # dry run, one SKU
  SSL_CERT_FILE=$(python3 -c 'import certifi;print(certifi.where())') python3 scripts/seed_floors.py --apply

A seller with no listing for a SKU gets no floor for it (it will not bid on it). Add one with --floor, for example
--floor 'seller-b=rtx 5070 ti:new:1189'.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
SELLERS_JSON = ROOT / "agents" / "sellers" / "sellers.json"
SUBJECT = {"seller_1": "seller-a", "seller_2": "seller-b", "seller_3": "seller-c"}   # the same map agents/sellers/seller_agent.py uses
CONDITIONS = ("new", "open-box", "refurbished", "used")   # market.ts CONDITIONS
DEFAULT_SERVER = "https://maincloud.spacetimedb.com"
DEFAULT_DB = "tech-bazaar"
DEFAULT_TOKENS = ROOT / ".tokens" / "tech-bazaar@maincloud.spacetimedb.com"


def planned_floors(catalog: dict, skus: Optional[list[str]] = None, extra: Optional[list[str]] = None) -> list[dict]:
    """[{seller, sku_spec, condition, floor}] in a stable order: from the catalog's floor_by_condition, then the --floor extras."""
    out: list[dict] = []
    for seller_id, subject in SUBJECT.items():
        listings = (catalog.get("sellers", {}).get(seller_id) or {}).get("listings", {})
        for sku, listing in listings.items():
            if skus and sku not in skus:
                continue
            for condition, floor in (listing.get("floor_by_condition") or {}).items():
                out.append({"seller": subject, "sku_spec": sku, "condition": condition, "floor": float(floor)})
    for text in extra or []:
        out.append(parse_extra(text))
    seen: dict[tuple, dict] = {}
    for row in out:   # a later --floor for the same (seller, sku, condition) wins, like the reducer's replace
        seen[(row["seller"], row["sku_spec"], row["condition"])] = row
    rows = list(seen.values())
    for row in rows:
        if row["condition"] not in CONDITIONS:
            raise ValueError(f"condition {row['condition']!r} for {row['seller']} {row['sku_spec']} is not one of {', '.join(CONDITIONS)}")
        if not row["floor"] > 0:
            raise ValueError(f"floor for {row['seller']} {row['sku_spec']} {row['condition']} must be above zero")
    return rows


def parse_extra(text: str) -> dict:
    try:
        seller, rest = text.split("=", 1)
        sku, condition, floor = rest.rsplit(":", 2)
        row = {"seller": seller.strip(), "sku_spec": sku.strip(), "condition": condition.strip(), "floor": float(floor)}
    except ValueError:
        raise ValueError(f"--floor wants SELLER=SKU:CONDITION:PRICE, got {text!r}") from None
    if row["seller"] not in SUBJECT.values():
        raise ValueError(f"--floor seller must be one of {', '.join(SUBJECT.values())}, got {row['seller']!r}")
    return row


def apply_floors(rows: list[dict], client_for: Callable[[str], Any], *, write: bool, say: Callable[[str], None] = print) -> int:
    """Make (or, without write, only list) the calls. Returns how many calls failed. A refused call is reported and the rest go on."""
    failed = 0
    clients: dict[str, Any] = {}
    for row in rows:
        label = f"{row['seller']:<9} {row['sku_spec']:<22} {row['condition']:<12} floor {row['floor']:>9,.2f}"
        if not write:
            say(f"DRY RUN  {label}")
            continue
        try:
            if row["seller"] not in clients:
                clients[row["seller"]] = client_for(row["seller"])
            clients[row["seller"]].call("set_floor_for_condition", sku_spec=row["sku_spec"], condition=row["condition"], floor=row["floor"])
            say(f"SET      {label}")
        except (RuntimeError, OSError, FileNotFoundError) as e:
            failed += 1
            say(f"FAILED   {label}: {str(e)[:160]}")
    return failed


def market_client_for(tokens_dir: Path, server: str, db: str) -> Callable[[str], Any]:
    """One stdb.Market per seller identity from its existing token file. A missing file is an error, never a new identity (a fresh
    identity has no seller role, so every floor it wrote would be refused)."""
    os.environ["SPACETIMEDB_HTTP"] = server
    os.environ["SPACETIMEDB_DB"] = db
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    import stdb

    def make(subject: str) -> Any:
        token = tokens_dir / f"{subject}.json"
        if not token.exists():
            raise FileNotFoundError(f"no token file {token}: that seller has no identity here")
        return stdb.Market(token_file=str(token))
    return make


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the floors (default: dry run, nothing is written)")
    ap.add_argument("--dry-run", action="store_true", help="the default; accepted so a script can say it out loud")
    ap.add_argument("--sku", action="append", help="only this sku_spec (repeatable); default every SKU the three sellers list")
    ap.add_argument("--floor", action="append", metavar="SELLER=SKU:COND:PRICE", help="one more floor, for a seller with no listing for that SKU")
    ap.add_argument("--server", default=DEFAULT_SERVER, help=f"market HTTP host (default {DEFAULT_SERVER})")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"database name (default {DEFAULT_DB})")
    ap.add_argument("--tokens-dir", default=str(DEFAULT_TOKENS), help="folder with seller-a.json, seller-b.json, seller-c.json")
    args = ap.parse_args(argv)
    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run contradict each other")
    catalog = json.loads(SELLERS_JSON.read_text(encoding="utf-8"))
    try:
        rows = planned_floors(catalog, args.sku, args.floor)
    except ValueError as e:
        ap.error(str(e))
    if not rows:
        print("nothing to set: no seller lists the SKU(s) asked for (use --floor to add one)")
        return 1
    print(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(rows)} floors on {args.server} database {args.db}")
    failed = apply_floors(rows, market_client_for(Path(args.tokens_dir), args.server, args.db), write=args.apply)
    if not args.apply:
        print("nothing was written. Re-run with --apply to set them.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
