# T15 replay driver report

## Scope

Worktree: `C:\Users\abhin\CAL_HACKS_13\lane-a-replay-driver`

Branch: `codex/lane-a-replay-driver`, based on `080bcd5fc413b57ccced4ec2cbbc066761dee846` (`Guard conclude after CRS notice`). This is a driver-only draft. It adds `agents/buyer/replay.py` and `agents/buyer/test_replay.py`; it does not edit buyer or Market handlers, the 143-owned replay worktree, the feed, or state schema.

## Driver contract

`async run_replay(rows, scenario, dispatch, clock, state_path) -> report` accepts only explicit `mode="SIM"` and `transport="SIM"`. It requires a matching buyer-owned goal already persisted in state, a required async dispatcher, and a clock with `now()` / `advance_to()` using aware UTC datetimes. The callback contract is `await dispatch(event, *, now, db, scenario) -> {"next_wakeup_at": datetime | None, "events": list}`; event is either `{"kind": "observation", "row": copied_original_row}` or `{"kind": "wakeup", "scheduled_at": datetime}`. The callback returns the earliest outstanding wakeup. The runner schedules rows and callback-returned wakeups in timestamp order, with wakeups first on ties. Wakeups must advance strictly and dispatch/event counts are bounded.

The runner opens `agents.buyer.state.open_state(state_path)` only for a dedicated `.state` path distinct from `DEFAULT_DB_PATH`, keeps the SQLite connection on its creating thread, and closes it after the run. It does not run startup recovery or create a goal/transaction. Rows are deep-copied before dispatch and passed with all original fields intact. Reports include derived row/provider counts and time bounds, a canonical digest of the `rows` argument (explicitly not a source-file SHA), safe event summaries with matching run/buyer/goal IDs, and no callback text or state path.

The dispatcher was not supplied. Tests use a clearly named SIM test callback to verify only runner scheduling, event-contract validation, and state isolation; these tests do not prove a production hunt, market selection, deadline transition, or quote-expiry callback. Provider/CRS/model and payment/approval/settlement execution remains outside this driver, and the driver has no client or service dependencies. The actual Market adapter must be supplied and reviewed before production replay claims or integration.

## Input evidence at this base

The feed present at base `080bcd5` contains MIRROR rows from `apify` and `apify-b`. The runner and tests derive the count/window/source counts at runtime; no count, date range, or feed hash is hard-coded in the driver.

- Row count: 22
- Row time bounds: `2026-10-24T05:08:39.627Z` to `2026-10-24T08:51:32+00:00`
- Provider counts: `apify: 19`, `apify-b: 3`
- Canonical `rows` argument SHA-256: `5b6a84797fddaf8dc815c14916b119f94a276ed424fc651146a5f64498f9aa43`

That digest is not the SHA-256 of `feed.json`. Newer `fe4e2df` has a refreshed feed with additional fields/providers; this worktree was intentionally not rebased. The runner preserves unknown original row fields and derives metadata from whichever rows its caller supplies. Root can replay this draft against the refreshed feed after reconciliation.

## Verification

Using the existing Python 3.12 environment with pytest plugin autoload disabled and a fresh temporary base:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH='C:\Users\abhin\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\site-packages'
& 'C:\Users\abhin\CAL_HACKS_13\cal-hacks-2026\agents\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider --basetemp 'C:\Users\abhin\CAL_HACKS_13\lane-a-replay-driver\.pytest-tmp-final' agents/buyer/test_replay.py agents/buyer/test_state.py
```

Result: **50 passed in 5.18s**. The 3-day synthetic SIM clock advances without sleeping and the test enforces a sub-60-second ceiling. Network and MerchantSim/charger sentinels are enabled in the driver-only test. `git diff --check` passed.

Windows required normal pytest temp ACL permissions; no sandbox protections were disabled.
