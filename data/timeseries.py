"""Time-series queries for the recorded price feed and the wind-tunnel rounds (Lane C, kickoff item c15, slip form).

Plain SQLite queries (stdlib sqlite3, in-memory by default, optional file path). Tiger Data (Timescale) would store these as
hypertables with continuous aggregates; not used here: no account was set up.

    python3 -m data.timeseries      # the four queries for rtx 5070 ti and the largest wind tunnel run
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

FOOTER = ("Plain SQLite queries. Tiger Data (Timescale) would store these as hypertables with continuous aggregates; "
          "not used here: no account was set up.")
OUT = Path(__file__).resolve().parents[1] / "sim" / "out"


def connect(path: str = ":memory:") -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS price_observations(observed_at TEXT, provider TEXT, store TEXT, url TEXT, sku TEXT,
            price REAL, in_stock INTEGER, condition TEXT, kind TEXT, origin TEXT);
        CREATE TABLE IF NOT EXISTS rounds(run_file TEXT, seed INTEGER, builder TEXT, archetype TEXT,
            winner_trained TEXT, winner_untrained TEXT);
        CREATE INDEX IF NOT EXISTS po_url ON price_observations(url, observed_at);
    """)
    return db


def load(rows: list[dict] | None = None, run_files: list[Path] | None = None, path: str = ":memory:") -> sqlite3.Connection:
    """price_observations from data.baselines.observations() (or the rows given); rounds from sim/out held_out rows."""
    db = connect(path)
    if rows is None:
        from data.baselines import observations
        rows = observations()
    db.executemany("INSERT INTO price_observations VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [(r["observed_at"], r.get("provider"), r["store"], r.get("url"), r["sku"], r["price"], int(bool(r["in_stock"])),
                     r.get("condition"), r["kind"], r.get("origin")) for r in rows])
    for f in (sorted(OUT.glob("wind_tunnel-*.json")) if run_files is None else run_files):
        add_run(db, f)
    db.commit()
    return db


def add_run(db: sqlite3.Connection, f: Path) -> None:
    for s in json.loads(Path(f).read_text())["learning"]["seeds"]:
        db.executemany("INSERT INTO rounds VALUES (?,?,?,?,?,?)",
                       [(Path(f).name, s["seed"], h["builder"], h["archetype"], h.get("winner_trained") or "none",
                         h.get("winner_untrained") or "none") for h in s["held_out"]])


def price_series(db, url: str) -> list[tuple[str, float]]:
    return db.execute("SELECT observed_at, price FROM price_observations WHERE url=? ORDER BY observed_at", (url,)).fetchall()


def latest_per_listing(db, sku: str) -> list[tuple]:
    """One row per listing URL with its newest price: (url, store, observed_at, price)."""
    return db.execute("""SELECT p.url, p.store, p.observed_at, p.price FROM price_observations p
        JOIN (SELECT url, MAX(observed_at) m FROM price_observations WHERE sku=? GROUP BY url) l ON p.url=l.url AND p.observed_at=l.m
        WHERE p.sku=? GROUP BY p.url ORDER BY p.url""", (sku, sku)).fetchall()


def daily_min(db, sku: str, retail=("bestbuy", "microcenter", "bh", "newegg")) -> list[tuple[str, float]]:
    """Lowest in-stock retail ask per day (sold rows and other stores left out)."""
    marks = ",".join("?" * len(retail))
    return db.execute(f"""SELECT substr(observed_at, 1, 10) d, MIN(price) FROM price_observations
        WHERE sku=? AND kind='ask' AND in_stock=1 AND store IN ({marks}) GROUP BY d ORDER BY d""", (sku, *retail)).fetchall()


def win_rates(db, run_file: str) -> dict[str, dict[str, float]]:
    """{archetype: {seller: share of held-out rounds won by the trained learner's market}}; 'none' is its own entry. Sums to 1."""
    out: dict[str, dict[str, float]] = {}
    for arch, n in db.execute("SELECT archetype, COUNT(*) FROM rounds WHERE run_file=? GROUP BY archetype", (run_file,)).fetchall():
        out[arch] = {w: c / n for w, c in db.execute(
            "SELECT winner_trained, COUNT(*) FROM rounds WHERE run_file=? AND archetype=? GROUP BY winner_trained ORDER BY winner_trained", (run_file, arch))}
    return out


def main():
    db = load()
    sku = "rtx 5070 ti"
    urls = [r[0] for r in latest_per_listing(db, sku)]
    print("price_series (first listing):", urls[0] if urls else None, price_series(db, urls[0]) if urls else [])
    print("latest_per_listing:")
    for r in latest_per_listing(db, sku):
        print("  ", r)
    print("daily_min:", daily_min(db, sku))
    runs = [r[0] for r in db.execute("SELECT run_file, COUNT(*) c FROM rounds GROUP BY run_file ORDER BY c DESC, run_file DESC")]
    if runs:
        print("win_rates", runs[0])
        for arch, d in win_rates(db, runs[0]).items():
            print("  ", arch, {k: round(v, 2) for k, v in d.items()})
    print(FOOTER)


if __name__ == "__main__":
    main()
