# Hyphenate results (SIM), run 2026-10-23

All numbers below come from `python3 -m hyphenate.scenarios.run --heldout --write`. The company, vendors, invoices and bank records are SIM; MIRROR price references come from `data/mirror/snapshots`; no model makes any control decision. The author wrote both sets: the held-out set was written after the dev set was frozen and was run once before this file was written (see the sha256 below), so it is a fair but not an independent test.

## Summary

| set | planted caught | clean controls with a false flag | decisions written | decisions explainable |
|---|---|---|---|---|
| dev (47 cases) | 39/39 | 0/8 | 364 | 364 |
| held-out (14 cases) | 11/11 | 0/3 | 118 | 118 |

Held-out history, stated plainly: the set was committed (sha256 `a1957e37c2d3...`) and run once before RESULTS.md existed: 10/11 planted, 0/3 false flags. The one non-catch, H06, was a crash from my own scripting mistake (the case moved the clock backwards: a bank change at 08:00 after an invoice at 09:00), not an engine miss. I fixed only that timestamp in the case (the key and the engine were not touched) and re-ran: the numbers in the table are from that corrected file.

Changes after the PR #40 review: three faults the reviewer found were fixed in the engine and added to the dev set as D37 (invoice splits one SKU over two lines), D38 (requester charges another department) and D39 (strict vendor with a department-head requester). D10 now uses an art-department requester because cross-department requests are refused. The held-out cases were not edited and their results did not change.

dev_cases.py sha256 `4edec08509953b1d3bc1034e1678c310f6f953c3c192ebddd666f324da2ee274`
heldout_cases.py sha256 `39cb210661f7ba1ad47ddbdc8a51769e6ccb0146bf5d3019b69cd6f1501f4eec`

## By planted fault

| fault | caught |
|---|---|
| above_authority | 1/1 |
| agent_overreach | 1/1 |
| arithmetic | 1/1 |
| bank_ledger_disagree | 1/1 |
| bank_wrong_payee | 1/1 |
| billed_before_receipt | 1/1 |
| changed_bank_details | 1/1 |
| changed_bank_details_recovery | 1/1 |
| claim_false | 1/1 |
| controller_no_drop | 1/1 |
| controller_no_replan | 2/2 |
| cross_department_charge | 1/1 |
| delegate_approval | 1/1 |
| duplicate_invoice | 2/2 |
| duplicate_serial | 1/1 |
| duplicate_signature | 1/1 |
| mandate_amount_tamper | 1/1 |
| mandate_payee_swap | 1/1 |
| new_vendor_large_po | 1/1 |
| over_billing | 1/1 |
| over_budget | 1/1 |
| over_delivery | 1/1 |
| payer_not_independent | 1/1 |
| period_locked_posting | 1/1 |
| prepaid_short_delivery | 1/1 |
| prepaid_wrong_condition | 1/1 |
| price_above_market | 1/1 |
| price_below_market | 1/1 |
| price_drift | 2/2 |
| receiver_not_independent | 1/1 |
| remit_to_changed | 1/1 |
| requester_self_approval | 2/2 |
| same_person_verifies | 1/1 |
| serial_missing | 1/1 |
| short_shipment | 2/2 |
| split_invoice_lines | 1/1 |
| strict_vendor_peer_signature | 1/1 |
| unapproved_po | 1/1 |
| unbalanced_entry | 1/1 |
| unreconciled_close | 1/1 |
| vendor_history_strict | 1/1 |
| wrong_condition | 1/1 |
| wrong_condition_rejected | 2/2 |
| wrong_sku_received | 1/1 |

## Misses and false positives (reported as found)

- no planted case missed
- no clean control flagged

## What these numbers do not show

- One author wrote the engine, the dev set and the held-out set from the same list of fault classes; a held-out variant is a different number, boundary, order or combination, not a fault class the engine was never designed for. Treat 100 percent as 'the controls do what they say', not 'finds every error'.
- The runner can say MISSED: `hyphenate/tests/test_scenarios.py` switches off the three-way match, the mandate guard and the period lock one at a time and watches the matching cases stop being caught.
- Not covered: sales tax, freight and multi-currency lines, OCR of invoices, collusion between two real approvers, depreciation, real Stripe or bank feeds, authentication.
- A clean control counts as a false positive on any denied, hold, blocked, exception, rejected, dropped or failed decision; only 11 controls exist, so a 0 percent false-flag rate has wide error bars.

