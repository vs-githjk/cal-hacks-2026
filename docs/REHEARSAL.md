# Rehearsal: run the five-beat skeleton and record it

`demo/rehearse.py` runs the demo skeleton N times against the local stack and writes a report, so the 08:00 run-through is
Vidyut watching, not debugging. It starts nothing and stops nothing: the stack must already be up.

## The 08:00 command

Run from the repo checkout that has the local stack running (SpacetimeDB on 3000, web on 3100):

```
python3 /ABSOLUTE/PATH/TO/demo/rehearse.py --runs 3 --screens --out /ABSOLUTE/PATH/TO/demo/rehearsal/2026-10-24-0800
```

Plan only, nothing touched: add `--dry-run`. One run, no screenshots: `--runs 1`.

The stage command is `demo/stage.py --auto` when that file exists, else `demo/bridge.py --reset --rounds 2 --step-delay 1`.
Override it with `--stage-cmd "<command>"`. Note that every run RESETS the demo tables (both stage.py and bridge.py call
`reset_demo`), so do not rehearse while someone is looking at /buyer or /market. A run is killed after `--timeout` seconds (default 900).

## What it writes

- `REPORT.md`: one table row per run (total seconds, seconds for beats 1 to 5, exit code, within or over the 2:00 target of
  120 s, checks), the slowest beat, a Problems list that names the beat and the last stage output line for every failure.
- `runs.json`: `[{run, started_at, seconds, beats: {"1": s, ...}, exit_code, checks: {name: pass|fail|skipped}, screenshots: [path], last_beat, last_line, timed_out, check_notes, screenshot_notes}]`.
- `run<k>.log`: the stage output of each run. Values of env vars whose names look secret (KEY, TOKEN, SECRET, PASSWORD, DSN, ...)
  are replaced by `[redacted]` everywhere. The harness reads no token or `.env` file.
- `screens/run<k>-beat<n>-buyer.png` and `-market.png` with `--screens`: 1440x900 headless Chrome shots of
  http://localhost:3100/buyer and /market taken when each beat ends. A failed screenshot is listed in Problems and never stops a run.

Per-beat seconds come from lines that start with `BEAT <n>` in the stage output (stage.py prints them). `demo/bridge.py`
alone prints no such lines, so with the bridge default the beat columns show `-` and the report says so. Total seconds is still real.

## What each check means (read only, `spacetime sql` against the local database)

| Check | Passes when | If it fails |
|---|---|---|
| `round_closed` | every row in `round` has state `closed` | a round was left open: the close step or the deadline wait did not finish |
| `awarded_line` | `round_result` has a row with rank 1 | the market ranked nothing: no valid bid reached the close |
| `payment_row` | `payment` has a row | beat 4 did not record a payment (denied approval, or it never ran) |
| `round_2_present` | `round` has at least two rows | beat 5 (round 2) never opened |

`skipped` means the query could not be read (CLI missing, not logged in, server down); the reason is in Problems. A skipped
check is never counted as a pass, and it does not fail the run.

## Exit codes

- 0: every run exited 0 and no check failed.
- 1: a run failed (non-zero exit or timeout) or a check failed. The harness still finishes the remaining runs.
- 2: the stack is down (port 3000 or 3100 refused). `REPORT.md` says `stack down at HH:MM, not run` and nothing was started.

## If a run fails

1. Open `REPORT.md`, Problems: it names the beat and the last stage line. The full output is in `run<k>.log`.
2. Fix or re-run only that run: `--runs 1`.
3. If it keeps failing at 08:00, play the recorded clip for that beat instead of the live run, and say so on stage. Do not
   re-run with `--force` flags or edit the stack in front of people.
