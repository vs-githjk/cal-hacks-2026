# market/ (Lane B)

The arena: SpacetimeDB holds every round, goal, bid and approval, and every screen and agent shares that one world. All market rules live in plain TypeScript in `rules/` (no SpacetimeDB imports), so the Convex fallback would call the same code.

**The Python bridge (`scripts/stdb.py`, SpacetimeDB's HTTP API) is the single point of failure; Convex is the fallback.** If the bridge or SpacetimeDB is down, agents cannot post needs or bids. The fallback keeps the same reducer names over Convex functions and the same `rules/`.

## Layout

| Path | What |
|---|---|
| `rules/` | sealing and anti-snipe, floor, redaction, scoring, approval and idempotency, fees, outcomes, split-order optimizer. Pure TS, vitest and fast-check. |
| `config.ts` | fee numbers (flat seller fee, PROPOSED). Nothing else hard-codes them. |
| `spacetimedb/src/schema.ts` | tables. Private: need, goal, bid, floors, mandate, approval, payment. Public: round, round_result, floor_event, persona, rejected_attempt. |
| `spacetimedb/src/market.ts` | reducer and view bodies (call `rules/`). |
| `spacetimedb/src/index.ts` | registers reducers and views. |
| `spacetimedb/src/market.test.ts` | reducer tests in-process, no server. The `INVARIANT-1` block is for Vidyut's review. |
| `scripts/stdb.py` | Python bridge for Lane A (stdlib only). |

## Run the tests (fresh clone, no server needed)

```bash
npm ci --prefix market && npm test --prefix market
```

`npm ci` installs `market/` and, through `postinstall`, `market/spacetimedb/`. The tests are the rules suite and the reducer suite (in-process SpacetimeDB harness, including `INVARIANT-1` and `SECURITY`). CI runs exactly this command.

## Run it locally

```bash
# once: install the CLI (official installer), then deps
curl -sSf https://install.spacetimedb.com | sh
cd market && npm ci

# start a local server (port 3000) in its own terminal
spacetime start --listen-addr 127.0.0.1:3000

# publish the module and load the demo (SIM)
spacetime publish -s local -p ./spacetimedb --yes=all tech-bazaar
spacetime call -s local tech-bazaar seed_demo

# regenerate web client bindings after any schema or reducer change
spacetime generate --lang typescript --out-dir ../web/src/module_bindings --module-path ./spacetimedb

# web (port 3100)
cd ../web && npm ci && npm run dev
```

`spacetime call -s local tech-bazaar reset_demo` then `seed_demo` resets everything except roles and pairing codes.

For a rehearsal, run or project the demo, not `npm run dev`: `npm run demo --prefix web` (`next build && next start -p 3100`) so the screen is a production build with no dev indicator or Insight badge.

## Who may call what (roles)

Every state-changing reducer checks the caller first (`requireRole` in `spacetimedb/src/market.ts`). Roles live in a private `role` table: **buyer** (bound to a buyer_id), **seller** (bound to a seller_id) or **referee** (the market service, Shield and the advocate relay). Only the module **owner**, the identity that published it, grants roles. The deadline scheduler runs as the module itself.

```bash
# once per database, as the owner (the spacetime CLI identity): creates agent tokens in .tokens/ (gitignored)
python3 market/scripts/setup_roles.py
# the buyer screen pairing code for Vidyut
spacetime sql -s local tech-bazaar "SELECT code FROM pair_code"
```

Open http://localhost:3100/buyer and enter that code. A seller identity can never pair.

## Python call path (Lane A)

```python
import sys; sys.path.insert(0, "market/scripts")
from stdb import Market

vidyut = Market(token_file=".tokens/buyer-vidyut.json")       # buyer role for vidyut
ref = Market(token_file=".tokens/referee.json")         # referee role
seller = Market(token_file=".tokens/seller-a.json")     # seller role for seller-a

vidyut.call("post_need", id="need-1", buyer_id="vidyut", goal_id="goal-vidyut-gpu",
         delivery_window="by Friday", spend_limit=800, consent=True,
         auction_window_s=15, origin="SIM",
         items=[{"sku_spec": "gpu-rtx5070ti-retail", "condition": "new",
                 "allowed_conditions": ["new"], "variant": "retail", "quantity": 1, "unit": "each"}])
ref.call("open_round", round_id="round-1", need_id="need-1", window_s=15)
seller.call("set_floor", sku_spec="gpu-rtx5070ti-retail", floor=700)              # any condition of this SKU
seller.call("set_floor_for_condition", sku_spec="gpu-rtx5070ti-retail", condition="open-box", floor=600)
seller.call("place_bid", id="bid-a", round_id="round-1", persona="Seller A",
            lines=[{"sku_spec": "gpu-rtx5070ti-retail", "offered_spec": "",
                    "offered_condition": "", "unit_price": 780, "quantity": 1}],
            stated_total=780, perks=[], claims=[], origin="SIM",
            source="https://example.com/listing")
print(seller.sql("SELECT * FROM my_bids"))              # a seller sees only its own bid until close
```

Pass every name in snake_case. SpacetimeDB's HTTP API wants top-level reducer args in camelCase but nested object fields in snake_case; `Market.call` converts the top level for you. Working examples: `scripts/post_goal.py` (Lane A's Goal shape) and `scripts/demo_round.py` (a whole SIM round, standing in for Lanes A, C and D, including refused calls). Env: `SPACETIMEDB_HTTP` (default `http://127.0.0.1:3000`), `SPACETIMEDB_DB` (default `tech-bazaar`), `SPACETIMEDB_SERVER` (CLI server name for setup_roles, default `local`).

