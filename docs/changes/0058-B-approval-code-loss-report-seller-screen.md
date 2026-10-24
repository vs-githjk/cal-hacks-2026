B (#20): new market pieces for b5 to b7. Market-internal tables and reducers; the LossReport contract is unchanged (its fields map 1:1).
- issue_approval_code(mandateHash, code), referee only: Lane D's approval relay stores the word pair it issued (pay/approval.py svc.issue) for a mandate that needs the call. Only that mandate's buyer sees it, in my_pending_approvals (with amount, payee, expiry, failures, locked).
- approve_typed(mandateHash, code), the mandate's own buyer only: the labelled typed fallback. A match records the same approval row the call would (method typed_code, same mandate hash); case and spacing are ignored; 5 misses lock it; the code never appears in a message.
- record_loss_report(id, roundId, sellerId, won, gapBand, reason, sourceUrl, strategyDiff[{key,from,to}], whatToChange, whatToChangeOrigin, origin), referee only. gapBand and reason must be from contracts/LossReport.schema.json. Each seller sees only its own, in my_loss_reports.
- seller_screen role: pair_seller_screen(sellerId, code) with a code the owner issues by reissue_seller_screen_code(sellerId). Read only; it can never bid or pair as a buyer.
- seller_needs gains ceilingBand ("$500 to $1,000", never the number) and origin.
Asks: Lane D call issue_approval_code right after svc.issue; Lane A call record_loss_report after each round (with the strategy diff and Claude's line when present).
