# Lane B: Market and screens (Spacetime, Next.js, the Lot Wall, three.js)

**Owner: Vedant.** Paste 00-shared.md first, then this. You own `market/` and `web/`.

## SETUP (do this first)
1. Your branch is `lane-b-market-floor`. Clone and switch (if the branch does not exist yet, create it with `git checkout -b lane-b-market-floor`): `git clone https://github.com/vs-githjk/cal-hacks-2026 && cd cal-hacks-2026 && git checkout lane-b-market-floor && git pull origin main`
2. Copy `.env.example` to `.env` and fill only the keys this lane needs: SPACETIMEDB_URI, CARTESIA_API_KEY, CARTESIA_AGENT_ID (call screen and later persona voices). Ask Vidyut for values; never paste a key in chat, a doc or a commit, and never commit `.env`.
3. You own `market/` and `web/`. Touch other lanes' folders only through `contracts/` (log changes in `docs/CHANGES.md`).
4. Read `docs/kickoff/00-shared.md`, then this file.
5. Open a PR to main per finished item, small and often. Never add Co-Authored-By.
6. Details live in `docs/`, `contracts/` and the hub page: https://claude.ai/artifact/Hjrg6QgJ8FgdmkoEAaLCeU
7. Vedant, your branch already has commits: run `git pull origin main` and resolve any conflicts before you start new work.

## Mission

One live shared market everyone sees, and the screens that make the five beats visible: the goal card and notification feed, the sealed round with origin badges, the review card with the word-pair code, and the seller's loss report. The Lot Wall is a later item, built only once the core loop works. Planned load: 11.0 h to Sat 10:00 (the tightest lane), 14.0 h to Sun 03:00 (25.0 h total, an equal share). Use the slip ladder early; do not wait for the gate. If you cannot finish an item, pass it back in the team chat and it moves to whoever is ahead.

## Vedant's existing lane-b work carries over

Do not redo it. Branch `lane-b-market-floor`: market/rules (sealing and anti-snipe, floor, redaction, scoring, approval with idempotency, split-order optimizer, outcomes), the SpacetimeDB hello module and its Node and Python call path, your proposals SpecCard, SupplierTerms, OrderPlan, ReceivingEvent, QualityRecord, FloorEvent v2. Finish the rename PR in the first hour inside b1: NeedItem `grade` becomes `condition` (new, open-box, refurbished, used), `pack_size` becomes `variant`; SpecCard gains `attrs` (socket, chipset, ram_type, tdp_w, length_mm, height_mm, form_factor, connectors) so Anoop's fit checker can read it; `recallsBlocked` says CPSC; fee numbers move to config (never hard-coded); fixtures use neutral names (Seller A, a CPU, a PSU); all tests stay green. Add `origin` (LIVE, MIRROR, SIM) and `source` to Bid and Claim. Post the SHA on docs/BOARD.md.

## BUILD ORDER TO SAT 10:00 (11.0 h; start Fri 21:45)

1. **b1 Spacetime reducers. 3.0 h, done by Sat 00:45.** Sealed round, floor enforced in the reducer, flat fee (never feeds ranking), approval-before-payment with idempotency on the mandate hash (the invariant: no payment row without an approval row for the same hash, tested in CI; Vidyut reviews). Includes the rename PR and the Fri 23:00 go or no-go (Convex fallback, post it). Done-check: a Need posted from Python shows in the web shell; the CI invariant test passes; the go or no-go line is on the board.
2. **b2 Allowance ladder reducer (moved from D). 1.0 h, done by Sat 01:45.** Allowance starts at $0, so the first buy always calls; each clean receiving check raises it. Inside the allowance, small buys auto-approve with a receipt. For IT buyers, each seat has an allowance and the requester can never be the approver. Done-check: reducer tests: first buy requires a call; one clean receiving event raises the allowance; requester cannot approve.
3. **b3 Goal state machine, reservation ledger, throttle, quote TTL. 2.0 h, done by Sat 03:45.** States ACTIVE, HUNTING, HOLD_FOR_CALL, DONE, EXPIRED, PAUSED; deadline passed means EXPIRED plus a notification. Budget reservation ledger (reserve before a deal is offered; release on EXPIRED or refund). Feed throttle: one event per class per 10 minutes plus a daily digest; only HOLD_FOR_CALL pushes. Call cooldown: 1 per goal per 30 min, 3 attempts per deal, then PAUSED; quiet hours 22:00 to 08:00. Quote TTL 10 min. Done-check: tests for each rule; two goals cannot reserve the same money; an expired goal notifies.
4. **b4 LossReport with banding. 0.5 h, done by Sat 04:15.** Gap in bands (within 5, 10, 20 percent), reason as a category plus cited source, never thresholds or model details; rate limited per seller. Done-check: a closed round emits a LossReport per losing seller, with no raw numbers in it.
5. **b5 Buyer screen. 2.0 h, done by Sat 06:15.** Goal card, notification feed, the review card with the word-pair code display and the written rule "goal cap is the ceiling to hunt under; allowance is what it may spend without a call", plus the card line "we never ask for anything but the code on this screen". A labelled typed-code fallback bound to the same mandate. Origin badges and the fit and veto reasons from Abhinav's AdvocateCard. Done-check: two laptops show the same round; a typed code approves the same mandate the call would.
6. **b6 Seller screen. 1.0 h, done by Sat 07:15.** Every seller shown is a Fetch.ai uAgent (fully agentic). Pooled lot placeholder (SKU, quantity, ceiling band, deadline only), real requests, the loss report with strategy diff and Claude's "what to change". Done-check: a losing seller sees its banded gap and reason with the source link.
7. **b7 Minimal 3D floor mirroring rows. 1.5 h, done by Sat 08:45.** Every motion traces to a market row (FloorEvent v2); click a character to see its row. About 8 characters. Done-check: unplug the market and the floor goes still.
8. **08:45 to 10:00 (slack):** every screen has its LIVE, MIRROR or SIM badge and the footer RunMode; Vidyut walks the screens and finds no unlabelled number.

