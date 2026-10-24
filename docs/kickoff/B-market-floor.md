# Lane B: Market and screens (SpacetimeDB, Next.js, three.js, Cartesia voice UI)
Paste 00-shared.md first, then this.

## PIVOT NOTE (Fri 21:00: restaurants to PC builders)
**Vedant: your work on branch lane-b-market-floor carries over. Do not redo it.** Read it first: market/rules (sealing, floor, redaction, scoring, approval with idempotency, split-order optimizer, outcomes), the SpacetimeDB hello module (market/spacetimedb, scripts hello.mjs and hello.py), and your contract proposals (SpecCard, SupplierTerms, OrderPlan, ReceivingEvent, QualityRecord, FloorEvent v2, Bid.lines[].offered_spec, OrderPlan.advocate).
**What carries over unchanged:** sealing and anti-snipe, the floor price, redaction, approval-before-payment with idempotency (the voice yes from the Cartesia call is one more way to get an approval_id), the optimizer (subset enumeration plus minimum repair; free-shipping thresholds and shipping fees now do the work supplier minimums did), the two savings numbers kept separate, the SpacetimeDB module and its Node and Python call path, FloorEvent v2.
**What to rename or adjust (domain terms only):**
- types.ts: NeedItem `grade` becomes `condition` (new, open-box, refurbished, used) and `pack_size` becomes `variant` (retail or OEM, cooler included or not, model number); `unit` stays "each". SpecCard `grade`, `pack_size`, `case_count` follow (drop case_count or set it to 1). Add optional `attrs` (socket, chipset, ram_type, tdp_w, length_mm, height_mm, form_factor, connectors) so Lane C's fit checker can read SpecCards. `supplier_id` can stay in code; say "seller" in UI and docs.
- scoring.ts: `checkLineSpec` keeps its logic, and also disqualifies a line whose offered condition is not allowed (an open-box part against a "new" need). Add `offered_condition` beside `offered_spec` (backward compatible).
- SupplierTerms: keep `delivery_fee` and `free_delivery_over` (call them shipping in UI); `min_order_value` is usually 0 for PC sellers (keep the field); `cutoff_time` and `delivery_days` become ship-by time and estimated delivery days; add `return_window_days`. Add sales tax as a labelled line in landed price only if Lane C supplies it (optional, do not block on it).
- outcomes.ts: `recallsBlocked` text says "openFDA food enforcement"; change to CPSC. `BASELINE_ORDERING_MINUTES_PER_WEEK = 90` is a kitchen assumption: rename to a per-build research-time assumption and set its value from interviews, not from the old 90. `creditsCaptured` becomes returns and refunds captured. `hoursSaved` wording: "hours of research and comparison".
- **`ourFee` with `FEE_RATE = 0.15` and `FEE_CAP_PER_MONTH = 299` is a restaurant-era pricing model and pricing is an OPEN decision (see 00-shared.md).** Keep the function, move both numbers to config, and stop showing the fee on the builder screen until Vidyut rules.
- Test fixtures use Sysco, romaine, onions and produce names (optimizer.test.ts and others): swap them for neutral PC names (Seller A, Seller B, a CPU, a board, a PSU, a keyboard). Keep every test's logic; the property tests still hold.
- contracts: log the rename in docs/CHANGES.md (Need and SpecCard fields above, UsageRecord and Forecast renamed to DemandRecord and TrendSignal, owned by Lane C).
**First 3 things to do now:**
1. Make the renames above in one small PR (types, scoring, outcomes, fixtures, contracts) with all tests still green; post the SHA on docs/BOARD.md.
2. Add a PC optimizer test: Seller A is cheapest on the CPU and board but its free-shipping threshold is missed; moving the keyboard to Seller A costs a little more per line and saves the shipping fee. The toggle "cheapest per line" versus "optimizer" must show this.
3. Spacetime go or no-go at Fri 23:00 as planned (Convex fallback); then wire the builder view (post a brief, watch bids land live) to the module.