## Reducers

| Reducer | Who may call it | Notes |
|---|---|---|
| `assign_role(identity, role, subject_id)` | owner | role is buyer, seller or referee |
| `pair_buyer_screen(buyer_id, code)` | a screen with no role, or a buyer | demo sign-in (SIM); a seller or referee is refused. A wrong code does not throw (so the count sticks) and shows in `my_pair_attempts`; 5 wrong codes lock the code, and 5 lock the caller across every code; the code never appears in a message |
| `issue_build_approval_code(mandate_hash, buyer_id, amount, payee, expiry_minutes, code, origin)` | referee | the word pair for the ONE call that approves a whole build, shown on that buyer's own `/buyer` card (`my_pending_approvals`, `mandate_id` = `whole build`). Keyed by the aggregate mandate hash (the build makes its mandates after the call), so no mandate row is needed; `expiry_minutes` 1 to 10; a new one retires the buyer's earlier build code; refuses a hash that is a real mandate (use `issue_approval_code`), an unknown buyer, an empty code or a zero amount |
| `clear_build_approval_code(mandate_hash)` | referee | takes that build code off the buyer's screen when the call ends (approved, denied or crashed); the row stays so telemetry still counts the call; a no-op when there is none |
| `reissue_pair_code(buyer_id)` | owner | fresh code, unlocked, counter reset |
| `set_floor(sku_spec, floor)` | seller | a floor for every condition of that SKU (unchanged call; the Lane D bridge uses it); private |
| `set_floor_for_condition(sku_spec, condition, floor)` | seller | a floor for one (seller, sku_spec, condition); it wins over `set_floor`; private |
| `post_need(...)`, `post_goal(...)` | buyer, for its own buyer_id | goal follows Lane A's Goal contract; starts ACTIVE, reserved 0. Each need item carries `allowed_conditions` (empty means only its `condition`) #449 item 3: for a buyer caller the server sets `origin` from the buyer's profile (else SIM) and ignores the argument; the referee keeps passing it |
| `open_round(round_id, need_id, window_s)` | referee | schedules the auto close at the deadline |
| `place_bid(...)` | seller, as its own seller_id | sealed; anti-snipe extends. Lines are alternatives per SKU, never summed; a line's quantity is its stock (qty_available) and must be above 0. At close the cheapest allowed line with enough stock is picked, priced for the need quantity. Any line below its floor (exact condition first, else the any-condition floor) rejects the whole bid (recorded, never ranks); a line with neither floor is just not eligible |
| `close_round(round_id)` | referee after the deadline (the scheduler closes it anyway) | ranks with `rules/scoring`; writes `round_result`. A bid's lines for one SKU are alternatives: the cheapest line whose condition is in the need item's `allowed_conditions` (empty means only `condition`) ranks, never the sum. A bid over `need.spend_limit` is out with `over_cap` (the cap itself is never shown). The score is quality-adjusted landed price (`QUALITY` in `config.ts`, PROPOSED: open-box +4 percent, refurbished +8, used +15, no 30-day-returns perk +2); `landed` stays the plain price |
| `attach_verdict(bid_id, verdict, rule_ids, origin)` | referee (Shield) | quarantine or block disqualifies |
| `attach_claim_check(bid_id, claim, check, evidence_url, origin)` | referee (claim check relay) | `false` disqualifies; `verified` breaks ties |
| `attach_advocate_card(bid_id, recommendation, rule_id, text, source_url, origin)` | referee (advocate relay) | recommendation is `buy`, `caution` or `veto`. A veto must cite `source_url` and disqualifies the bid in the round result (rule, text and source in the reason); it writes an `advocate_card` floor event (rule id only, no seller, text or price) and a `veto` line on the buyer's feed. Refused once the round is closed |
| `create_mandate(...)` | the mandate's buyer, or the referee | MOCK shape until the Mandate contract is wired in. Inside the buyer's allowance it auto-approves (method `allowance`) with a receipt; otherwise the deal waits for the call. `requested_by` names an IT seat that asked for it #449 item 3: a second live mandate for one deal (not expired, not paid, not denied) is refused |
| `record_approval(mandate_hash, method, approved_by, voice_approval_id, code)` | the referee relaying that buyer's call | approved_by must equal the mandate's buyer and must not be the requester; a second approval is refused and shown. #449 item 3: for `voice_code` the `code` must equal the word pair issued for that mandate (`issue_approval_code`; a whole-build call has the referee issue the same code for each mandate it makes), case and spacing ignored. A wrong code throws and counts a failure on the row, 3 failures lock it, and a locked row always throws (the throw rolls the reducer back, so on a real server the count itself is not kept; nothing is approved either way). `allowance` ignores the code |
| `claim_goal(goal_id)` | referee | #449 item 3: first writer wins. An ACTIVE goal becomes HUNTING (and leaves `agent_open_goals`, so every agent's poll); any other state throws `goal already claimed or closed`. The referee may still post the need of a HUNTING goal |
| `set_goal_state(goal_id, state, text)` | referee | #449 item 3: state is HUNTING, HOLD_FOR_CALL, DONE, EXPIRED, PAUSED or FAILED. A closed goal (DONE, EXPIRED, FAILED) never changes again. Writes one `state` notification for the buyer and goal (text cut to 200 characters; a push for a closing state), which `/buyer` shows on the goal card |
| `record_payment(mandate_hash, payment_ref, amount, mode)` | referee | INVARIANT-1: refused without an approval for the same hash, and refused once the mandate has expired (#449 item 3). `mode` is `sim` (our stub; label "SIM stub, no money moved", origin SIM) or `stripe_test` (Stripe's test API; label "Stripe test mode", origin LIVE) |
| `record_receiving(id, order_id, sku_spec, photo_url, expected_spec_id, result, reasons, checked_by, origin)` | the deal's buyer | needs a paid deal; a clean check raises the allowance one step (once per deal); a failed one opens a credit request |
| `reset_demo()`, `seed_demo()` | owner or referee | SIM data only; roles survive a reset |

The allowance ladder (`rules/allowance.ts`, amounts PROPOSED in `config.ts`) follows D's Allowance contract: it starts at $0, so a new buyer's first buy always calls.

Views clients subscribe to: `my_role`, `my_allowance`, `seller_needs` (redacted: items, window, deadline, never the spend limit or goal), `my_bids`, `my_goals`, `my_goal_items`, `my_notifications`. Referee-only reads for the agents: `agent_buyer_contact`, `agent_open_goals`, `agent_goal_items`, and (#449 item 3) `agent_approvals` and `agent_payments`, which show approval and payment rows to the referee only and nothing to anyone else.
