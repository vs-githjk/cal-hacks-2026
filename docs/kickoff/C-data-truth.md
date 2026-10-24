# Lane C: Data, truth, wind tunnel, then integration (Apify, fit checker, merchant simulator, Shield product layer)

**Owner: Anoop.** Paste 00-shared.md first, then this. You own `data/` and `sim/`, the merchant simulator in `pay/`, and the product layer of `shield/` (OpenAPI, keys, meter, client, bench). **From Sun 03:00 you are the integration owner for 6 hours.**

## SETUP (do this first)
1. Your branch is `lane-c-data`. Clone and switch (if the branch does not exist yet, create it with `git checkout -b lane-c-data`): `git clone https://github.com/vs-githjk/cal-hacks-2026 && cd cal-hacks-2026 && git checkout lane-c-data && git pull origin main`
2. Copy `.env.example` to `.env` and fill only the keys this lane needs: APIFY_TOKEN, ANTHROPIC_API_KEY, STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, CRS_API_KEY (test identities), CARTESIA_API_KEY (Photon spike), TIGER_DATA_SERVICE_URL (after Sat 14:00); BRIGHT_DATA_API_KEY only after Vidyut approves the spend. Ask Vidyut for values; never paste a key in chat, a doc or a commit, and never commit `.env`.
3. You own `data/`, `sim/`, the merchant simulator in `pay/`, and the Shield product layer in `shield/`. Touch other lanes' folders only through `contracts/` (log changes in `docs/CHANGES.md`).
4. Read `docs/kickoff/00-shared.md`, then this file.
5. Open a PR to main per finished item, small and often. Never add Co-Authored-By.
6. Details live in `docs/`, `contracts/` and the hub page: https://claude.ai/artifact/Hjrg6QgJ8FgdmkoEAaLCeU

## Mission

Put the real web inside the market and make every claim checkable and every fit decision come from code. Then prove the claims we make: the wind tunnel (learning sellers against a fair frozen control), the attack corpus and its held-out and voice cases, the scoreboard, and Shield as a product Armadin can point a swarm at. Planned load: 10.25 h to Sat 10:00, 14.0 h to Sun 03:00 (24.25 h total, an equal share), then integration from Sun 03:00. If you cannot finish an item, pass it back in the team chat and it moves to whoever is ahead. You carry beat 2's truth (fit by code, the claim-check source) and the corpus behind beat 3.

## BUILD ORDER TO SAT 10:00 (10.25 h; start Fri 21:45)

Apify and CRS credits are in hand. Record cost per run anyway. Test every required domain from the cloud session in the first 30 minutes.

