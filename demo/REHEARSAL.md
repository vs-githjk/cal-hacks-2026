# Local rehearsal with a real call

One full run on your own Mac: a local market, the live build on the paired `/buyer` screen, and one real approval phone call. Everything here is local; nothing touches Maincloud, Vercel or a shared database. Env var NAMES only appear below, never values.

What you will see: the build panel on `/buyer` switches from the labelled "SIM sample, not this market" build to the live run as soon as `demo/build.py` writes its first step. The panel reads `GET /v1/build` on the local agent feed, which serves `demo/out/build-view.json` (or `BUILD_VIEW_DIR`). Prices are tagged `[LIVE]`, `[MIRROR]` or `[SIM]` per row exactly as the run recorded them. Payment is the SIM stub unless you pass `--stripe`.

## Before you start
- Repo root below is the checkout you run from (`cd` into it first; every path here is relative to it).
- `spacetime` CLI installed (`~/.local/bin/spacetime`), Node and `npm ci --prefix market` and `npm ci --prefix web` done once, python3 with `fastapi` and `uvicorn` (the agent feed's own needs).
- The call needs these names set, either in your shell or in the env file `build.py --env-file PATH` reads (default `../lane-d/.env` next to this checkout): `CARTESIA_API_KEY`, `CARTESIA_AGENT_ID`, `APPROVAL_CALL_TO` (your own phone, E.164), `APPROVAL_SECRET` (random, 16+ characters), and optional `CARTESIA_PHONE_NUMBER_ID`, `APPROVAL_BUYER_NAME`. For `--stripe` also `STRIPE_SECRET_KEY` (must be an `sk_test_` key, else the SIM stub runs). Optional price re-check: `BRIGHT_DATA_API_KEY`.
- Trap: for `SPACETIMEDB_SERVER`, `SPACETIMEDB_HTTP` and `SPACETIMEDB_DB` the env file WINS over your shell (`demo/market_target.py`). If that file points at Maincloud, `build.py` will too. Step 9 prints a market line; stop (Ctrl-C) if it does not say `on local SpacetimeDB (spacetime -s local)`.

## Steps, in order

1. Start a local SpacetimeDB (terminal 1, leave running):
   ```
   spacetime start --listen-addr 127.0.0.1:3000
   ```
2. Publish the market module to it (terminal 2, from the repo root). `-s local` is your own scratch server on 127.0.0.1:3000:
   ```
   spacetime publish -s local -p ./market/spacetimedb --yes=all tech-bazaar
   ```
3. Create the agent identities and roles (once per database, as the module owner, which is your spacetime CLI identity). Writes `.tokens/` (gitignored):
   ```
   python3 market/scripts/setup_roles.py
   ```
4. Load the demo data. This is also what creates the buyer's pairing code, and the market README's run block omits it:
   ```
   spacetime call -s local tech-bazaar seed_demo
   ```
5. Read the pair code:
   ```
   spacetime sql -s local tech-bazaar "SELECT code FROM pair_code"
   ```
6. Start the agent feed (terminal 3), the server the build panel polls. It binds 127.0.0.1 and allows only localhost pages (CORS):
   ```
   python3 -m uvicorn agent_feed:app --app-dir scripts --host 127.0.0.1 --port 8790
   ```
   Check it: `curl -s http://127.0.0.1:8790/v1/health` answers `{"ok":true}`, and `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8790/v1/build` answers `404` until a run wrote a view (a stale file from an old run answers 200: see Reset).
   If you want the view somewhere else, set `BUILD_VIEW_DIR` for the feed and pass the same folder as `--out-dir` to `build.py`.
7. Start the web app in PRODUCTION mode (terminal 4). `next dev` did not hydrate in headless tests, so use the production build:
   ```
   cd web && NEXT_PUBLIC_SPACETIMEDB_URI=ws://127.0.0.1:3000 NEXT_PUBLIC_SPACETIMEDB_DB=tech-bazaar npm run demo
   ```
   (`npm run demo` is `next build && next start -p 3100`.) The `NEXT_PUBLIC_` names are baked in at build time, so set them on this command and rebuild if you change them. `NEXT_PUBLIC_AGENT_FEED_URL` is not needed: a page on localhost polls `http://127.0.0.1:8790` by default.
8. Pair `/buyer`: open http://localhost:3100/buyer, enter the code from step 5. The build panel shows the SIM sample, labelled as such.
9. Run the build with the real call (terminal 2, repo root). `--reset` calls `reset_demo` first (wipes needs, goals, rounds; keeps roles and the pair code, so you stay paired):
   ```
   python3 demo/build.py --reset --live-call
   ```
   Add `--stripe` only for a Stripe TEST charge per part after the call approves (`--stripe` without `--live-call` is refused).
   Check the console's first lines: `market: tech-bazaar on local SpacetimeDB (spacetime -s local)`, `live call: ONE call to +1*******...` (your number, masked) and `BuildView: ... written to .../demo/out/build-view.json`. A "Cartesia NOT configured" line means the names above are missing: the build above the allowance is then denied and nothing is paid.
10. Watch `/buyer`: within about 3 seconds (the panel polls every 3 s) the SIM label goes away and the rows fill as rounds open, knock out and lock; the fit check can show one clash and a re-plan. The run takes about 80 s of rounds, then the re-check, then the call. The console prints the approval code for the call: read it, answer the phone and follow the call's script. Only the call approves a build above the allowance ($250 per buy, $500 per month by default; `--per-buy`, `--period-limit`).

What the panel never shows, by design: mandate hashes, payees, per-mandate amounts, the approval code, your phone number, the allowance rule or the call/approval/receipt lines. `GET /v1/build` strips them; `demo/out/build-view.json` on disk keeps the full view.

## Reset between runs
- Same market, new run: run step 9 again. `--reset` calls `reset_demo` (SIM data only) and keeps roles and your pair code.
- The panel keeps showing the LAST run's file until the next run writes its first step. To make it fall back to the SIM sample right away, delete the old view: `rm demo/out/build-view.json demo/out/build-view.steps.jsonl`.
- Pair code lost or locked: `spacetime call -s local tech-bazaar reissue_pair_code '"vidyut"'`, then step 5 again.
- Wipe everything (roles, pair code and data) and start clean: stop the server (Ctrl-C in terminal 1), start it again, and redo steps 2 to 5. Or publish over the same server with `spacetime publish -s local -p ./market/spacetimedb --delete-data --yes=all tech-bazaar`, then redo steps 3 to 5 (roles and pair code are gone).
- A refused or silent call changes nothing on the market's money side: nothing is paid. Re-run step 9.

## No phone needed (dry check of the panel)
Run `python3 demo/build.py --reset` without `--live-call`: the build stops before any call and pays nothing, and the panel still shows the live rounds. `python3 demo/build.py --dry-run --out-dir <folder>` writes a view offline with no market at all (point `BUILD_VIEW_DIR` at that folder to see it through the feed).
