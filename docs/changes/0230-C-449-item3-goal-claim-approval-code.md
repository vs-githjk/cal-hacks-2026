# #449 item 3: claim_goal, set_goal_state, approval code check, referee reads

Reducers (market/spacetimedb): new `claim_goal(goalId)` and `set_goal_state(goalId, state, text)`, both referee only. `record_approval` gains a required string arg `code` (the word pair the call checked; for `voice_code` it must match the `approval_code` row of that mandate). `create_mandate` refuses a second live mandate for one deal; `record_payment` refuses an expired mandate. `post_goal` and `post_need` ignore `origin` from a buyer caller (the buyer profile's origin is used). `SIGNUP_MAX` is 300. Public floor events for sign-up, allowance set or raised and pairing lock or throttle carry an empty `refId`.

Views: new referee-only `agent_approvals` and `agent_payments`. No table changed.

Web bindings to regenerate before publishing (web/src/module_bindings): `record_approval_reducer.ts` (new `code` arg), new `claim_goal_reducer.ts` and `set_goal_state_reducer.ts`, new `agent_approvals_table.ts` and `agent_payments_table.ts`, and the shared `index.ts`, `types.ts`, `types/reducers.ts`. The `spacetime generate` command in market/README.md rewrites all of them.
