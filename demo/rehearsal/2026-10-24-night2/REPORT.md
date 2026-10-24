# Rehearsal report (2026-10-24 04:07 PDT)

Stage command: `python3 /Users/vidyutsriram/hackathons/cal-hacks-13-2026/lane-d-night2/demo/bridge.py --reset --rounds 2 --step-delay 1`
Runs: 3 of 3. Target: 120 s per run (the 2:00 cut).

| Run | Total s | Beat 1 s | Beat 2 s | Beat 3 s | Beat 4 s | Beat 5 s | Exit | Target | Checks |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 75.29 | - | - | - | - | - | 0 | within 120 s | round_closed pass, awarded_line pass, payment_row pass, round_2_present pass |
| 2 | 75.3 | - | - | - | - | - | 0 | within 120 s | round_closed pass, awarded_line pass, payment_row pass, round_2_present pass |
| 3 | 75.32 | - | - | - | - | - | 0 | within 120 s | round_closed pass, awarded_line pass, payment_row pass, round_2_present pass |

Slowest beat: unknown (the stage command printed no `BEAT <n>` lines, so there are no per-beat timings).
Clean runs: 3 of 3 (exit 0 and every check passed).
Unverified runs: 0 of 3 (exit 0, no failed check, but at least one check was skipped, so the end state was not confirmed).

## Problems

None.

## What the checks read

- `round_closed`: every round has state closed (`SELECT id, state FROM round`)
- `awarded_line`: a bid holds rank 1 in round_result (`SELECT round_id, rank FROM round_result WHERE rank = 1`)
- `payment_row`: the payment table has a row (`SELECT mode FROM payment`)
- `round_2_present`: at least two rounds exist (`SELECT id FROM round`)

Logs: one `run<k>.log` per run beside this file (secret values replaced by `[redacted]`).
