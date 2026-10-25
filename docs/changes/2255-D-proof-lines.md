# 2255-D: sponsor proof lines on the deal card (BuildView additions, additive only)

Judge fix 3 (plan/judge-2230.md). Two optional fields on the BuildView; the board and `contracts/samples/build-board.sample.json` ignore them, and nothing in `market/` changes.

- `parts[].history` (only on a part that has a champion): Tiger Data's read for the part's SKU (`part.label.lower()`, as the round's `sku_spec`).
  `{state: ok | no_data | not_configured | error, origin: MIRROR | SIM, windows: [{days: 7 | 30, low, median, n, daysOfData}]}` in dollars.
  A window carries numbers only when Tiger holds rows for it; `daysOfData` is how many days it really holds. A stored row is dated, so the label is never LIVE.
  Read in `demo/build.py` `BuildRun.read_history` through `demo.sponsors_live.price_history` (`data.tiger.trends.price_trend`), bounded, behind the existing
  `TIGER_DATA_SERVICE_URL`. No URL means `not_configured` and no connection.
- `parts[].champion.liveCheck.source` = "Bright Data". `liveCheck` already existed (state, price, fetchedAt, origin, quoted).

`GET /v1/build` (local agent feed, `scripts/agent_feed.py`) now serves, from those:
- `champion.liveCheck` = `{state, origin, source, fetchedAt}` only. `fetchedAt` and the LIVE label go out only for a read this run made with a real time. The price read and the quote stay private.
- `parts[].history` = `{state, origin, windows[{days, low, median, n, daysOfData}]}`; LIVE is clamped to MIRROR.

The hosted board's `public_view` is unchanged: neither field goes to the public `build_view` table.
