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

## Run it locally

```bash
# once: install the CLI (official installer), then deps
curl -sSf https://install.spacetimedb.com | sh
cd market && npm ci && npm ci --prefix spacetimedb

# tests (rules + reducers, includes INVARIANT-1)
npm test

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

`spacetime call -s local tech-bazaar reset_demo` then `seed_demo` resets everything except agent identities and buyer screen sessions. The Market page has a Reset demo button that does the same.

## Python call path (Lane A)

```python
import sys; sys.path.insert(0, "market/scripts")
from stdb import Market

buyer = Market()                                   # one identity
buyer.call("post_need", id="need-1", buyer_id="joe", goal_id="goal-joe-gpu",
           delivery_window="by Friday", spend_limit=800, consent=True,
           auction_window_s=15, origin="SIM",
           items=[{"sku_spec": "gpu-rtx5070ti-retail", "condition": "new",
                   "variant": "retail", "quantity": 1, "unit": "each"}])
buyer.call("open_round", round_id="round-1", need_id="need-1", window_s=15)

seller = Market(token_file=".seller-a.token")      # keep the token: it is the seller's identity
seller.call("register_seller", seller_id="seller-a")
seller.call("set_floor", sku_spec="gpu-rtx5070ti-retail", floor=700)
seller.call("place_bid", id="bid-a", round_id="round-1", persona="Seller A",
            lines=[{"sku_spec": "gpu-rtx5070ti-retail", "offered_spec": "",
                    "offered_condition": "", "unit_price": 780, "quantity": 1}],
            stated_total=780, perks=[], claims=[], origin="SIM",
            source="https://example.com/listing")
print(seller.sql("SELECT * FROM my_bids"))         # a seller sees only its own bid until close
```

Pass every name in snake_case. SpacetimeDB's HTTP API wants top-level reducer args in camelCase but nested object fields in snake_case; `Market.call` converts the top level for you. `python3 market/scripts/post_goal.py` is a working example. Env: `SPACETIMEDB_HTTP` (default `http://127.0.0.1:3000`), `SPACETIMEDB_DB` (default `tech-bazaar`), `SPACETIMEDB_TOKEN_FILE`.

## Reducers

| Reducer | Who calls it | Notes |
|---|---|---|
| `register_seller(seller_id)` | a seller agent, once | binds that identity to the seller id; a buyer screen cannot register |
| `set_floor(sku_spec, floor)` | the seller | private; only the seller reads its floor |
| `open_buyer_session(buyer_id)` | the buyer screen | demo sign-in (SIM); a seller identity is refused |
| `post_need(...)`, `post_goal(...)` | Lane A buyer agent | goal starts ACTIVE, reserved 0 |
| `open_round(round_id, need_id, window_s)` | Lane A | schedules the auto close at the deadline |
| `place_bid(...)` | a registered seller | sealed; anti-snipe extends; below-floor bids are recorded as rejected and never rank |
| `close_round(round_id)` | anyone after the deadline, or the scheduler | ranks with `rules/scoring`; writes `round_result` |
| `attach_verdict(bid_id, verdict, rule_ids, origin)` | Lane D Shield | quarantine or block disqualifies |
| `attach_claim_check(bid_id, claim, check, evidence_url, origin)` | Lane C | `false` disqualifies; `verified` breaks ties |
| `create_mandate(...)` | Lane D | MOCK shape until Vidyut's Mandate lands |
| `record_approval(mandate_hash, method, approved_by)` | Lane D call core | second approval for a hash is refused and shown |
| `record_payment(mandate_hash, payment_ref, amount)` | Lane D | INVARIANT-1: refused without an approval for the same hash |
| `reset_demo()`, `seed_demo()` | demo operator | SIM data only |

Views clients subscribe to: `seller_needs` (redacted: items, window, deadline, never the spend limit or goal), `my_bids`, `my_goals`, `my_goal_items`, `my_notifications`.
