# Hyphenate blind planted-error results (SIM)

Run 2026-10-24T07:01:38+00:00 UTC with `python3 -m hyphenate.scenarios.blind_run --write`, public API only, blank studio per case.
Cases: `hyphenate/scenarios/blind_cases.json`, frozen 2026-10-24T06:59Z and committed before any run (sha256 `c593d98d4083c960a4ad0601464d990b0c41cde6b19b174851c083cc262490f8`). Written by Lane C without reading hyphenate/*.py or the existing case files. No engine code was changed.

**Planted: 26 of 27 caught, 1 missed, 0 stopped before the planted step, 0 runner errors. Clean: 5 of 7 passed, 2 false flags, 0 runner errors.**

| case | planted | result | where | codes |
|---|---|---|---|---|
| b01 Short ship billed in full | yes | caught | step 3 (invoice): invoice held | qty_short |
| b02 Open-box received, billed as new | yes | caught | step 3 (invoice): invoice held | qty_short, rejected_goods_billed |
| b03 Price drift 4 percent over PO | yes | caught | step 3 (invoice): invoice held | price_variance |
| b04 Price drift just past materiality (0.6 percent) | yes | caught | step 3 (invoice): invoice held | price_variance |
| b05 Duplicate invoice, same number reformatted | yes | caught | step 4 (invoice): invoice rejected_duplicate | duplicate_invoice |
| b06 Duplicate invoice under a new number | yes | caught | step 4 (invoice): invoice held | possible_duplicate, qty_over_po, qty_short |
| b07 Split billing: two invoices for the same received units | yes | caught | step 4 (invoice): invoice held | possible_duplicate, qty_over_po, qty_short |
| b08 Split lines on one invoice exceed the PO | yes | caught | step 3 (invoice): invoice held | duplicate_line_sku, qty_over_po, qty_short |
| b09 Vendor bank change right before payment | yes | caught | step 5 (pay): denied | bank_unverified |
| b10 Bank change verified by the person who requested it | yes | caught | step 5 (bank_verify): denied | same_person_verified |
| b11 Remit-to differs from the verified vendor master | yes | caught | step 3 (invoice): invoice held | remit_to_mismatch |
| b12 Requester approves their own PO | yes | caught | step 1 (approve): denied | self_approval |
| b13 Department head approves above their $2,500 limit alone | yes | caught | step 2 (receive): denied | po_not_open |
| b14 Over budget with no controller override | yes | caught | step 1 (approve): denied | above_authority |
| b15 Posting into a closed period | yes | caught | step 1 (journal): denied | period_locked |
| b16 Credit memo, then the vendor re-bills the same error | yes | caught | step 3 (invoice): invoice held | qty_short, rejected_goods_billed |
| b17 Partial receipt, invoice for the whole order | yes | caught | step 3 (invoice): invoice held | qty_short |
| b18 Invoice total does not add up | yes | caught | step 3 (invoice): invoice held | arithmetic |
| b19 SKU swapped to a pricier model | yes | caught | step 3 (invoice): invoice held | sku_not_on_po |
| b20 Freight line not on the PO | yes | caught | step 3 (invoice): invoice held | sku_not_on_po |
| b21 Sales tax line not on the PO | yes | caught | step 3 (invoice): invoice held | sku_not_on_po |
| b22 Receiving failed (damaged), invoice billed in full | yes | caught | step 3 (invoice): invoice held | qty_short, rejected_goods_billed |
| b23 Same invoice paid twice | yes | caught | step 5 (pay): denied | already_paid |
| b24 PO priced far above the MIRROR market reference | yes | missed | - |  |
| b25 Invoice before anything was received | yes | caught | step 2 (invoice): invoice held | billed_before_receipt |
| b26 Closing a period with a payment that has no bank record | yes | caught | step 5 (close_period): blocked | unreconciled_cash |
| b27 Two-unit PO, one unit open-box, billed both as new | yes | caught | step 3 (invoice): invoice held | qty_short, rejected_goods_billed |
| k01 One GPU, clean all the way to payment | clean | clean_pass | - |  |
| k02 Immaterial 50 cent variance | clean | false_flag | step 3 (invoice): invoice matched | price_variance_immaterial |
| k03 Two partial deliveries, each billed after receipt | clean | false_flag | step 5 (invoice): invoice held | possible_duplicate |
| k04 Bank change verified by a different person, then paid | clean | clean_pass | - |  |
| k05 Open-box allowed and priced as open-box | clean | clean_pass | - |  |
| k06 GPU and PSU on one PO, both billed correctly | clean | clean_pass | - |  |
| k07 Same invoice number from two different vendors | clean | clean_pass | - |  |

## For Lane D (misses, false flags and anything that needs a look)
- b24 PO priced far above the MIRROR market reference: missed
- k02 Immaterial 50 cent variance: false_flag
- k03 Two partial deliveries, each billed after receipt: false_flag

## Notes
- README says money is integer cents everywhere, but the API reads line prices and journal amounts as dollars (124999 became $124,999.00). The cases follow the README; the runner divides by 100 on the way in.
- There is no human AP clerk in the studio; bank changes in the cases use Maria Hill (vendor admin).
- Planted cases count as caught only at or after the planted step; a refusal earlier means the planted error was never reached.

## Observations (written after the run, from the API responses; the verdicts above use the frozen rule unchanged)
- b24: missed. The $1,600.00 PO routed to the department head only: route flags and evidence were empty, so no MIRROR reference was consulted for 'rtx 5070 ti' in the blank studio (the README says a PO over 15 percent above a fresh MIRROR reference routes to the controller). Worth checking the SKU-to-reference lookup and freshness in the empty story.
- k02: false flag by the frozen rule only: the invoice was matched and paid; the finding was the informational price_variance_immaterial. Lane D may treat this as correct behavior; it is reported, not re-scored.
- k03: real false flag: after two partial deliveries, the second correct invoice (same lines and total as the first) was held as possible_duplicate and payment was refused. The duplicate rule (same vendor, PO, lines, total within 60 days) does not account for cumulative partial receipts.
