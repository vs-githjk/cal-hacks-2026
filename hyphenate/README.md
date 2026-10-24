# hyphenate/: the purchasing seat and the AP clerk seat (Lane D)

One line on the seats: **an IT buyer's purchasing seat and an accounts-payable clerk seat for a 40-person game studio's computer-gear buying (Pixel Forge Games, SIM), with limited access, a clean record of every call, and the sense to ask a person.**
Vidyut is the requester (same persona as the Tech Bazaar demo). The studio, its people, vendors, invoices and bank records are **SIM**. Price references are **MIRROR** (median asking price from the dated listings in `data/mirror/snapshots`). The bank record is shaped like a Stripe test record and is SIM unless a real test charge is wired in. No model makes or changes a control decision; everything runs offline.

```
python3 -m hyphenate.demo                     # the moment, narrated (add --json for structure)
python3 -m hyphenate.scenarios.run --heldout  # planted errors: dev and held-out, caught/missed (add --write to refresh RESULTS.md)
python3 -m pytest hyphenate -q                # 77 tests, under a second
python3 -m uvicorn hyphenate.api:app --port 8789
```

## What is in code (controls, not prompts)
| Area | File | Control |
|---|---|---|
| Ledger | `ledger.py` | Chart of accounts (1000 cash, 1200 prepaid deposits, 1300 vendor credits receivable, 1500 IT equipment, 2000 AP, 2100 accrued received-not-billed, 5900 price variance, 6100 bank fees). Integer cents. Entries balance to the cent, carry a reason and source refs, are immutable (fixed by reversal). A closed period refuses posting. Periods close in order. Vendor subledger ties to the GL. |
| Approval chain | `procurement.py`, `org.py` | Requester can never approve (checked before role, so the reason is the real one), nor their delegate. Department head: own department, up to $2,500. Over that, new vendor over $1,000, over budget (explicit controller override), a PO price more than 15 percent above or 40 percent below a fresh MIRROR reference (SKU spelling is normalized; the trust reason is recorded), or a strict vendor all route to the controller. A strict vendor always needs two independent signatures: department head and controller, and if the requester is a department head, another department's head fills that slot. The route is recomputed at approval time. The Hyphenate agents hold no approve permission. |
| Controller says no | `procurement.py` | `reject` then re-plan inside the controller's ceiling (cheaper allowed condition line, or fewer units down to `min_qty`), else drop and release the budget. Capped at 2 re-plans. The child PO needs approval again. |
| Binding to pay/ | `procurement.py`, `payables.py` | Final approval binds deal id, payee, currency and an amount ceiling (hash recorded). Payment builds a mandate and calls `pay.mandate.can_charge` with the approved PO's deal, amount and payee, then `mark_used`. An edited amount (hash mismatch), a swapped payee (payee mismatch even if re-hashed), a replay, or an amount over the ceiling is blocked. |
| Three-way match | `matching.py`, `payables.py` | PO vs invoice and claim vs receiving: quantity (cumulative, partial deliveries), price (materiality: the larger of $1 or 0.5 percent per line, zero for a strict vendor), condition, SKU, arithmetic, several invoice lines for one SKU are added together before any comparison, duplicates (same number ignoring case, punctuation and zeros; or same vendor, PO, lines and total within 60 days with no goods received since the earlier bill), remit-to vs verified vendor master, a false independent claim check. A mismatch holds the bill and writes a credit memo request. |
| Accruals | `procurement.py`, `payables.py` | Accepted goods accrue at PO price on receipt (Dr 1500, Cr 2100). The bill reverses the accrual and books AP; immaterial variance goes to 5900. Prepaid vendors draw down the deposit; rejected or never delivered prepaid goods become a vendor credit receivable (1300) cleared by a bank refund. |
| Sources that disagree | `trust.py` | Fixed ranking per question (cash: bank, ledger, seller; condition and quantity: receiving first; agreed price: the PO; remit account: verified vendor master; market price: MIRROR if under 14 days old). The reason, naming the source believed and the ones not, is written into the decision. |
| Time | `vendors.py` | Vendor risk is a pure function of dated history: a failed receiving check in the last 120 days (or two in a year) makes the vendor strict (zero price tolerance, controller signature as well as department head); one older failure is watch; after a year it is forgotten. A vendor with no completed order is new. A vendor bank change blocks every payment until a different person verifies it. |
| Audit | `audit.py` | Every decision: timestamp, kind, subject, outcome, machine codes, a sentence written at the time, actor (person, rule, data or system), rule id and text, evidence refs, parent decisions, hash chain. `explain(decision_id)` returns the record, its ancestors and the journal entries that cite it. Journal entries cite the decision that caused them. |
| Close | `payables.py` | Only the controller closes a period; every payment in it needs a bank record; the trial balance must balance. |
| Proof | `scenarios/`, `RESULTS.md` | 41 dev plus 11 held-out planted cases and 12 clean controls, and Lane C's 34 blind cases (RESULTS-blind.md), with answer keys. See RESULTS.md. |

## API (all under `/v1/hyphenate`)
State is one in-memory company. `POST /demo/reset?story=moment|empty` loads the seeded story (default `moment`) or a blank studio. Identity is a claimed id in this sandbox (in production it comes from SSO). The server clock decides when things happen; a client-supplied `at` is honoured only in demo-clock mode (`HYPHENATE_DEMO_CLOCK=1`, or after `POST /demo/reset`, which turns it on for scripted stories), because a far-future `at` would age out vendor strictness and MIRROR freshness. `GET /health` reports `clock_mode`. Time never goes backwards (409).
Every write returns `Outcome`: `{"ok": bool, "status": str, "decision_ids": [..], "decisions": [Decision..], "code"?: str, ...extra}`. A refused action is HTTP 200 with `ok:false`, a `code` and a decision that says why. 404 unknown id, 409 clock, 422 bad input, 413 body over 64 KB.

