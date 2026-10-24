# Wind tunnel results (SIM)

Run 2026-10-24T06:10:48+00:00 UTC: `python3 -m sim.wind_tunnel --builders 10 --seeds 3`. Everything here is SIM. Control and learner are defined in sim/CONTROL.md.

## Learning arm (benign builders only)
**Too few held-out rounds to quote a lift (n = 6, below 20).** Raw counts: the learner won 3 of 6 held-out rounds, the control 0 of 6. Run with more builders before using a number.

| seed | train builders | held-out builders | learner win rate | control win rate | untrained learner | lift | frozen price step |
|---|---|---|---|---|---|---|---|
| 0 | 8 | 2 | 0.50 | 0.00 | 0.00 | +50 pts | 0.07 |
| 1 | 8 | 2 | 0.50 | 0.00 | 0.00 | +50 pts | 0.07 |
| 2 | 8 | 2 | 0.50 | 0.00 | 0.00 | +50 pts | 0.07 |

Mean lift +50 pts (range +50 pts to +50 pts); untrained learner vs control +0 pts. Held-out archetypes: open_box_ok, small_case.

Per held-out archetype (learner / control win rate, by seed): seed 0: open_box_ok 0.00/0.00 (n=1), small_case 1.00/0.00 (n=1); seed 1: open_box_ok 0.00/0.00 (n=1), small_case 1.00/0.00 (n=1); seed 2: open_box_ok 0.00/0.00 (n=1), small_case 1.00/0.00 (n=1)

## Attack arm (Shield, rules only, no classifier; no learning measured)
| set | attacks | stopped | block rate | clean | false blocks |
|---|---|---|---|---|---|
| dev | 30 | 30 | 100% | 10 | 0 |
| held_out | 20 | 12 | 60% | 10 | 2 |

Held-out misses: h01, h03, h05, h07, h09, h13, h15, h20. Held-out false blocks: k04, k05.
The dev column is what the rules were written against; quote held-out, never a pooled number, and never "secure".

## Caveats
- n is small: 6 held-out rounds in total. Seeds vary builders (cap, case, PSU); sellers are deterministic.
- **Every seed gave the same lift.** Winners depend on the builder's archetype only, so the seeds add no independent evidence and the range is not an interval. Seeds that vary sellers too are needed before quoting.
- The learner has an open-box line the control lacks (sim/CONTROL.md); compare with the untrained column.
- Rounds reuse demo/round.py on SIM and MIRROR sellers from one dated snapshot (Oct 24).
