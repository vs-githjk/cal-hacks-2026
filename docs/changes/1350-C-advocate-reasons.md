# 13:50 Lane C: two new spoken advocate reasons (#291, PR #287)

Touches Lane A's `agents/advocate/checks.py` CALL_SUMMARIES and Lane D's `pay/reasons.py` SUMMARIES (kept in sync, tested):

- `advocate.recall_partial`: "A CPSC recall names a similar model, so check the exact model". A recall that shares the brand and a model number but not the full model (a 4070 Ti recall against a 4070 Super bid) is now a caution with the recall link, never a veto.
- `advocate.unverified`: "Some checks could not run". Replaces "No problems found in the checks" on a buy card when a price or recall lookup was unverified, because that line is spoken on the call.

Recall entries passed to `checks.advise` may now carry `bid_ids` (the veto applies only to those bids), `partial`, and `text` (the recall title and date). Entries without these fields behave as before.

`data.baselines.baseline` has a new status `thin`: two data owners but fewer than 2 observations from one of them. It gives no median, like `one_source`.
