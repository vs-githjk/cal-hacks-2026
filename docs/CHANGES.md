# Contract changes

- [20:36] B (proposed, lane-b-market-floor): add SpecCard {id, sku_spec, item_name, grade, pack_size, case_count, unit, allowed_substitutes[], photo_checks[], source}: the spec every bid and delivery is checked against.
- [20:36] B (proposed): add SupplierTerms {supplier_id, min_order_value, delivery_fee, free_delivery_over, cutoff_time, delivery_days[], source}: input to the split-order optimizer.
- [20:36] B (proposed): add OrderPlan {id, need_id, mode cheapest_per_line|optimizer, allocations[{supplier_id, bid_id, lines[]}], subtotal, fees, total, savings_vs_baseline, explanation[], source}: output of close_auction, both modes stored for the judge toggle.
- [20:36] B (proposed): add ReceivingEvent {id, order_id, sku_spec, photo_url, expected_spec_id, result accepted|rejected, reasons[], credit_request_id?, checked_by photo_check|owner, at, source}: written by the receiving check (C vision or owner), feeds QualityRecord and D's three-way match.
- [20:36] B (proposed): add QualityRecord {supplier_id, deliveries, rejects, credits_requested, credits_captured, recalls_blocked, on_time_rate, updated_at}: derived per supplier from ReceivingEvents.
- [20:36] B (proposed): FloorEvent v2: kind becomes an enum (need_posted, bid_sealed, auction_closed, bid_rejected, claim_checked, verdict, order_placed, delivery_checked); add ref_table, supplier_id (optional), label. Every floor animation traces to ref_table/ref_id.
