# Lane B: supplier_signal table and partial bid reason

- New public table `supplier_signal` (supplier_id primary key, stability, checked_at ISO, source) and reducer `record_supplier_signal(supplierId, stability, checkedAt, source)`, referee only. Bands only (verified_stable, caution, not_verified); sources sandbox, recorded, live, mirror, simulated. The latest check replaces the row. Lane A's adapter (or the bridge) writes it; /buyer and /market show the band with the fixed reason text and grey out not_verified and results older than 24 hours.
- close_round: a ranked bid that does not cover every needed item (rankBids `complete` false) gets the reason `missing: <sku, sku>` on its round_result row.
- Mandate refusal for non-eligible bands is not in this change.
