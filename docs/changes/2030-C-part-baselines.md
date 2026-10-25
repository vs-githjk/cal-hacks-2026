# 2030 C: dated price baselines for the Build Story parts (#342 step 6)

MIRROR. Refs #342.

- `data.baselines.part_baseline(model_number, as_of=None, rows=None)`: the GPU rule (retail asks within 24 h and eBay sold within
  30 days, two data owners, 2+ prices each) for one EXACT maker model from `data/fit_checker/part_specs.json`, read only from
  `data/mirror/parts_snapshots/`. Key: `part_key(model_number)`, never a search slug. Central Computers and Amazon rows never enter
  the median (the same RETAIL set as the GPU baseline). The GPU path and its readers are unchanged and never read parts_snapshots.
- `agents/advocate/real_data.py`: `part_baseline_for` prices a CPU, board, memory, storage or cooler line. The model comes from OUR
  data only: our own listing row for the line's URL, else the buyer's own sku (exact matcher). The seller's text alone never picks
  it. No match, or no two-owner baseline, gives an `advocate.baseline_unverified` note. The label format matches the GPU one.
- `python3 -m data.baselines.refresh --parts [--dry-run] [--cap 2] [--items 5]`: re-runs Best Buy, Micro Center, B&H and eBay sold
  for the 11 part searches (no second family, no Central Computers, no Amazon), then prints each model's baseline status. SPEND
  must be typed every time; `--yes-spend` does not skip it.
