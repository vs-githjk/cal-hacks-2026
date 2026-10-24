# Mirror bid provenance and eligibility

MIRROR bids now retain captured listing IDs, snapshot identifiers and dates, and seller-of-record names only where the listing or existing retailer grouping supplies them. eBay and Amazon third-party rows without captured merchant identity remain visible as skips and cannot bid.

The demo keeps its existing 93% operator floor and zero-shipping behavior, but labels both as SIM policy alongside the MIRROR asking price. The private numeric floor stays inside the referee policy and out of the bid and decision trace. Bid validation pins SIM floor and shipping policy evidence to the public `demo/sellers.py` source.

Focused validation: seller provenance tests and Advocate adapter tests pass. Full-round tests that create throwaway Ed25519 keys could not run in this sandbox because `os.open(..., 0o600)` is denied even under a worktree-local temp directory; this does not affect the focused adapter tests.
