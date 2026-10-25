# Sealed rounds leak nothing before close (supersedes #416)

Public floor_event and round_result rows of an open round no longer name a bid, a seller, a verdict or a price.

- `place_bid` writes no floor event. The close of the round (or of a knockout stage, for that stage's bids) writes `bid_sealed` or `bid_rejected` for each bid, stamped with the moment the bid really arrived (`at` = the bid's `sealed_at`), in arrival order. `round.sealed_count` stays public.
- Every path that sets a round to closed (close_round, and close_stage with a champion, no survivor or no bid) flushes the deferred Shield, claim and advocate events of every bid in the round.
- A knockout stage that leaves the round open publishes its `knocked_out` rows with rank 0, landed 0, adjusted_total 0 and no lines. The real values wait in a new private table `round_result_sealed` and are copied back (and the held rows deleted) when the round closes.
- Schema: one new private table, `round_result_sealed`. Adding a table migrates in place on publish. Private tables are not in the client bindings, so `web/src/module_bindings` is unchanged.
- Web: no reader needed a change to stay correct; the buyer table and the corral show "·" instead of "$0.00" for a held-back row.
