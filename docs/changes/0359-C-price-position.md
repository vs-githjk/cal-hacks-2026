# Scoreboard gains an optional price_position block (issue #141)

`data/scoreboard.json` has a new optional top-level key `price_position` (also an optional property in `contracts/Scoreboard.schema.json`): rank among in-stock, same-condition, fitting retail listings for the demo winner, with `sentence` (the exact on-screen line), `status` (one_source or ok), `snapshot_dates`, and the sold median when the baseline is ok. Render `sentence` as is; never add the word "savings". The tiles array is unchanged.
