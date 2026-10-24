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

## Who may call what (roles)

Every state-changing reducer checks the caller first (`requireRole` in `spacetimedb/src/market.ts`). Roles live in a private `role` table: **buyer** (bound to a buyer_id), **seller** (bound to a seller_id) or **referee** (the market service, Shield and the advocate relay). Only the module **owner**, the identity that published it, grants roles. The deadline scheduler runs as the module itself.

```bash
# once per database, as the owner (the spacetime CLI identity): creates agent tokens in .tokens/ (gitignored)
python3 market/scripts/setup_roles.py
# the buyer screen pairing code for Joe (demo persona, SIM)
spacetime sql -s local tech-bazaar "SELECT code FROM pair_code"
```

Open http://localhost:3100/buyer and enter that code. A seller identity can never pair.

## Python call path (Lane A)

```python
import sys; sys.path.insert(0, "market/scripts")
from stdb import Market

joe = Market(token_file=".tokens/buyer-joe.json")       # buyer role for joe
ref = Market(token_file=".tokens/referee.json")         # referee role
seller = Market(token_file=".tokens/seller-a.json")     # seller role for seller-a

joe.call("post_need", id="need-1", buyer_id="joe", goal_id="goal-joe-gpu",
         delivery_window="by Friday", spend_limit=800, consent=True,
         auction_window_s=15, origin="SIM",
         items=[{"sku_spec": "gpu-rtx5070ti-retail", "condition": "new",
                 "allowed_conditions": ["new"], "variant": "retail", "quantity": 1, "unit": "each"}])
ref.call("open_round", round_id="round-1", need_id="need-1", window_s=15)
seller.call("set_floor", sku_spec="gpu-rtx5070ti-retail", condition="new", floor=700)   # one floor per condition
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
| `reissue_pair_code(buyer_id)` | owner | fresh code, unlocked, counter reset |
| `set_floor(sku_spec, condition, floor)` | seller | one floor per (seller, sku_spec, condition); private, only the seller reads it |
| `post_need(...)`, `post_goal(...)` | buyer, for its own buyer_id | goal follows Lane A's Goal contract; starts ACTIVE, reserved 0. Each need item carries `allowed_conditions` (empty means only its `condition`) |
| `open_round(round_id, need_id, window_s)` | referee | schedules the auto close at the deadline |
| `place_bid(...)` | seller, as its own seller_id | sealed; anti-snipe extends. Lines are alternatives per SKU, never summed; a line's quantity is its stock (qty_available) and must be above 0. At close the cheapest allowed line with enough stock is picked, priced for the need quantity. Any line below the floor for its condition rejects the whole bid (recorded, never ranks); a line with no floor for its condition is just not eligible |
| `close_round(round_id)` | referee after the deadline (the scheduler closes it anyway) | ranks with `rules/scoring`; writes `round_result`. A bid's lines for one SKU are alternatives: the cheapest line whose condition is in the need item's `allowed_conditions` (empty means only `condition`) ranks, never the sum. A bid over `need.spend_limit` is out with `over_cap` (the cap itself is never shown). The score is quality-adjusted landed price (`QUALITY` in `config.ts`, PROPOSED: open-box +4 percent, refurbished +8, used +15, no 30-day-returns perk +2); `landed` stays the plain price |
| `attach_verdict(bid_id, verdict, rule_ids, origin)` | referee (Shield) | quarantine or block disqualifies |
| `attach_claim_check(bid_id, claim, check, evidence_url, origin)` | referee (claim check relay) | `false` disqualifies; `verified` breaks ties |
| `attach_advocate_card(bid_id, recommendation, rule_id, text, source_url, origin)` | referee (advocate relay) | recommendation is `buy`, `caution` or `veto`. A veto must cite `source_url` and disqualifies the bid in the round result (rule, text and source in the reason); it writes an `advocate_card` floor event (rule id only, no seller, text or price) and a `veto` line on the buyer's feed. Refused once the round is closed |
| `create_mandate(...)` | the mandate's buyer, or the referee | MOCK shape until the Mandate contract is wired in. Inside the buyer's allowance it auto-approves (method `allowance`) with a receipt; otherwise the deal waits for the call. `requested_by` names an IT seat that asked for it |
| `record_approval(mandate_hash, method, approved_by)` | the mandate's buyer, or the referee relaying that buyer's code | approved_by must equal the mandate's buyer and must not be the requester; a second approval is refused and shown |
| `record_payment(mandate_hash, payment_ref, amount, mode)` | referee | INVARIANT-1: refused without an approval for the same hash. `mode` is `sim` (our stub; label "SIM stub, no money moved", origin SIM) or `stripe_test` (Stripe's test API; label "Stripe test mode", origin LIVE) |
| `record_receiving(id, order_id, sku_spec, photo_url, expected_spec_id, result, reasons, checked_by, origin)` | the deal's buyer | needs a paid deal; a clean check raises the allowance one step (once per deal); a failed one opens a credit request |
| `reset_demo()`, `seed_demo()` | owner or referee | SIM data only; roles survive a reset |

The allowance ladder (`rules/allowance.ts`, amounts PROPOSED in `config.ts`) follows D's Allowance contract: it starts at $0, so a new buyer's first buy always calls.

Views clients subscribe to: `my_role`, `my_allowance`, `seller_needs` (redacted: items, window, deadline, never the spend limit or goal), `my_bids`, `my_goals`, `my_goal_items`, `my_notifications`.