1. **c1 Apify mirror Actors. 2.0 h, done by Fri 23:45.** Test the actors already found (slugs verified Fri 20:56): Newegg `kawsar/newegg-product-scraper`, PCPartPicker `lulzasaur/pcpartpicker-scraper`, Micro Center `sian.agency/microcenter-product-scraper`, Best Buy `benthepythondev/bestbuy-scraper`, B&H `shahidirfan/B-H-Photo-Scraper`, eBay sold `caffein.dev/ebay-sold-listings`, eBay live `memo23/ebay-search-scraper-ppe`, Amazon `junglee/Amazon-crawler`. Mirror listings for the demo set (a GPU with 3 SKUs, a PSU, a case, about 12 parts and 2 peripherals) with title, model number, condition, price, shipping, seller, return policy, stock. Public data only. Write actor ids and cost per run in data/README.md. Done-check: one real listing JSON per working actor committed, with snapshot id and date.
2. **c2 Fit checker, hand tables, 40 hand-checked builds, 20 tests. 3.0 h, done by Sat 02:45.** Pure functions on `docyx/pc-part-dataset` (MIT; data was scraped from PCPartPicker, flag data rights): CPU to board socket and BIOS note, RAM generation and speed, PSU wattage with headroom and GPU connectors, GPU length against case, cooler height, form factor, storage. Add two tables the dataset lacks (CPU microarchitecture to socket, GPU chipset to board power). Write 20 failing tests first from real combinations, including AM4 versus AM5. Freeze 40 hand-checked builds against manufacturer spec sheets before you tune the checker; "false OK" (said it fits, it does not) is reported on its own. Unknown means "uncertain". Mock the same I/O for Abhinav now. Done-check: 20 tests pass; the 40-build accuracy and false-OK count are in data/RESULTS.md.
3. **c3 Claim-check Actor. 2.0 h, done by Sat 04:45.** Given a Claim (stock, shipping, price, condition, warranty), check it against the live page and return verified, unverified or false with an evidence URL, `checked_at` and method. Real stores get neutral wording ("the price claim did not match the price history", "differs from the listing at time T", "could not verify"). Abhinav publishes it to the Store (a14). Done-check: three claims return false with evidence URLs on our hosted pages.
4. **c4 Hosted liar pages. 1.0 h, done by Sat 05:45.** "Honest Hal" and "Shady Sam" with a lie toggle: a fake "was" price, an open-box part listed as new, a wrong socket; works on any wifi. Also a page with an injected instruction and a payee swap for beat 3. Done-check: the claim check flags each lie; the injected page exists for Vidyut's Shield test.
5. **c5 Merchant simulator, TAP verification, Stripe test charge, replay failure (moved from D). 1.5 h, done by Sat 07:15.** Verifies Visa Trusted Agent Protocol HTTP message signatures (Visa and Cloudflare open spec), runs the Stripe test charge on a Visa test card (4242 4242 4242 4242 is a Visa), checks the mandate hash, and fails a replayed or altered mandate with the reason shown. Say "conformance, verified by our merchant simulator". Done-check: a valid mandate charges; a replayed one and an altered amount both fail on screen.
6. **c6 Photon SIP spike. 0.75 h, done by Sat 08:00, decision Sat 09:00.** Photon SIP first (the team used it at LA Hacks and won its voice prize), Cartesia over SIP. Test numbers only, never a real person's number in the repo; store a reference in env. Post go or no-go on the board at 09:00. Done-check: a test call connects and speaks, or "not working, in-browser is the path" posted.
7. **08:00 to 10:00 (slack):** first measured numbers (fit accuracy, price spread on real parts against a dated baseline) in data/RESULTS.md, including results that show no effect; write the 10 voice attack cases (below) ahead of c8 if time allows.

## THEN TO SUN 03:00 (14.0 h; clock times are targets)

