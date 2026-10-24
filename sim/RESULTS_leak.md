# Loss-report leak (SIM), BLIND first run

Run 2026-10-24 11:01 UTC at git 3e8c798: `python3 -m sim.leak --seeds 3`. Standalone model, not the full market: controls at Bargain Bin $1,199.00, Median Market $1,248.50, Fair Price $1,289.00 with a seeded +-1% jitter; clearing price is the lowest bid; a loss report gives the gap band. Band names and steps are demo.learning's; mitigations are parameters in sim only. Nothing was tuned after seeing these numbers; any rerun goes in a separate not-blind section below.

## Probe: rounds for a seller varying its bid to land within 2 percent of the price to beat
Start $1,349, cap 40 rounds ('not reached' if capped).

| reports | seed 0 | seed 1 | seed 2 |
|---|---|---|---|
| default (4 bands, every round) | 3 | 2 | 3 |
| coarse (2 bands, every round) | 6 | 6 | 6 |
| default bands, report every 3rd round | 7 | 4 | 7 |
| coarse bands and every 3rd round | 16 | 16 | 16 |

## Collusion: two learners with the same rule, 20 rounds
Starts $1,349 and $1,339. A loss sets the price to start x (1 - step for its band); a win raises 1% next round. Clearing price at rounds 1, 10, 20 per seed; 'rose' = round 20 above round 1.

| reports | market | seed 0 (r1 / r10 / r20, rose) | seed 1 (r1 / r10 / r20, rose) | seed 2 (r1 / r10 / r20, rose) |
|---|---|---|---|---|
| default (4 bands, every round) | with controls | 1,207.26 / 1,138.15 / 1,146.65, no | 1,190.23 / 1,138.15 / 1,146.65, no | 1,209.94 / 1,138.15 / 1,146.65, no |
| default (4 bands, every round) | learners only | 1,339.00 / 1,308.53 / 1,308.53, no | 1,339.00 / 1,308.53 / 1,308.53, no | 1,339.00 / 1,308.53 / 1,308.53, no |
| coarse (2 bands, every round) | with controls | 1,207.26 / 1,004.25 / 1,011.75, no | 1,190.23 / 1,004.25 / 1,011.75, no | 1,209.94 / 1,004.25 / 1,011.75, no |
| coarse (2 bands, every round) | learners only | 1,339.00 / 1,254.57 / 1,254.57, no | 1,339.00 / 1,254.57 / 1,254.57, no | 1,339.00 / 1,254.57 / 1,254.57, no |
| default bands, report every 3rd round | with controls | 1,207.26 / 1,146.65 / 1,149.53, no | 1,190.23 / 1,146.65 / 1,149.53, no | 1,209.94 / 1,146.65 / 1,149.53, no |
| default bands, report every 3rd round | learners only | 1,339.00 / 1,308.53 / 1,298.83, no | 1,339.00 / 1,308.53 / 1,298.83, no | 1,339.00 / 1,308.53 / 1,298.83, no |
| coarse bands and every 3rd round | with controls | 1,207.26 / 1,011.75 / 1,014.29, no | 1,190.23 / 1,011.75 / 1,014.29, no | 1,209.94 / 1,011.75 / 1,014.29, no |
| coarse bands and every 3rd round | learners only | 1,339.00 / 1,254.57 / 1,245.27, no | 1,339.00 / 1,254.57 / 1,245.27, no | 1,339.00 / 1,254.57 / 1,245.27, no |

With the controls present the clearing price can never exceed the cheapest control (the lowest bid sets it), so a rise there would need the controls to leave.

Caveats: a model with fixed controls and one probe, 3 seeds; it says what the reports leak in this setup, not what a real market would do.
