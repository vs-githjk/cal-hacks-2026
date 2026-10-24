# Wind tunnel control seller (frozen Fri Oct 23 23:09 PDT, written before any training run)
SIM. The control is **Fair Price PC** (`fair-price-pc`, `control=True` in `demo/sellers.py` on main):
one new line, list $1,289.00, floor $1,200.00, discount 0, 303 mm card, honest claims. It never changes its bid.
The learner is **Gadget Grove** (`gadget-grove`, `learning=True`): new $1,349.00 and open-box $1,279.00 lines,
2.5% discount, floors $1,230.00 and $1,190.00, and a `price_step` set only by `demo.learning.update_strategy`
from its own loss reports (banded gap, never a rival's price), clamped at its floors.
Known asymmetry, stated up front: the learner also carries an open-box line and the control does not, so builders who
accept open box can favor the learner for reasons other than learning. The runner reports an untrained-learner
column (price_step 0) so the lift from learning alone is visible.
Neither seller's definition may change after a run is recorded in sim/RESULTS.md.
