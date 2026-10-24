# Partial bids never outrank complete ones (issue #136)

Lane C changed `market/rules/scoring.ts` as the issue assigned.

- `Ranked` gains two additive fields: `complete: boolean` (every needed SKU has a picked line) and `missing: string[]` (the needed `sku_spec`s no picked line covers).
- `rankBids` sorts complete bids before partial ones, then by the existing keys, unchanged. A partial bid is still ranked (not dropped), below every complete bid; its `missing` list says what it does not cover.
- Existing order among complete bids is unchanged; the existing tests pass unmodified.
- Contract behaviour change: on a multi-item need, $100 for one of two items no longer beats a complete $200 bid.
