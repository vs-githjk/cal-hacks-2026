# Wind tunnel control seller (frozen Fri Oct 23 23:09 PDT, written before any training run)
SIM. The control is **Fair Price PC** (`fair-price-pc`, `control=True` in `demo/sellers.py` on main):
one new line, list $1,289.00, floor $1,200.00, discount 0, 303 mm card, honest claims. It never changes its bid.
The learner is **Gadget Grove (Vedant)** (`gadget-grove`, a SIM seller owned by Vedant, `learning=True`): new $1,349.00 and open-box $1,279.00 lines,
2.5% discount, floors $1,230.00 and $1,190.00, and a `price_step` set only by `demo.learning.update_strategy`
from its own loss reports (banded gap, never a rival's price), clamped at its floors.
Known asymmetry, stated up front: the learner also carries an open-box line and the control does not, so builders who
accept open box can favor the learner for reasons other than learning. The runner reports an untrained-learner
column (price_step 0) so the lift from learning alone is visible.
Neither seller's definition may change after a run is recorded in sim/RESULTS.md.

## Second control (added Fri Oct 23 23:30 PDT for issue #34, written before the rerun)
**Median Market PC** (`median-market-pc`, SIM, defined in `sim/wind_tunnel.py`, not in demo/): one new line, list $1,248.50,
floor $1,200.00, discount 0, 303 mm card, honest claims, never changes. The price is the field median: the median of
every seller's cheapest bid line across the 6 archetype builders of seed 0 at price step 0 ($1,248.51, rounded down).
Measured in that reference run: Bargain Bin ($1,199) wins every builder except small_case, where its 336 mm card does not
fit the 330 mm NR200P and Best Buy ($1,249.99) wins. **Fair Price PC at $1,289 never wins by construction**; this
second control can. The median of new-condition bid lines alone was $1,289.00, the same as Fair Price PC.

## What the learner is
The learner's update is `demo.learning.update_strategy`: a Lane D SIM stand-in that changes only the price step, from
the loss report's gap band. It is **not** Abhinav's a7 strategy (agents/sellers), which the wind tunnel does not use yet.
