# 1456 C: Central Computers (SF) as a MIRROR seller (#308, part of #283 T9)

MIRROR: real Central Computers listing captured Oct 24 21:12 UTC via Apify. Central Computers is not a partner.

- New snapshot `data/mirror/snapshots/centralcomputers-20261024T2112Z.json`: the 12 RTX 5070 Ti rows from #308, unchanged except
  `source`, which is the listing URL like every other snapshot (the Apify actor id stays in `listing.apify_actor` and
  `listing.apify_run_id`). Extra listing fields: `availability` (`in_stock_sf_store`, `not_in_sf_store`, `special_order`),
  `sf_store_qty`, `store_inventory`, `sku`, `seller_location`, `source_page`.
- `data/mirror/central_computers.py`: the seller. Bids only rows with `availability == "in_stock_sf_store"`, at the listed
  price, floor 93 percent of list (the same SIM assumption as demo/sellers.py FLOOR_OF_LIST). Condition stays `unknown`.
  It bids one line: the cheapest SF in-stock card with a maker-confirmed length (that fits the clearance when one is given);
  unknown-length and too-long cards go to `withheld_lines` with the reason.
- `agents/sellers/policy.py`: `mirror_seller("central_computers_sf", clearance_mm=None)` and `make_bid` now honour a MIRROR
  seller: `origin` MIRROR, `source` the listing URL, the seller's own `mirror_snapshot_id`, additive keys `mirror_label` and
  `withheld_lines`, `qty_available` on the line. SIM sellers' bids are unchanged (tested).
- `agents/advocate/checks.py`: a condition of `unknown` (offered or page) is now an `unverified` caution with rule_id
  `advocate.unsourced` (existing summary, so pay/reasons.py needs no change). It is never shown as new and is no longer a
  mismatch veto or a "you asked for new" spec caution. Stated conditions keep the old checks.
- `data/baselines`: the rows are observations (store `centralcomputers`, kind ask) but stay OUT of the retail median
  (`LOCAL_STORE`, not in `RETAIL`): a bid must not move the baseline it is judged against. The median at 21:30 UTC is
  unchanged at $1,259.99.
- `data/fit_checker/gpu_lengths.json`: two maker rows ahead of the family matches: MSI VENTUS 3X PZ OC (303 mm) and the
  non-OC ASUS PRIME-RTX5070TI-16G (304 mm). ROG Strix stays unknown.
- `demo/sellers.py` (Lane D, one line): `load_offers` skips a snapshot prefix that has no `SELLER_OF_RECORD` entry, so the
  stage round is exactly as before. **Offer to Lane D:** to use the store in the stage round, add
  `"centralcomputers": "Central Computers (SF)"` to `SELLER_OF_RECORD` and take offers from
  `data.mirror.central_computers.stage_offers()` (SF in-stock rows only; the special-order rows' stock text is not
  "out of stock", so the generic `_stock_ok` would let them bid). The cheapest SF card that fits 305 mm is $1,249.99.
- Not done: Central Computers is not yet a running uAgent. The buyer only accepts bids from `common.SELLERS`
  (agents/buyer/buyer_agent.py SELLER_ADDRS), so a live round needs a new identity: a `seller_6` slot in
  `common.SELLERS`/`SELLER_PORTS`/`factory.PORT_OWNERS`, an `AGENTVERSE-seller_6.md`, `SELLER_6_AGENT_SEED` on Abhinav's machine
  and `seller_agent.build` reading `mirror_seller`. No existing address changes; needs Abhinav's go (#283 rules).