| Route | Purpose |
|---|---|
| `GET /health`, `GET /company`, `GET /vendors` | company, people (with `system:true` for the two agents), budgets and `budget_used`, policy; vendors with `events`, `bank_verified`, `risk{level,reasons,...}` |
| `GET /pos?status=`, `GET /pos/{id}` | PO view (below) plus `decisions`, `memos`, `invoices_detail` |
| `POST /requisitions` `{requester, vendor_id, lines[{sku,qty,price,condition?,allowed?,alternatives?[{condition,price}],min_qty?,serialized?}], justification?, at?}` | draft a PO and route it (the PO is charged to the requester's own department; a requester cannot pick another department's budget or approver, only the controller can) |
| `POST /pos/{id}/approve` `{by, override_budget?, note?}`; `/reject` `{by, reason, max_amount?}` | approval and the controller's no (response has `replan.child` or `replan.dropped`) |
| `POST /pos/{id}/receive` `{by, lines[{sku,qty,condition,serials[],ok?,reasons?}]}` | receiving check |
| `POST /pos/{id}/prepay`, `/close` | prepaid vendor payment; close an order short |
| `GET /invoices?status=`, `GET /invoices/{id}`, `POST /invoices` `{po_id, number, date, lines[{sku,qty,price,condition}], remit_to?, total?, claim?, supersedes?}` | intake and three-way match |
| `POST /invoices/{id}/pay` `{by?}` | release payment through the mandate guard |
| `GET /memos`, `POST /memos/{id}/issued` | credit memo requests |
| `POST /bank-records` `{id, kind: charge\|refund\|fee, amount, payee, ref, source}` | reconcile a bank or Stripe test record |
| `POST /vendors/{id}/bank-change` `{new_account, by, via?}`, `/bank-verify` `{by, method?}` | vendor bank details |
| `GET /ledger/accounts`, `/ledger/journal?ref=&period=`, `/ledger/trial-balance`; `POST /journal`, `POST /periods/{p}/close` `{by}` | books |
| `GET /audit?subject=&kind=&outcome=&limit=`, `/audit/{id}`, `/audit/{id}/explain?draft=`, `/audit/verify` | audit trail, explanation (draft only rephrases, numbers guarded), chain and invariant check |
| `GET /reconciliation` | per payment: ledger, bank, seller claim, MIRROR reference, which source is believed and why |
| `GET /results?heldout=` | runs the planted-error sets live and returns caught/missed |

Shapes (field names are exact):
- **PO view**: `id, requester, dept, vendor_id, status (pending_approval|approved|partially_received|received|closed|rejected|replanned|dropped), total, justification, created_at, committed, parent, replanned_to, replans, bound{deal_id,payee,currency,ceiling,approval_ids,hash}|null, route{needs[],two_person,flags[],notes[],evidence[],vendor_level}, approvals[{by,role,fills,at,note,override_budget}], invoices[], receipts[], paid, prepaid, lines[{sku,desc,qty,unit,condition,allowed[],serialized,accepted,rejected,billed,accepted_conditions[],reject_reasons[],min_qty,alternatives[]}]`. Money is integer cents everywhere.
- **Invoice**: `id, po_id, vendor_id, number, date, lines[{sku,qty,unit,condition}], total, computed, remit_to, claim, status (held|matched|matched_prepaid|paid|superseded|rejected_duplicate), findings[{code,sku,detail,credit,hold}] (only what needs a person), info[{code,sku,detail,credit,hold:false}] (booked as-is: variance inside tolerance, merged split lines), payable, match_decision, supersedes`.
- **Decision**: `id, at, kind, subject, outcome, codes[], reason, actor{kind,id}, rule{id,text}|null, evidence[{type,id,detail}], parents[], prev_hash, hash`.
- **Memo**: `id, vendor_id, po_id, invoice_id|null, amount, reasons[], status (requested|credited), requested_at, text`.
- **Journal entry**: `id, date, period, lines[{account,debit,credit,party}], reason, refs[], posted_at, posted_by, reverses`.
- **Explain**: `{decision, chain[Decision] (oldest first), journal_entries[], text}`.
- **Reconciliation row**: `payment, invoice, po, ledger, bank, seller_claim, mirror[{sku,po_unit,mirror,mirror_as_of}], agreed, believed, reason, origin`.

## The moment (3 lines)
1. Vidyut asks for 3 GPUs; Vidyut cannot approve the PO, the department head is over the limit, the controller says no with a $2,600 ceiling, and the system re-plans to 2 units inside it.
2. Receiving finds one unit open-box; the vendor's invoice bills 2 as new and asks to be paid to a different bank account: held, credit memo drafted, and `explain()` names the rule, the receiving record, the vendor's new strict level and every decision it rests on.
3. The vendor's bank details then change the day before payment: held until the controller verifies by call-back; the bank record is $5 off the ledger and the bank is believed, written down with why.

## Not done, said plainly
Sales tax, freight and multi-currency lines; OCR of invoices (invoices arrive structured); collusion between two real approvers; stock or fixed-asset depreciation; real Stripe wiring (`bank_record` takes the shape, nothing here calls Stripe); authentication (identities are claimed ids). Vendor events are seeded, not learned across years. The reviewer can find the same limits listed in RESULTS.md next to the numbers.