## Every case

### Dev

| id | fault | planted | verdict | detail |
|---|---|---|---|---|
| D01 | short_shipment | yes | caught | ok |
| D02 | wrong_condition | yes | caught | ok |
| D03 | wrong_condition_rejected | yes | caught | ok |
| D04 | price_drift | yes | caught | ok |
| D05 | duplicate_invoice | yes | caught | ok |
| D06 | changed_bank_details | yes | caught | ok |
| D07 | remit_to_changed | yes | caught | ok |
| D08 | requester_self_approval | yes | caught | ok |
| D09 | delegate_approval | yes | caught | ok |
| D10 | over_budget | yes | caught | ok |
| D11 | above_authority | yes | caught | ok |
| D12 | controller_no_replan | yes | caught | ok |
| D13 | controller_no_drop | yes | caught | ok |
| D14 | billed_before_receipt | yes | caught | ok |
| D15 | wrong_sku_received | yes | caught | ok |
| D16 | duplicate_serial | yes | caught | ok |
| D17 | serial_missing | yes | caught | ok |
| D18 | arithmetic | yes | caught | ok |
| D19 | vendor_history_strict | yes | caught | ok |
| D20 | new_vendor_large_po | yes | caught | ok |
| D21 | mandate_amount_tamper | yes | caught | ok |
| D22 | mandate_payee_swap | yes | caught | ok |
| D23 | bank_ledger_disagree | yes | caught | ok |
| D24 | unapproved_po | yes | caught | ok |
| D25 | period_locked_posting | yes | caught | ok |
| D26 | over_billing | yes | caught | ok |
| D27 | price_above_market | yes | caught | ok |
| D28 | unbalanced_entry | yes | caught | ok |
| D29 | agent_overreach | yes | caught | ok |
| D30 | same_person_verifies | yes | caught | ok |
| D31 | payer_not_independent | yes | caught | ok |
| D32 | unreconciled_close | yes | caught | ok |
| D33 | claim_false | yes | caught | ok |
| D34 | bank_wrong_payee | yes | caught | ok |
| D35 | prepaid_short_delivery | yes | caught | ok |
| D36 | receiver_not_independent | yes | caught | ok |
| D37 | split_invoice_lines | yes | caught | ok |
| D38 | cross_department_charge | yes | caught | ok |
| D39 | strict_vendor_peer_signature | yes | caught | ok |
| C01 | clean_control | control | clean_ok | ok |
| C02 | clean_control | control | clean_ok | ok |
| C03 | clean_control | control | clean_ok | ok |
| C04 | clean_control | control | clean_ok | ok |
| C05 | clean_control | control | clean_ok | ok |
| C06 | clean_control | control | clean_ok | ok |
| C07 | clean_control | control | clean_ok | ok |
| C08 | clean_control | control | clean_ok | ok |

### Held-out

| id | fault | planted | verdict | detail |
|---|---|---|---|---|
| H01 | short_shipment | yes | caught | ok |
| H02 | wrong_condition_rejected | yes | caught | ok |
| H03 | price_drift | yes | caught | ok |
| H04 | duplicate_invoice | yes | caught | ok |
| H05 | requester_self_approval | yes | caught | ok |
| H06 | changed_bank_details_recovery | yes | caught | ok |
| H07 | over_delivery | yes | caught | ok |
| H08 | prepaid_wrong_condition | yes | caught | ok |
| H09 | price_below_market | yes | caught | ok |
| H10 | controller_no_replan | yes | caught | ok |
| H11 | duplicate_signature | yes | caught | ok |
| HC1 | clean_control | control | clean_ok | ok |
| HC2 | clean_control | control | clean_ok | ok |
| HC3 | clean_control | control | clean_ok | ok |
