market/spacetimedb round_result (public table, Lane B): two new columns, appended last so a publish migrates in place.

- `adjusted_total` (f64, default 0): the real quality-adjusted score `rankBids` used to order the row (rules/scoring.ts `rankBids(...).ranked[].score`), stored by `closeRoundInner`. Equal to `landed` when the row was never ranked (disqualified) or when nothing adjusted it.
- `adjustment_reason` (string, default ''): a short line naming the condition step and the no-returns step that applied (new `adjustmentReason` export in rules/scoring.ts), empty when `adjusted_total` equals `landed`.

Bindings regenerated (`spacetime generate`). Web: `RankedBid.adjusted`/`adjustedReason` in web/src/lib/screens.ts now come from these real stored fields (not recomputed, not invented); the buyer screen's "Adjusted" column and the hero's "Quality-adjusted" line are back, honest this time (#135 review item 2).