## THEN TO SUN 03:00 (14.0 h; clock times are targets)

Order: the five beats and Hyphenate first, then the Lot Wall and the extras once the core loop works (demo path green, Sat 14:00). The Lot Wall is never hardcoded.

1. **b12 Fold in feedback, polish and demo path. 3.0 h, Sat 10:00 to 12:30 and Sat 14:30 to 15:00.** Fold in the Sat 10:00 sponsor and judge feedback, run the five-beat path on the deployed build (Vidyut checks the Sat 14:00 gate with what exists), screens at stage size.
2. **b10 Hyphenate: PO, credit memo, audit page. 2.0 h, Sat 12:30 to 14:30 (gate Sat 16:00).** PO number field on the goal and the deal; the requester cannot approve (already in b2); a credit memo row written when the receiving check fails; the audit page is a filtered view of the event table showing for each call the data, rule or person behind it. Uses Anoop's `three_way_match` (c14, done 12:30). If the demo path is red at 14:00, stop and ship the slip form. Done-check: a seeded IT order shows PO, a failed match writes a credit memo, the audit page lists each step.
3. **b13 Lot reducer with quantity tiers. 1.5 h, after Sat 14:00 green, Sat 15:00 to 16:30.** Pools by exact SKU and condition. Sellers bid a price ladder by quantity (1, 10, 25, 50). The lot closes at its deadline at the highest tier reached. Mandate binds the tier price reached and a max price; an unfilled pool falls to the lower tier and, if above the ceiling, to a call. Output shape is aggregate only (SKU, quantity, ceiling band, deadline), never a buyer name or goal text. Done-check: a test where requests pool and a bid slides to the next tier; a test that no buyer field appears in the seller-bound shape.
4. **b8 Lot Wall view and split toggle (a later item). 3.0 h, Sat 16:30 to 19:30 (gate Sat 22:00).** Left Joe's universe (one card), right the wall of bricks (Joe's gold REAL, the rest grey SIM), the vertical price ladder with sealed bids sliding down tiers, each with its origin badge; a key folds the wall to one gold brick. Drawn from the lot reducer's rows and Anoop's wind-tunnel builders (SIM), never hand-typed. Stage line: "This is one real order, Joe's. When many orders pool, this is what a seller sees. One or two bids here are real, the rest are labelled simulated." Done-check: the wall steps through the tiers on live lot state; the badge counts match the rows.
5. **b9 3D floor extras. 2.5 h, after Sat 14:00 only, Sat 19:30 to 22:00 (hard stop Sat 22:00).** Slip form: 2D row mirror.
6. **b11 Persona voices. 2.0 h, after Sat 14:00 only, Sat 22:00 to 24:00.** Each persona speaks its bid with its own Cartesia voice, audio cached per bid, mute toggle. Slip form: text bubbles.
7. Rolling to Sun 03:00: fixes from rehearsals.

Coming later, or only if time remains after the agentic path: a real non-agent seller side. It is not in your list.

## Slip ladder minimum forms (your items)

- Lot Wall (Sat 22:00): a plain lot table with the tier ladder, read live from the lot reducer, no wall animation. Never a hardcoded picture.
- Hyphenate (Sat 16:00): PO, three-way match and audit page on seeded data, labelled SIM.
- 3D floor extras and persona voices (Sat 22:00): 2D row mirror plus text bubbles.

## What you get and hand over

- **From A (Abhinav):** Need and Goal writes, bids with origin, AdvocateCard JSON, goal events, strategy diffs and "what to change" lines, the CRS band for the greyed-out seller.
- **From C (Anoop):** SpecCards, mirror snapshot ids, wind-tunnel builders for the wall, scoreboard queries, `three_way_match`.
- **From D (Vidyut):** the Mandate shape and hash, the code words, VoiceApproval rows, the code display copy, Shield verdicts to show quarantine.
- **To A:** reducers' tables and reducers (rounds, goals, lots), the feed API.
- **To C:** FloorEvent rows, lot state, the scoreboard feed.
- **To D:** the reducer invariant to review; the review card where the code appears; the call screen.

## Sponsor hard requirements you own

Spacetime (the portal's "AI systems coordinating in a persistent world state": every agent and screen shares one world; the floor and scoreboard subscribe to it; README says the Python bridge is the single point of failure and what the Convex fallback is). Hyphenate's PO, audit page and credit memo. The Cartesia call screen and review card (with Vidyut's core). The LIVE, MIRROR and SIM badges on every screen.

## Sun 03:00 to 09:00

Two hours on call for fixes, then sleep in shift. Anoop runs integration; take his merge order.