1. **c8 20 held-out attacks and 10 voice attacks. 1.5 h, Sat 10:00 to 11:30.** You write them so Vidyut does not grade himself. The 20 held-out attacks are written before Shield's rules are tuned. The 10 voice cases: wrong code, replayed code, "yes" without code, other amount, silence, injected seller text in the "why" answer, noisy audio, second approval, expired code, other deal's code. Done-check: files committed with expected verdicts; Vidyut runs the voice set Sat afternoon.
2. **c14 `three_way_match`. 1.0 h, Sat 11:30 to 12:30.** `three_way_match(po, listing_claim_and_page, delivery_check)` returns match or the named mismatch ("sources disagree: page says open box"). Reuses the receiving check and the claim-check Actor. Vedant's Hyphenate audit page calls it. Done-check: a test returns each named mismatch.
3. **c9 Shield OpenAPI, keys, meter, client, `shield-bench`, docs page. 2.5 h, Sat 12:30 to 15:00 (gate Sat 22:00).** Versioned API `POST /v1/shield/screen`, `/verify-agent`, `/check-claim`, `/verify-mandate` with OpenAPI, example curl and a docs page; API key per caller, rate limit per key, usage counted per call (the pricing unit; price set after a design partner); a 20-line client; `shield-bench` replays the corpus and any attack file Armadin hands us and prints block rate, false-block rate and p95 latency, with new attacks credited. Block rate reports three columns: dev (30), held-out (20), adaptive (Claude-generated after the rules froze). Logging stores hashes and rule ids, not bodies. Done-check: `shield-bench` prints the three columns and p95; a key-less call is refused.
4. **c10 `/check-claim` endpoint. 0.5 h, Sat 15:00 to 15:30.** Wraps the claim-check Actor so a third party gets the advocate's best feature. Done-check: curl returns verified, unverified or false with evidence.
5. **c11 Dated baselines from 2 sources plus the recorded price feed. 1.0 h, Sat 15:30 to 16:30.** Two dated sources within 24 h before a buy (Apify plus Bright Data; Bright Data spend needs Vidyut's OK, else the second source is eBay sold). The recorded price feed (with date range) feeds Abhinav's sim clock (a15, Sat 21:30). Done-check: baseline rows with timestamps and URLs; the feed file with its dates.
6. **c7 Wind tunnel runner. 3.0 h, Sat 16:30 to 19:30 (gate Sat 20:00).** 50 parametric builders (budget, haggle rate, fit strictness, hostility) and 50 attacks (published cases plus Claude variants), two arms with separate outputs: (a) learning arm, benign builders only; (b) attack arm against the market and Shield, no learning measured. A frozen hand-tuned control seller, written down in the repo before training. 5 seeds, mean and range shown (say 3 if only 3). At least 2 of 6 builder archetypes held out; lift per archetype; negative lift is shown. Uses Abhinav's a7 strategy (done by Sat 14:00). Claim wording: "learning sellers beat a fair static seller by X points on held-out simulated builders (n, 5 seeds, interval); this is a simulator we built, not the market." Done-check: output with seeds, intervals and held-out archetypes; committed control definition.
7. **c12 Scoreboard view, "Hack the market" console, metric queries. 2.5 h, Sat 19:30 to 22:00.** Four tiles, each with count, date range and LIVE, MIRROR or SIM label: dated verified savings (real and SIM columns separate; negative shown), attack block rate (and false blocks on 50 benign listings, judge attempts counted pass or fail, voice attacks tagged "voice"), fit accuracy (with false OK), seller learning lift (SIM). The console is a text box that sends a hostile listing to `/v1/shield/screen` and shows the verdict and the rule; every attempt counts. Done-check: tiles read live queries; a judge attempt appears in the count.
8. **c15 Tiger Data time series. 2.0 h, after Sat 14:00 and after the fit checker is green, Sat 22:00 to Sun 00:00 (gate Sun 00:00).** Hypertables for price observations and rounds. Slip form: plain queries with the honest note that Postgres could do this.

## Slip ladder minimum forms (your items)

- Wind tunnel (Sat 20:00): 10 builders, 3 seeds, same two numbers, labelled SIM.
- Shield API extras (Sat 22:00): keys and schema stay; metering as a counter; `shield-bench` as a script.
- Tiger Data (Sun 00:00): plain queries.
- Photon (Sat 09:00, then Sat 18:00): in-browser call, typed fallback code.

## SUN 03:00 TO 09:00: INTEGRATION OWNER (6 h)

You run the demo path end to end three times (start 03:15, 05:00, 07:00), own the merge order (hot fixes first, then labels, then docs), own the README live versus mock table and the claims list check (every claim present tense only if built, proven by a file or a run), and run the deploy checklist (Vidyut approves any deploy and any restart). You do not add features. Keep fallback recordings of each beat ready for judging.

## What you get and hand over

- **From A (Abhinav):** the a7 strategy for your runner (by Sat 14:00); `/verify-agent` for the Shield docs; the claim-check Actor Store publish.
- **From B (Vedant):** FloorEvent and lot state; the scoreboard feed target; the Hyphenate page that calls `three_way_match`.
- **From D (Vidyut):** Shield's core (`/screen`, `/verify-mandate`, signed receipts, rules as files) and the 30 dev attack cases you wrap in the bench; the mandate shape for your merchant simulator.
- **To A:** the fit checker, SpecCards, mirrored offers, the claim-check Actor, the recorded feed.
- **To B:** wind-tunnel builders for the Lot Wall (a later item), scoreboard data.
- **To D:** the merchant simulator, hosted injected page, the 20 held-out attacks and 10 voice cases, the Photon decision.

## Sponsor hard requirements you own

Apify: mirrors and the claim-check Actor published (with Abhinav), cost per run documented, credits in hand. Visa: a merchant simulator that verifies TAP and fails replay. Armadin: the OpenAPI, the key and the `shield-bench` we hand them, with the three honest columns. Spacetime and Tiger Data: Tiger Data adapter only. CRS: you do not own the gate (Abhinav); you supply the sandbox test identities. Never put a number on research time, incompatibility rate or return rate (none found).

## Wording

Never call a real store a liar. Say "charges worth questioning", "the price claim did not match the price history", or "could not verify".
