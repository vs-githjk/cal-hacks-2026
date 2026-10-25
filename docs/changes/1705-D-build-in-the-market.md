# 17:05 Lane D #345 phase 1: a full build in the market, the BuildView function, one call

For Vedant (#343, the board), Abhinav (#344, the planner) and Anoop (#342). Code: `demo/build.py`. Run: `python3 demo/build.py --dry-run`.

## What the board reads
- `demo/out/build-view.json` is rewritten at every step of a run. `demo/out/build-view.steps.jsonl` keeps one BuildView per line, in order (a replay).
- `build_view(market_rows, plan_events, checks)` in `demo/build.py` is pure. The board can mirror it in TypeScript; its tests (`demo/tests/test_build_view.py`) are the spec.
  - A part is `owned` when its goal item has `skippedOwnedPartId`; `planned` with no round; `bidding` while its round is open; `locked` when the closed round has an eligible rank 1; `replanned` when the part has a later need and an eligible rank 1; `failed` when the closed round has no eligible rank 1.
  - An eligible rank 1 is the market's rank 1 whose reasons do not start with `held back`, whose seller joined the market (`data/mirror/not_partners.py`) and whose landed price is a whole number of cents. A part is never `locked` on anything else.
  - `spent` is the sum of locked parts' landed prices. `origin` of the build is its weakest part's label (SIM, then MIRROR, then LIVE).
  - A part's later need replaces the earlier one (`needId` and `roundId` are the latest). Need ids are `need-<goalId>-<part>` and `need-<goalId>-<part>-2` for a re-plan.

## Goal type
The goal is posted as `build_by_date`: the market's `GOAL_TYPES` and the enum of `contracts/Goal.schema.json` have no `build` (the 1650 note and the sample say `build`; read it as `build_by_date`).

## Keys added to the sample's shape (the board ignores keys it does not know)
- `parts[].origin` and `events[].origin`: the label the doc's Labels section asks for (the sample left them out).
- `parts[].champion.liveCheck`: `{state, price, fetchedAt, origin, quoted}` from the Bright Data re-check (`state` is ok, price_changed, out_of_stock, stock_unknown, slow, empty, not_configured). Only a MIRROR champion on a real listing is checked; a SIM champion has no `liveCheck`.
- `approval.method` (`voice_code` or `allowance`) and `approval.reason` (why a build was not called or not paid).
- `approval.mandates[]` also has `part`.

## Two things that differ from the sample
1. **One mandate per part, not per seller.** `create_mandate` is for one deal: the rank 1 bid of one closed round, the winning seller as payee, that bid's landed price as the amount (#191, #240). A seller that wins two parts gets two mandates. `approval.sellers` still counts sellers, and the one call covers all the mandates. `approval.mandates` has one entry per mandate: `{sellerId, amount, mandateHash, part}`.
2. **Central Computers cannot be a champion.** The sample locks the GPU on Central Computers, but that store never joined (#333): its bid is for comparison only and never gets a mandate. `build.py` never bids it, and a rank 1 from it makes the part `failed`.

## Events
- `plan`, `round_open`, `knockout`, `locked`, `call`, `approved`, `denied` and `receipt` are written by the driver from the market's rows. `clash` and `replan` come from the planner through `plan_events`.
- The Bright Data line per part uses `kind: "locked"` with `parts: [part]` ("GPU: price checked live 3 s ago via Bright Data: $1,299.99 (LIVE; quoted $1,299.99)", or "GPU: Bright Data: live price not read (too slow); the quoted MIRROR price stays: $1,299.99 (dated listing of 2026-10-24)"). There is no `price_check` kind in the closed list.
- A failed part or a stopped build writes one `denied` event ending "Nothing was paid."

## The call and the money order
- Above the allowance the build gets ONE Cartesia call: "Your whole build, 6 parts from 3 sellers, for <amount in words>". `pay/callscript.py` takes `{"parts": n, "sellers": m}` beside the amount (our own counts, never seller text).
- The call is judged on an aggregate mandate kept in Python (deal `build-<goalId>`, amount = the total). **No market mandate exists before the call approves**, because the market approves a mandate under the per-purchase limit by itself and a build of cheap parts would be paid without the call.
- After the call: the build sets the buyer's per-purchase limit to $0 (referee `set_allowance`, the period limit and period unchanged), makes one `create_mandate` per part's rank 1, records one `record_approval` (`voice_code`, the call's VoiceApproval id) on each, and restores the limit in a `finally`. At $0 the market's own `decide()` says "call" for every mandate, so none is auto-approved with method `allowance` and an empty id (a later `record_approval` on an already approved mandate is only logged as rejected, never thrown). If the restore fails the limit stays at $0, so every buy calls (fail closed) and the run says so. The ladder step shown is recomputed by `set_allowance` from the restored numbers.
- Before any payment the build reads the approvals back as the buyer through the `my_deals` view (`r[0]` mandate hash, `r[8]` approval method, `r[9]` VoiceApproval id; the referee cannot read the private tables), else, fail closed on the id, the public `floor_event` labels "Approved by voice code" / "Approved within the allowance" (method only). A mandate without a `voice_code` row carrying the call's id, or without an `allowance` row inside the allowance, denies the build visibly, calls `deny_approval` on each mandate, and pays nothing. A build whose approvals cannot be read back at all pays nothing. No Stripe TEST charge is made before every approval is confirmed.
- The buyer's allowance is read once, as the buyer, through the `my_allowance` view, before any call or mandate. That row decides call or no call (its real spent this period counts), and it is what the limit is restored to, so a limit the buyer tightened stays tightened. There is no fallback to the plan's numbers: an allowance that cannot be read denies the build before any call.
- A hard kill (SIGKILL, a power cut) between the zero and the restore leaves the per-purchase limit at $0. That fails closed (every buy calls). The next `python3 demo/build.py` run sets the plan's allowance again in its goal step; by hand: `spacetime call -s local tech-bazaar set_allowance '"vidyut"' 250 500 '"month"'` (buyer id, per purchase, per period, period). Use the referee call: a buyer can only lower their own limit.
- A champion needs the market's rank 1 in a round the market reports closed, with `round_result.status` of `''` or `champion` (#363): a stage leader (`advancing`) or a knocked-out bid is never mandated.
- Inside the allowance: no call; the market approves each mandate itself (method `allowance`); `record_payment` per part.
- Phase 1 limitation: `issue_approval_code` needs a market mandate, so the call's code is not shown on /buyer for a build; the run prints it on the console (the bridge does the same when /buyer cannot show it).
- A receipt per part is the market's `record_payment` row plus a `receipt` event: "SIM payment confirmed for deal <id>: $x.xx, reference ch_..., mandate <12 hex>." (the wording of `agents/buyer/checkout.format_settlement_result`). The ASI:One message and the Gmail connector are the buyer agent's (phase 2).

## Phase 2 needs
- Live wiring: the planner's `plan()` before the rounds (`build.plan_from_planner` reads its output) and `resolve()` after them (its knockouts and re-plan become `plan_events`; a re-plan needs a second need and round for the part, ids as above).
- The knockout stages from #336, and parallel pacing for six rounds (phase 1 runs the rounds one after another).
- `checks` from `data.fit_checker.build_check` (Anoop's #342), a fresh one after each swap.
- A market way to show a build's call code on /buyer.
