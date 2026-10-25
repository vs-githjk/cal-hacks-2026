The whole-build approval code now reaches the buyer's /buyer card (rehearsal 22:17: the code was only printed to the console, /buyer said "Nothing is waiting for you", the call denied).

Market contract (market/spacetimedb, publish needed; appended columns migrate in place, connected clients reconnect):
- `approval_code` gains `amount`, `payee`, `expiry`, `origin` (all defaulted). A row with `expiry` after the epoch and no mandate row is a whole-build code.
- New referee-only reducers `issue_build_approval_code(mandate_hash, buyer_id, amount, payee, expiry_minutes, code, origin)` and `clear_build_approval_code(mandate_hash)`.
- `my_pending_approvals` also returns a live build code (`mandate_id` = `whole build`), to the buyer it was issued for and nobody else. Same columns, same /buyer card.
- web/src/module_bindings regenerated (additions only).

demo/build.py: before dialing, the runner issues the code (keyed by the aggregate mandate hash it already computes); in a finally it clears it. A market without the reducer, a refusal, or approve_typed in the module leaves the code on the console only, with one line saying so. The code is never in the BuildView, so `GET /v1/build` and the hosted copy cannot carry it. Affects Lane A (/buyer) and anyone republishing the market.