## GOALS TO SAT 10:00 (TALKABLE PROGRESS: the second round of sponsor and judge feedback)
1. By Fri 22:30: the rename PR (condition, variant, attrs, CPSC wording, fee as config, neutral fixtures) is merged with all market/rules tests green. Done-check: test run output pasted on the board, SHA posted.
2. By Fri 23:00: Spacetime go or no-go made and posted; the hello module is extended with needs, bids and orders tables. Done-check: a Need posted from Python shows in the web shell.
3. By Sat 03:00: the builder view shows live bids landing, the split plan with both toggles, and the advocate card. Done-check: two laptops show the same auction.
4. By Sat 07:00: the 3D floor shows a Need, sealed bids, a rejected bid and an order, each animation tied to a market row (click a character to see its row). Done-check: unplug the market and the floor goes still.
5. By Sat 09:00: voice approval screen (in-browser call fallback first) and the seller dashboard with a demand trend panel fed by Lane C's series, labelled SIM where it is. Done-check: a screen recording of the call screen and the dashboard.
6. By Sat 10:00: every screen has its LIVE, MIRROR or SIM badge and the footer RunMode. Done-check: Vidyut walks the screens and finds no unlabelled number.

You own market/ and web/. Goal: one live shared market everyone sees, and the 3D floor as a view on top of it.

Tasks in order:
1. SpacetimeDB module: tables for needs, bids, claims, verdicts, orders, personas, owned parts (read-only for you; Lane A owns the logic), voice approvals; reducers post_need, place_bid, counter, close_auction, attach_verdict, attach_claim_check, record_approval. Auction rule: sealed reverse auction with a deadline; best bid by landed price minus perks value, ties to verified claims, wrong spec or condition disqualifies. Unit-tested (done on your branch). If the module blocks you past Sat 00:00, fall back to Convex and tell the board.
2. Builder web view: post a build brief, watch bids land live, see advocate warnings, see the split plan, approve (mirrors the ASI:One flow for the big screen). Leads with outcomes: hours of research saved, dollars saved, each with "how we computed this". Trust visible: signature verified, claims checked, seller stability verified, seller record.
3. Voice approval UI (new, with Lane D): the call screen shows the deal being read, the live transcript, the yes or no answer and the recorded approval before payment. Fallback: in-browser voice call, labelled as such.
4. Seller dashboard: orders won and lost with the reason (price, condition, shipping fee), demand and trend intelligence (anonymized aggregates with a minimum group size, categories and brands up or down, price points where demand went unfilled; fed by Lane C's trend series), wind-tunnel results, ledger summary, "cost of this auction".
5. 3D Bidding Royale floor (three.js or react-three-fiber), built from the start: a market square with stalls; each seller agent is a rigged low-poly character (free CC0 characters with idle, haggle, cheer, sulk animations), speech bubbles show live bids, the advocate stands by the builder, the Shield guard drags blocked agents out. Every motion is driven by market state only (FloorEvent v2 traces to a row). About 8 characters on screen; 2D sprites are an emergency fallback only.
6. Persona voices: each persona speaks its bid with its own Cartesia voice (cache audio per bid; mute toggle). Tier 1; the approval call is Tier 0 and shares the Cartesia setup.
7. Receiving screen: photo of each delivered box, the spec it is checked against, accept or reject, and the seller's quality record updating live.
8. Optional hardware terminal: camera scan plus a touch screen showing bids; fallback is a webcam scan in the browser.
Done when: two laptops see the same auction and the same floor in real time, the floor never shows anything the market did not record, and the two judge toggles ("cheapest per line" versus "optimizer", "advocate off") work.

## Decided Fri 20:30 (still holds)
- Build the 3D floor from the start (Vidyut's call), drawn only from market state; 2D sprites only as an emergency fallback. The builder view, receiving screen and the two judge toggles still ship in Tier 0 or 1.
