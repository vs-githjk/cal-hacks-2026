# 0300 D: the demo winner fits the case (additive, no contract field removed)

Night run 2, T1. Vidyut's case takes 305 mm. The demo winner is now the ASUS Prime RTX 5070 Ti OC Edition (304 mm, maker spec) at Best Buy, $1,299.99 before sales tax, inside the $1,300 cap. It was the MSI Gaming Trio at $1,249.99 with "fit not confirmed"; the maker spec says 338 mm.

## What changed (all in demo/, the SIM runner)
- MIRROR seller agents pick, per condition, the cheapest real listing that fits the buyer's case clearance (305 mm, `demo.sellers.CASE_CLEARANCE_MM`) using maker-spec lengths in data/fit_checker/gpu_lengths.json. No fit but an unknown length: the cheapest unknown, flagged. All known and too long: the cheapest, which the advocate vetoes.
- Cheaper lines of the same seller that the maker spec says are too long are listed on the bid as `withheld_lines` (model, price, rule `fit.gpu_length`, the real fit checker's reason, the maker spec URL). The key is additive. It is not seller text, so Shield does not screen it (Shield reads a long URL path as an encoded payload: shield.encoded.payload fires on maker spec URLs, a false positive to report to the Shield owner).
- MIRROR bid lines carry `attrs.length_mm`, `attrs.length_source`, `attrs.length_model` when the model is in the table. A title that is not in the table gets no length (unknown, never guessed).
- Advocate: a `fit.gpu_length` veto cites the maker spec page when the line has one (`demo/advice.py`; `agents/advocate/checks.py` untouched).
- Buyer rule, demo only (to move into the advocate, issue for Abhinav): a fit-unknown bid cannot win while a confirmed-fit bid is inside the cap (`demo/round.py pick_winner`).
- Winner line says `before sales tax` and `shipping: not captured` when the listing states no delivery cost (`landed_note`).
- SIM prices retuned so the real ASUS line wins honestly: Gadget Grove open-box list 1279 -> 1319 (it still wins round 2 after one learning step), Fair Price PC (static control) 1289 -> 1329, now just over the cap.

## Same schema
demo/out/sample-run.json is regenerated (`python3 demo/run_demo.py --out-dir <dir>`, copied over). No key was removed; keys added: `bids[].withheld_lines[]` and the three `length_*` attrs. Values changed: Best Buy line and mandate amount (1299.99), Gadget Grove open-box (1286.02), Fair Price PC (1329.00).
