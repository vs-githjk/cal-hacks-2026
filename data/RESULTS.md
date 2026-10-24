# Lane C results (every number labelled)

## c2 fit checker on the frozen build set (SIM)

Set: `data/fit_builds.json`, 44 builds, frozen and committed before tuning. Truth = within the makers' published specs
(recommended PSU, clearances, sockets, chipset support). **Not yet hand-checked:** the part specs were drafted from known
spec values and each spec page still needs a human re-open (`hand_checked: false` in the file).
Run: `python -m data.fit_checker.eval_builds`

### Before tuning (first run on the frozen set)
- decided (pass or fail): 43, correct 41 (95%)
- uncertain: 1
- **false OK: 1** (`terra_atx_psu`: there was no PSU form-factor rule, so an ATX PSU "fit" an SFX-only case)
- false fail: 1 (`9950x_5090fe_1000`)

### After one change (added `fit.psu_form_factor`; same set, so this run is not held out)
- builds: 44 (SIM, frozen set in data/fit_builds.json)
- decided (pass or fail): 43, correct 42 (98%)
- uncertain: 1
- **false OK (said fits, does not): 0**
- false fail (said does not fit, fits): 1
  - false fail: `9950x_5090fe_1000` (fit.psu_wattage)
  - uncertain: `zen3_b350` (fit.cpu_socket)

The false fail is on purpose: the PSU rule takes the larger of the maker's recommended PSU and the estimated load plus
25% headroom, so a 170 W CPU plus RTX 5090 on 1000 W is flagged. We prefer a false fail to a false OK.
The uncertain row is a 300-series AM4 board with Ryzen 5000, where support depends on the board's BIOS.
**Do not quote 42/43 as hand-checked accuracy.** It is accuracy against drafted specs until every part's spec page is re-opened.

### Review fixes (Fri 22:40, same frozen set, score unchanged)
- A CPU card with no TDP or vendor now makes `fit.psu_wattage` uncertain instead of judging on the GPU alone.
- EATX in an ATX mid tower (known only by case type) and an SFX PSU in an ATX bay are now uncertain, not fail.
- Table rows re-checked: RTX 5070 Ti and 5070 on nvidia.com (2x 8-pin adapter, 750 W and 650 W). RX 9070 and 9070 XT recommended PSU left out: amd.com blocked our fetch and third-party pages disagree, so the load estimate decides.

### Spec re-check (Fri, maker pages read by an agent, not a person)
Each part in `fit_builds.json` now carries `checked` (level, source, date); a build is `hand_checked` only if every part was confirmed on a maker page.
- Values corrected: Fractal North cooler clearance 145 mm (was 170); Noctua NH-D15 168 mm (was 165); O11 Dynamic EVO GPU 455 mm; Strix 4090 and Astral 5090 357.6 mm; Sapphire NITRO+ 7900 XTX 420 W board power, 800 W PSU; RM850x 2024 has 3x 8-pin, RM1000x has 4x; B650I AORUS ULTRA 4 SATA. RM650e and RM750e connector counts could not be confirmed and were removed (unknown).
- Truths changed by the corrections: `demo_hero` (PA120 SE does not fit the North), `nhd15_h5`, `4090fe_14900k_1000`. No builds added or removed.
- Not confirmed: Ryzen 5 5600X on PRIME B350M-A, H5 Flow (retailer listings only), CPU TDPs, memory kits, most boards and remaining PSUs.

| set | builds | decided correct | false OK | false fail | uncertain |
|---|---|---|---|---|---|
| all 44 (after re-check) | 44 | 42 of 43 | 0 | 1 | 1 |
| maker-checked subset | 12 | 12 of 12 | 0 | 0 | 0 |

Say "12 of 12 on builds whose specs we confirmed on maker pages; 42 of 43 on the full set, partly unconfirmed". The set was tuned on once, so neither is held out.
Next: confirm the remaining parts, and add held-out builds no one tuned against.

## First price numbers on real parts (MIRROR, RTX 5070 Ti)

Run: `python3 -m data.mirror.price_spread`. Source: the c1 Apify snapshots in `data/mirror/snapshots/`.

Snapshots (MIRROR): 2026-10-24T05:08, 2026-10-24T05:09 UTC. Query "RTX 5070 Ti", 3 to 5 items per store.

| what | n | min | median | max |
|---|---|---|---|---|
| store asks (Micro Center, Best Buy, B&H, eBay live, Amazon) | 14 | $1,189.95 | $1,299.99 | $1,489.00 |
| eBay sold baseline, 2026-10-23 to 2026-10-23 | 5 | $640.00 | $880.00 | $1,476.86 |

Asks vs the sold median: +35% (lowest ask) to +69% (highest), median +48%.

| store | n priced | min | median | max |
|---|---|---|---|---|
| amazon | 2 | $1,299.99 | $1,344.99 | $1,389.99 |
| bestbuy | 3 | $1,249.99 | $1,249.99 | $1,299.99 |
| bh | 3 | $1,189.95 | $1,299.99 | $1,399.99 |
| ebay_live | 3 | $1,239.99 | $1,399.99 | $1,489.00 |
| microcenter | 3 | $1,199.99 | $1,259.99 | $1,299.99 |

Listings with no price on the page: 1. Baseline conditions: new, open-box, unknown, used.

**Read this before quoting anything above. These results are weak, and some look bad for us:**
- **The baseline is not a fair one.** It has 5 eBay sales, all ending on one day, in mixed condition (new, used, open box, unknown). Its median ($880) sits far below every store ask, and the cheapest sales ($640 open box, $699 "new") could be partial or misdescribed items we have not checked. The "+48%" is asks against a mixed used-market median. **It is not a markup and must not be quoted as one.**
- **Two sold "new" items differ by about $778** ($699 and $1,476.86, and the second also had $125.94 shipping). With n = 5, the sold price for this card is not pinned down at all.
- **The sample is tiny.** There are 14 priced asks, 3 to 5 per store, and 3 of them (B&H) are out of stock, so they cannot be bought at that price.
- **There is nothing to verify savings against.** No store showed a "was" price that differed from its price (Best Buy's was equal to its price), so this snapshot has no discount claims to check, and no "verified savings" number exists yet.
- **Only one dated source.** The kickoff asks for two dated sources within 24 h before a buy (c11). This is one source, at one time.

What it does show: across 5 stores at one time, asks for this card (new where stated; first-party stores give no condition; one eBay ask is open box) sat in a narrow band ($1,190 to $1,489, median $1,300).
Next: a condition-matched baseline (new only, more sold rows, 30 days), a second dated source (c11), and a re-run on a second day.
