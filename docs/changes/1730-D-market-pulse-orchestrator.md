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
- Whoever writes Tiger rows: `bid_ticks` must carry the `win` tick (rank 1) for `seller_record` to count wins and to join a loss to the winning price for the gap band (`demo/sponsors_live.round_ticks` already does this). `loss_coach.rounds_bid` counts only `event = 'bid'`, so it leaves out a seller's wins; `seller_record` counts every tick.
