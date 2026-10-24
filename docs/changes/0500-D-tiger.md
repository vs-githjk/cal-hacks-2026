# 0500 D Tiger Data price history and round curve
New package `data/tiger/` (schema.sql, store.py, load.py). Tiger Data is the time-series store behind the history views; the live market stays in SpacetimeDB. State: code and fake-connection tests only. NOT run against a live Tiger service (TIGER_DATA_SERVICE_URL was not in the builder's environment), so the SQL below is untested on a real server.

Tables (all hypertables): `price_obs` (dated price per sku, store, provider, listing url, with origin LIVE, MIRROR or SIM), `bid_ticks` (event bid, withdraw, win or blocked), `loss_reports`. Continuous aggregates, real time: `bid_curve_10s` (best bid and bid count per round, sku and 10 seconds) and `market_1h` (typical_cents, min_cents, n per sku and hour, in-stock rows only). Every statement is `IF NOT EXISTS`; nothing drops, truncates or deletes.

Differences from plan/sponsor-needs.md section 2, each on purpose:
- The unique index on `price_obs` is (ts, sku, store, provider, url), not without url: one store lists several cards at the same instant (three Best Buy rows share a timestamp in the snapshot), and the shorter key would keep one of them. The hypertable orderby adds store, provider and url so the unique columns are all in segmentby or orderby (TimescaleDB's columnstore rule, from the docs, not checked on a server).
- `bid_curve_10s` carries `sku` so it can join `market_1h`. `market_1h` names its column `typical_cents`: the median (`percentile_cont`), or the mean if the server refuses `percentile_cont` in a continuous aggregate (`store.MARKET_1H_FALLBACK`, reported by `apply_schema()["market_1h"]`).
- An optional statement adds a columnstore policy (compression); if the server lacks it the schema still applies and `optional_failed` names it.

API: `store.status()`, `apply_schema()`, `write_price_obs(rows)`, `write_bid_ticks(rows)`, `write_loss_reports(rows)`, `best_bid_vs_market(round_id)` (one parameterized query). With the env var unset each raises `NotConfigured` before any connection. Errors never carry the connection string, password or host.

Loader: `python3 -m data.tiger.load --dry-run` (counts, no connection, works with no env). Today it reports 19 source rows, 9 comparable retail asks, 10 skipped (marketplace and sold rows stay out, as in data.baselines). `python3 -m data.tiger.load` writes once and is idempotent (re-run inserts 0). `--brightdata` adds one Bright Data fetch (credits), never in a dry run.

Honesty rule: a row's origin is its origin at write time. A Bright Data row stored as LIVE is MIRROR (dated) to any later reader, so no screen may show a stored row as LIVE.

Live run: not done. To run it: set TIGER_DATA_SERVICE_URL, then `python3 -m data.tiger.load`, then paste the printed counts here (never the URL). Affects: nothing existing; T15 (trends) builds on `price_obs` and `loss_reports`.
