# 17:35 Lane D to Lane B: a `require_call` flag on create_mandate (proposal, nothing changed in market/)

For Vedant (Lane B). Not needed for #345 phase 1; it would let Lane D drop a workaround.

## The problem
`create_mandate` approves a mandate by itself when `decide(allowance, amount)` says `auto` (amount at or under the per-purchase limit and inside the period limit): it inserts an `approval` row with method `allowance` and an empty VoiceApproval id, and spends the allowance. A later `record_approval(voice_code, id)` on that mandate is only logged as `rejected()`; it does not throw.

A build is one call for several mandates. Each part is its own mandate, so a part at or under the buyer's per-purchase limit is auto-approved even when the whole build needed the call: the call's approval never reaches it, and the allowance is charged.

## What Lane D does today (demo/build.py, no market change)
After the call approves, set the referee allowance's `per_purchase_limit` to 0 (`decide()` returns "call" at $0), create the mandates, record the voice approvals, and restore the limit in a `finally`. Then read the approvals back and deny the build if any mandate lacks a `voice_code` row with the call's id. It works, but it briefly changes the buyer's allowance (and `set_allowance` recomputes the ladder step).

## Proposal
`create_mandate(..., require_call: bool = false)`, referee only. When true, `decide()` is skipped: the mandate is never auto-approved, whatever the allowance says, and the `mandate_created` floor event and the notification say a call is needed. Default false keeps every current caller unchanged.

Optionally, `record_approval` on a mandate that already has an approval could throw instead of only logging `rejected()` when the method differs (a `voice_code` approval over an `allowance` row), so a caller sees the mismatch at once.

When it lands, `_mandates_zeroed` in `demo/build.py` becomes a plain `create_mandate(..., require_call=True)` and the allowance is never touched.
