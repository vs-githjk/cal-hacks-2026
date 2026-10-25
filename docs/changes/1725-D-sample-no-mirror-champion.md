# 17:25 Lane D: the build-board sample never locks a MIRROR store

For Vedant (#343, #365), Abhinav (#361) and Anoop (#364).

`contracts/samples/build-board.sample.json` had Central Computers (SF) as the locked GPU and cooler champion. Central Computers is MIRROR: a real store that never agreed to sell through us, so it is never a winner and never paid (decisions.md). The sample now uses SIM sellers instead:

- GPU champion: `seller_4`, Micro Center, $1,249.99, SIM.
- Cooler champion: `seller_2`, B&H, $52, SIM.

Totals, part ids and the shape are unchanged (spent $1,968, 4 sellers). If you copied the sample into `web/public/`, copy it again. When a MIRROR offer ranks first in a live round, Lane D marks that part `failed` (docs/changes/1705-D-build-in-the-market.md); show it as a comparison card ("Comparison only, not paid"), never as locked.
