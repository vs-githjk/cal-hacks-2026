# Arena rules: when two buyers want the same thing

The short version: the referee never rolls dice. The same bids always give the same ranking. Two requests for the same part can still end differently, because the sellers, their stock and the clock are different each time. Like a boxing match, the ring and the judges are fixed; what happens in it is not.

## What the referee fixes

1. **Sealed bids.** Nobody sees another seller's bid until the round closes. A bid that lands in the last 3 seconds adds 5 seconds, at most twice.
2. **One ranking rule.** Bids rank on quality-adjusted landed price, lowest first. A tie goes to the bid with more verified claims, then to the earlier bid, then to the lower seller id. The same bids in any order give the same ranking.
3. **No pay for rank.** The seller fee never enters the ranking. Shield blocks, advocate vetoes, a price under the seller's own floor and a bid over the buyer's cap take a bid out, each with its reason.

## What changes the outcome

The referee is the same every time. These are not:

- **The sellers.** Each seller agent has its own pricing (a fixed margin or a discount), its own floor per condition, its own perks, and may bid several conditions of one part (new, open-box, refurbished) as alternatives.
- **Stock.** A bid states how many units the seller has. Nobody can win a unit the seller no longer has.
- **The clock.** If two rounds want the last unit, the round that closes first wins it.
- **Learning.** A losing seller gets a loss report (the gap and the reason) and can lower its price next round, never under its floor. Built in the simulation today; the loss report table is Vedant's work and is not on this branch yet.
- **Not built yet:** sellers that raise or lower their price because they can see demand (how many buyers want the part). The rules above allow it, since a seller may bid anything above its floor, but no seller agent does it today.

## The last unit

1. The round that wins a unit **holds** it. The hold is written when the round closes and lasts 2 minutes, the same as the approval code. The unit is out of every other round while it is held.
2. A later round that would award that unit **skips that line** with the reason "sold out to an earlier round" and awards the next best bid. A seller with a second allowed line (say open-box) still ranks on that line. A seller with spare stock is not skipped: a hold takes only the units the winning round needs.
3. The hold ends one of three ways:
   - **Sold.** The payment is recorded. The unit is gone for good.
   - **Released.** The approval is denied (wrong code, silence, a no), or 2 minutes pass with no answer. The unit goes back on sale.
   - **Renewed.** Making the mandate for that deal starts a fresh 2 minutes, because the call starts then. If the hold had run out and another round took the unit meanwhile, the mandate is refused as sold out and the deal must be re-quoted.
   - **One sale, one buyer.** A deal belongs to the buyer whose need the round served: another buyer's mandate on it is refused as "not your deal", even before the round closes and a hold exists, because the owner is read from the bid itself. Once a unit is sold, a second mandate, approval or payment on the same deal is refused as sold out and the deal must be re-quoted.
   - **Short stock is not a sell-out.** A line that states less stock than the need keeps its real quantity reason; "sold out to an earlier round" is only shown when holds caused the shortfall.
4. Nobody is oversold. Reducers run one at a time, so two rounds closing together are decided in a fixed order: whichever the market closes first.

A deal is tied to its hold by its deal id, which names the awarded bid (`<bid id>`, `deal-<bid id>` or `<round id>:<bid id>`). A deal that names no awarded bid touches no hold.

## What this does not claim

- A seller's stated stock is read as stock before any sale in the arena. The arena subtracts what it sold, so a seller should not also lower its own number after a sale, or the sale counts twice.
- Replaying the same need in a second round (the demo's round 2) does not compete with itself: holds made by rounds that served the same need are ignored when that need's later round closes, so a seller that sold its unit in round 1 can bid again in the replay. A round that serves a different need (the second buyer) still meets every held or sold unit.
- The second buyer and every stock count are SIM. Six of the eleven demo sellers (Best Buy, Amazon.com, Micro Center and three eBay sellers) are MIRROR snapshots of real listings whose stock count was not captured, so the one unit each holds is our assumption, not their inventory. The other five sellers are SIM. See `docs/REAL_VS_SIMULATED.md`.

Run it: `python3 demo/bridge.py --two-buyers` plays Vidyut's deal, then a second buyer (buyer-2, SIM) goes for the same single units. The market screen shows the skipped line with its reason. Tests: `market/spacetimedb/src/market.test.ts` (describe "T11 contention") and `market/rules/holds.test.ts`.
