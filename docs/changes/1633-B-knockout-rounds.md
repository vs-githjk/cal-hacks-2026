# #336: sealed knockout rounds contract (Lane B)

For Lane D (demo/bridge.py) and the UI (web): best-and-final-offer knockout, up to 3 stages. Replaces other Lane B work; not extra. Implementation follows this note; fields and reducer shapes below are final for parallel build.

## `round` (new fields)
- `stage: u32` -- current stage, starts at 1.
- `maxStages: u32` -- default 3.
- `stageWindowS: u32` -- seconds per stage (same snipe rule as today: last 3s left adds 5s, at most twice per stage).

## `close_stage(roundId)` -- referee or round_timer
Runs today's checks (Shield, claim check, advocate veto, over cap, below floor) on every live offer in the stage. Writes one `round_result` row per seller for this stage:
- `stage: u32`
- `status: 'knocked_out' | 'advancing' | 'champion'`
- `reason: string` -- empty when advancing or champion

Knocked out this stage: every rule-breaker (veto, Shield block, CRS fail, fit fail, over cap, below floor) plus the single last-placed survivor among sellers who were not already knocked out by a rule.

- One survivor left after knockouts: that seller becomes `champion` immediately, and this closes the round (same as today's `close_round`; #240's `create_mandate` rank-1-of-closed-round rule is unchanged, now reading the `champion` row).
- Zero survivors left (every remaining seller ruled out together): the round closes with no deal and nothing is paid. No mandate is ever created for a `knocked_out` row.
- More than one survivor and `stage < maxStages`: round advances to `stage + 1`, deadline resets to `stageWindowS`, round stays `open`.
- More than one survivor and `stage == maxStages`: best offer among survivors wins (same ranking as today's `close_round`); that seller is `champion`, round closes.

One `floor_event` per knockout (`stock_sold_out`-style public label, seller id only, no price): e.g. `Seller knocked out (stage N)`.

## `place_bid` in stage `k > 1`
- Survivors only (a knocked-out seller's `place_bid` is refused, same style as today's role refusal).
- One offer per stage per seller. A second `place_bid` in the same stage from the same seller is refused ("already offered this stage").
- Must be strictly lower than that seller's own previous-stage offer, and at or above its floor, else refused. If a survivor places no offer in a stage, its previous offer stands unchanged into the knockout check.

## `my_standing` -- seller-only view, own rounds only
Returns, per round the seller has a live or past offer in: `stillIn: boolean`, `reason: string` (empty while still in), and the seller's own last offer (amount and line). Never another seller's price or standing.

## Not in this contract
- The demo/bridge.py call sequence for driving stages is Lane D's; this note only fixes the reducer and view shapes it calls against.
- UI (#343's exploded-PC build board) reads `round.stage`/`maxStages` and `round_result.status` per the shapes above; no UI-only fields needed.
