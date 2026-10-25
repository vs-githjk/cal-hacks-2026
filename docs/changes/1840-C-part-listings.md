# 1840 C: real MIRROR listings and maker specs for CPU, board, memory and cooler (#342, part of the Build Story)

MIRROR: captured Oct 24 2026 18:00 to 18:40 PDT with Apify. Refs #342 (not Closes: #342 also holds the injection screen fix).

- `data/mirror/parts.py`: `PART_SEARCHES` (11 searches), `offers(part, owned=None, max_price_cents=None)` in #344's shape
  `{seller, price_cents, spec, source}` plus `origin` MIRROR, `snapshot_id`, `captured_at`, `orderable`, `condition`, and the maker
  page. `skipped(part)` lists every captured listing that cannot bid, with the reason.
- Only a listing whose EXACT model has a maker row in `data/fit_checker/part_specs.json` ever bids. Its spec comes from that row
  (maker page URL and check date cited), never from seller text. No row, no bid, no guess.
- Central Computers rows are `orderable: False` and only listed when the SF store has one in stock. Condition stays "unknown".
  eBay sold rows are baseline history, never offers. An Amazon listing bids only when the page names Amazon itself as the seller.
- `data/mirror/run_actors.py --parts`: `--cap` (default $5, at most $10, a run is skipped if its worst case would pass it), the SPEND
  prompt (no flag skips it), `--dry-run`, `--stores`, `--workers`, `--approved-by` (written into every log record).
- `data/mirror/normalize.py`: `to_spec_card(..., part=)` is category-aware; without `part` the GPU path is unchanged.
- `data/fit_checker/build_check.py`: a named CPU, board, memory, storage or cooler is filled from `part_specs.json` when we hold the
  exact model; the caller's own spec still wins, and an unknown model stays uncertain.
- `python -m data.mirror.red_line` (offline): which real clash the Build Story would hit on these prices.
- Snapshots are in `data/mirror/parts_snapshots/` (not `snapshots*`, so the GPU baselines, the claim scan and the pulse
  orchestrator do not read them). Raw items are in `data/mirror/raw/`, reduced to the fields the cards use.
- Baselines: not added yet. Once #287 is merged, the new searches go on `data/baselines/refresh.py`'s SKU list for the Sat 22:00
  and Sun 06:00 refreshes; until then the advocate says "Price baseline unavailable (unverified)" for these parts.
