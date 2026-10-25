# 16:50 Lane D: data shape for the full-build board (#343, #344, #345)

For Vedant (#343, the build board), Abhinav (#344, the planner) and Lane D (#345, the market and approval). Build the board against `contracts/samples/build-board.sample.json` now. The live data arrives in the same shape.

## A build in the market (existing tables, no schema change for the board's first version)
- **One build** is one `goal` row (`type: "build_by_date"`, the market's goal enum; there is no "build" type) with one `goal_item` per part.
  - An owned part is a `goal_item` with `skippedOwnedPartId` set, for example the buyer's 750 W PSU and case.
- **Each part that is bought** gets its own `need`, with `need.goalId` equal to the goal id and one `need_item`. Each need gets its own `round`, with knockout stages per #336. `round_result` rows give each part's bids, ranks and reasons.
- **A part's champion** is the rank 1 `round_result` of its round once the round is closed.

## What the board reads (one object per build; see the sample)
```
BuildView = {
  goalId, buyerId, budget, spent, origin,           // spent = sum of locked parts' landed prices
  parts: [{ part, label, status, budget, needId, roundId, champion?: { bidId, sellerId, persona, landed, origin, sourceUrl }, reason? }],
  checks: [{ a, b, rule, state, detail, source }],  // compatibility lines between two parts
  events: [{ at, kind, text, parts }],              // the plan, knockouts and re-plan, in order
  approval: { state, total, sellers, mandates }     // one call for the whole build
}
```
- `part` is one of `gpu`, `cpu`, `board`, `ram`, `ssd`, `cooler`, `psu` or `case`.
- `status` is one of:
  - `owned`, a part already in the buyer's rig;
  - `planned`;
  - `bidding`, the round is open;
  - `locked`, there is a champion;
  - `replanned`, the earlier pick was swapped;
  - `failed`, no eligible bid.
- `rule` is one of `socket`, `ddr`, `case_room`, `power` or `cooler_height`.
- `state` is `ok`, `clash` or `unknown`.
- `source` is the fit checker rule id: Anoop's checks in #342.
- `events.kind` is one of `plan`, `round_open`, `knockout`, `locked`, `clash`, `replan`, `call`, `approved`, `denied` or `receipt`.
  - Each event's `text` is a short human line, for example "Clash: Ryzen 7 7700 is AM5; board winner is LGA1700".
- `approval.state` is one of `waiting`, `calling`, `approved`, `denied` or `paid`.
  - One call covers the whole build.
  - `mandates` holds one entry per seller, each with `sellerId`, `amount` and `mandateHash`.

## Who writes what
- **#344 (planner):** the `plan`, `clash` and `replan` events and the parts' budgets, sent as agent events. Until the market wiring is done, they arrive as `agent_event` rows the board reads.
- **#345 (Lane D):** the goal, its needs and rounds, the champions, `approval`, `mandates` and `receipt`.
- **#342 (Anoop):** the `checks` rules and their ids.
- **The board (#343)** only reads the data. It never decides a fit or a price.

## Labels
Every part, champion and event carries `origin`: LIVE, MIRROR or SIM. The sample is all SIM, with made-up prices.
