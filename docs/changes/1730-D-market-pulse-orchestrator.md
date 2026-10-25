# 1730 D Market Pulse orchestrator (#260 phase 1)
New: `agents/pulse/orchestrator.py` (uAgent "Market Pulse", runner, chat answers), `agents/pulse/AGENTVERSE.md`, `agents/pulse/fixtures/round1_sample.json`. Added to `data/tiger/trends.py`: `WINDOWS = (7, 30)`, `price_trend(sku, days)`, `seller_record(seller_id, days)`, `gap_band`. No Lane A, market or web file is edited.

State: code and tests only. Not registered on Agentverse, no long-running agent started, not run against the live market or a live Tiger service (TIGER_DATA_SERVICE_URL is not in the builder's environment, so the new SQL is untested on a real server, like 0500-D-tiger.md).

## What a finished round produces
- A note per losing seller: the existing `market_pulse` note plus the seller's 7-day and 30-day record (rounds entered, won, win rate, median gap band) from Tiger.
- A trend per SKU: 7-day and 30-day lowest, median, now and direction from `price_obs`, and the count of sellers listing the SKU that are CRS verified (from `.cache/crs-signals.json`, same freshness and shape checks as `agents/crs.py`; a seller with no fresh signal is "no current check", never verified).
- "only N days of data" wherever Tiger holds fewer days than the window. Nothing is padded.
- Without TIGER_DATA_SERVICE_URL the windows come from a deterministic fixture, every line tagged `[SIM fixture; SIM]`; `--no-sim` prints "not configured" and no numbers.

## Run it
`python3 -m agents.pulse.orchestrator --round-file agents/pulse/fixtures/round1_sample.json [--crs-cache <path>] [--json] [--no-sim]`
`--market-round <round_id> --token-file <existing identity file>` reads `round_result` through `market/scripts/stdb.py` (never creates an identity; untested live). `--serve` runs the agent (long-running).

## Hooks wanted from other lanes (not done here)
- Lane A (Abhinav): after a round closes, the buyer or referee agent can send the Market Pulse agent a `PulseRound(round_json)` message (`{"round_result": [...], "loss_reports": [...]}`) and gets `PulseNotes(notes_json)` back. Seller agents could show the note from `my_loss_reports` plus that reply. Market Pulse needs an address in `agents/README.md` once registered.
- Lane A: `common.SEEDS` has no `pulse` role; the agent reads `PULSE_AGENT_SEED` itself (mailbox needs a private seed, else it exits). Add `PULSE_AGENT_SEED` to `agents/.env.example` if you want it listed.
- Vedant and Abhinav (#123 dashboard): `--json` prints the same result a panel would read (`seller_notes[].record["7"|"30"]`, `buyer_trends[].windows`, `.crs`). There is no HTTP API yet.

## Round history to Tiger (added after the first run on the real service)
The first run on the real Tiger service found no tables and nothing writing `bid_ticks` or `loss_reports`, so every seller record said "no rounds recorded".
- `data/tiger/history.py` (`round_ticks`, `loss_rows`) turns a closed round's `round_result` rows and the referee's loss reports into Tiger rows, each with its origin (LIVE, MIRROR or SIM; a row stating none is SIM). A runner that is not `demo/bridge.py` (the full-build runner in #368) calls `demo.sponsors_live.round_ticks`, `write_round_ticks`, `loss_rows` and `write_loss_reports`: bounded, best effort, a Tiger failure is a console line plus a log line (`demo.tiger`) and never stops a round or a payment.
- `demo/bridge.py`: the bid ticks (a `win` tick for rank 1, `blocked` for a disqualified bid, `bid` for the rest) are written when beat 4 reads the round, before the winner gate, so a round with no payable winner is still recorded. The loss reports are written in one batch after the run's last step (after the payment). Both are wired on `--live-call`, and on any run when TIGER_DATA_SERVICE_URL is in the environment.
- `bid_ticks` and `loss_reports` gain a nullable `origin` column. New databases get it from `CREATE TABLE`; a service created before this change needs `python3 -m data.tiger.load` run again (the `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements are idempotent). Until then writes and `seller_record` fail with a visible error, not a wrong number. Not run against a real server by the builder.
- `lost_by_cents` is the loser's landed price minus the champion's, in whole cents, never below 0; None when the loser or the champion has no row in the market's `round_result`.
- `data.tiger.load` now prints each optional statement it skipped with the server's reason ("optional, skipped (plan does not support columnstore)" when the reason names the plan; otherwise the server's own words, redacted).
- Labels: a record or price line from a real Tiger read carries the origin of the rows it was built from; a real read that found none says "no data" (it used to say SIM).
