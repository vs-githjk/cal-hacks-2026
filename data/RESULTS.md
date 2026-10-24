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
Next: re-open each spec page, then add held-out builds that no one tuned against.
