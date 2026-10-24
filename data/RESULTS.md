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

### Second maker re-check (Sat 2026-10-24, maker pages read through a search index restricted to each maker's domain)
26 more parts confirmed on maker domains (amd.com, intel.com, asus.com, msi.com, corsair.com, evga.com, gskill.com, samsung.com, nvidia.com, nzxt.com): nine CPUs (socket, TDP), seven boards (socket, form factor, memory type), three memory kits, the Corsair CX550, CV450 and EVGA 600 BR, two Samsung drives, the RTX 4090 Founders Edition (304 mm) and the NZXT H5 Flow (2023 spec 365 mm GPU, 165 mm cooler). Each part carries `check_source`.
- Value corrected: Corsair CV450 PCIe 8-pin connectors 1 -> 2 (corsair.com lists two on one cable). No build truth changed.
- Still unconfirmed: Seasonic FOCUS GX-850 (2019) 8-pin count (the maker PDF is for a later revision), Corsair RM650e and RM750e (2023) 8-pin counts, G.Skill Trident Z5 4x16GB (no such kit found on gskill.com), MSI RTX 4060 Ventus length.

| set | builds | decided correct | false OK | false fail | uncertain |
|---|---|---|---|---|---|
| all 44 | 44 | 42 of 43 | 0 | 1 | 1 |
| maker-checked subset (every part confirmed on a maker page) | 33 (was 12) | 33 of 33 | 0 | 0 | 0 |

False OK is 0 on both. The checker was not changed; the set was tuned on once, so neither row is held out.

### Fit depth (Sat 2026-10-24, issue #159)
Cooler height vs case clearance and RAM generation/form vs the board, using maker values already confirmed on maker domains (`data/fit_checker/depth_data.json`: 6 coolers, 3 cases, 6 boards). One rule was truly missing and was added: `fit.ram_form` (DIMM vs SO-DIMM; a check only when a form is stated, uncertain when only one side states it). Six new maker-checked builds: NH-L12S, AK400 and NH-U12S in the Fractal North; a DDR5 kit on Z890 (fits); a DDR4 kit on Z790 (does not fit); a Crucial DDR5 SO-DIMM kit on a desktop DIMM board (does not fit).

| set | builds | decided correct | false OK | false fail | uncertain |
|---|---|---|---|---|---|
| all | 50 | 48 of 49 | 0 | 1 | 1 |
| maker-checked subset | 39 | 39 of 39 | 0 | 0 | 0 |

**False OK: 0** on both. The checker's existing rules were not tuned; the set was tuned on once, so neither row is held out.

## First price numbers on real parts (MIRROR, RTX 5070 Ti)

Run: `python3 -m data.mirror.price_spread`. Source: the c1 Apify snapshots in `data/mirror/snapshots/`. Out-of-stock listings are left out of the ask range (not buyable at that price) and counted.

Snapshots (MIRROR): 2026-10-24T05:08, 2026-10-24T05:09 UTC. Query "RTX 5070 Ti", 3 to 5 items per store.

| what | n | min | median | max |
|---|---|---|---|---|
| store asks, in stock or stock unknown | 11 | $1,199.99 | $1,299.99 | $1,489.00 |
| eBay sold baseline, 2026-10-23 to 2026-10-23 | 5 | $640.00 | $880.00 | $1,476.86 |

Asks vs the sold median: +36% (lowest ask) to +69% (highest), median +48%.

| store | n priced | min | median | max |
|---|---|---|---|---|
| amazon | 2 | $1,299.99 | $1,344.99 | $1,389.99 |
| bestbuy | 3 | $1,249.99 | $1,249.99 | $1,299.99 |
| bh | 0 | - | - | - |
| ebay_live | 3 | $1,239.99 | $1,399.99 | $1,489.00 |
| microcenter | 3 | $1,199.99 | $1,259.99 | $1,299.99 |

Left out of the ask range: 4 out-of-stock listings. Listings with no price on the page: 0. Baseline conditions: new, open-box, unknown, used.

**Read this before quoting anything above. These results are weak, and some look bad for us:**
- **The baseline is not a fair one.** It has 5 eBay sales, all ending on one day, in mixed condition (new, used, open box, unknown). Its median ($880) sits far below every store ask, and the cheapest sales ($640 open box, $699 "new") could be partial or misdescribed items we have not checked. The "+48%" is asks against a mixed used-market median. **It is not a markup and must not be quoted as one.**
- **Two sold "new" items differ by about $778** ($699 and $1,476.86, and the second also had $125.94 shipping). With n = 5, the sold price for this card is not pinned down at all.
- **The sample is tiny.** There are 11 priced asks that are in stock or of unknown stock, 2 to 3 per store; 4 more listings were out of stock (all 3 at B&H, 1 at Amazon) and are left out.
- **No savings number exists yet.** The only was prices captured (Best Buy) equal the price; the other scrapers do not capture one. So this snapshot has no discount claims to check.
- **Only one dated source.** The kickoff asks for two dated sources within 24 h before a buy (c11). This is one source, at one time.

What it shows: across 4 stores with buyable or unknown-stock listings at one time, asks for this card (new where stated; first-party stores give no condition; one eBay ask is open box) ran from $1,199.99 to $1,489.00, median $1,299.99.
Next: a condition-matched baseline (new only, more sold rows, 30 days), a second dated source (c11), and a re-run on a second day.
