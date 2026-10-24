# Tech Bazaar: shared kickoff (every teammate pastes this first, then their lane file)

Final version, Fri Oct 23 2026, written 21:30 to 21:50 PDT. Sources, newest wins: the "VIDYUT RULINGS, Fri 21:25" section of plan/idea-v2.md (law), plan/redteam-v2.md (lane table, slip ladder, hardened call), plan/judge-v2.md (five beats), plan/decisions.md. Deadline: Sun Oct 25, 09:00 PDT on Devpost. Team: Abhinav (Lane A), Vedant (Lane B), Anoop (Lane C), Vidyut (Lane D).

## THE IDEA

**Name:** Tech Bazaar (renamed from Tech Bazaar by Vidyut's final ruling, Fri night). Security API inside it: Bazaar Shield. The repo name stays cal-hacks-2026.

**Category line:** a refereed arena for agent commerce, starting with computer gear.

**One line:** Tech Bazaar is a buyer's agent for scarce, scam-prone goods. You give it a goal, seller agents bid for it, an advocate vetoes the traps with a source, and nothing is paid until you approve on a two-way voice call.

**Scope:** all computer gear (PCs, parts, laptops, monitors, peripherals). The demo hero is a GPU because GPUs are where scarcity and scams meet. The IT buyer view uses laptops and monitors. (LOCKED.)

**Reframe:** not "a shopping agent". It is a buyer's agent for goods that are scarce and where scams live, and a referee for the day the seller is also an agent, possibly a hostile one.

**30-second pitch:** An RTX 5070 Ti lists 49 percent over launch price (Capital & Compute citing Tom's Hardware, Sep 1 2026), and a 5090 once shipped from Amazon with the chip missing (reported, open the article before saying it). Tech Bazaar is a buyer's agent for this. You give it a goal: "this card, under $800, by Friday". It hunts for you and tells you after every step. Seller agents bid in a sealed round. Your advocate checks fit with code and every claim against the live page, and vetoes the cheapest bid when it is a trap, with the source. Above your allowance, it calls you. You can ask "why not the cheaper one?" and it answers aloud. Your spoken code signs that exact deal. Losing sellers get a loss report and their agents learn. Bazaar Shield, our security API, blocks agents that try to cheat. Everything on screen is labelled LIVE, MIRROR or SIM.

**Who it is for:** the demo hero is Vidyut, an upgrader whose agent remembers the rig (the rig data is labelled SIM). The first payer is the small IT buyer (a school lab, small office, esports cafe, club or small MSP) refreshing 10 to 50 machines. The other side is sellers: marketplace, used, refurbisher and local PC shop sellers (big-box retailers will not bid; say so). **Fully agentic: every seller is a Fetch.ai uAgent on Agentverse.** A real non-agent seller side (a shop with no agent) is listed as coming later, or only if time remains after the agentic path. Incumbents we are compared to: Amazon Business, CDW and Dell business stores (they do approvals and POs; they do not referee agent-to-agent deals or argue against a bad deal). **Naming these incumbents and the IT buyer's per-refresh pricing idea are finalized later** (Vidyut, after the first quotes); until then they live in Q&A only, not on slides. Never say "Windows 10 now": support ended Oct 14 2025.

## CORE LOOP and MULTIVERSE

**Core loop (LOCKED, 21:15): agents battle, both sides win.**
- **Buyer agents fight for the best verified price.** The buyer agent holds the goal, ownership memory and allowance. Its quality advocate (Claude, closed output schema) scores each bid, can veto the cheapest with the source, and never sees the fee.
- **Seller agents fight for the sale, and they learn.** Every seller is a Fetch.ai uAgent on Agentverse. Each bids from its owner's real listings and never below its floor (a reducer enforces it). After every round it gets a loss report: won or lost, the gap in bands (within 5, 10 or 20 percent), and the reason as a category plus the cited source (price, fit, condition, delivery, record, or the advocate's veto). It updates a small, inspectable strategy (price step, bundle, delivery promise, condition disclosure) inside its owner's rules. Claude writes the owner a one-line "what to change". It can never edit a listing's condition field.
- **The market referees.** Sealed bids, one flat fee for everyone, no pay for rank, Shield on every message, and an anonymous public record of closed rounds. Memory and allowances stay private.
- **Why both sides come back:** buyers save verified money and avoid traps; sellers learn faster than alone.

**MULTIVERSE (Vidyut ruling 1) and the Lot Wall.** The demo is one small universe: one order. The real market has many buyers whose requests pool. Mechanism: a need resolves to a shortlist of exact SKUs and conditions, then pools by SKU. Sellers bid a price ladder by quantity on the lot (for example 1, 10, 25, 50 units). The lot closes at its deadline at the highest tier reached. The buyer's mandate binds to the tier price actually reached and to a max price; a pool that never fills falls back to the lower tier and, if above the buyer's ceiling, to a call. Sellers see only SKU, quantity, ceiling band and deadline of the pool, never a buyer name or goal text.

**The Lot Wall is a later item, not a hardcoded screen.** Build it only after the core loop works (demo path green, Sat 14:00). It is drawn from real lot rows and labelled SIM builders, never typed by hand. Split screen. Left: Vidyut's universe, one card. Right: the seller's view of one pooled lot as a wall of bricks. Vidyut's brick is gold and labelled REAL; the rest are grey and labelled SIM. Beside it, a vertical price ladder: as bricks stack past each tier, the sellers' sealed bids slide down to the next tier price, each carrying its origin badge. A key press folds the wall into the single gold brick: "one universe".

**Origin badge on every bid:** LIVE (an outside Agentverse agent), MIRROR (our seller agent bidding from a real listing, with the listing URL and the floor), SIM (wind-tunnel builder). Clicking a bid opens its listing link.

**Stage honesty line (exact):** "This is one real order, Vidyut's. When many orders pool, this is what a seller sees. One or two bids here are real, the rest are labelled simulated." Never say "many buyers use it".

**Default if no real seller bids (Ruling 12, not yet confirmed by Vidyut):** the agent buys the best public listing and the card says "no seller bid, bought the public listing, earned nothing".

## GOALS NOT ORDERS (Vidyut ruling 3)

The person gives the agent a goal, not a one-shot order. Three goal types only: budget cap ("spend at most X"), part price by date ("this part under this price by this day"), build price by date ("assemble this build under this price by this day"; demo it on 3 parts: GPU, PSU, case). A goal is a typed object with states ACTIVE, HUNTING, HOLD_FOR_CALL, DONE, EXPIRED, PAUSED. A passed deadline means EXPIRED plus a notification, never a silent stop.

- **Notify after each step.** One event per class (deal found, bid in, veto, progress to goal), throttled to one per class per 10 minutes, plus a daily digest line. The in-app feed shows all; only HOLD_FOR_CALL pushes. Channels: in-app feed (default), an ASI:One message, and the call. No SMS or email is promised.
- **Call above the allowance.** One rule, written on the card: the goal cap is the ceiling the agent may hunt under; the allowance is what it may spend without a call. Above the allowance, even inside the cap, it calls. A new buyer's allowance starts at $0, so the first buy always calls. Each clean receiving check raises it.
- **Call limits:** at most 1 call per goal per 30 minutes, 3 attempts per deal, then PAUSED plus a notification. Quiet hours 22:00 to 08:00 by default (a deal waits, it does not call).
- **Budget reservation ledger** in the Spacetime reducer: a goal reserves before a deal is offered; release on EXPIRED or refund. Two goals never spend the same money.
- **Quote TTL 10 minutes** on every deal. The call re-reads the price just before dialing; a change over 2 percent restarts the card.
- **Time machine:** a standing hunt cannot run for days in a 3-minute demo, so a sim clock fast-forwards a recorded price feed, labelled SIM with the recorded date range. The first step of the live path uses real MIRROR data.

## THE FIVE BEATS

One thesis: **the buyer's agent argues for you and refuses to move money until you say yes, on a call, about one exact deal.** Five stage beats, in this order. Everything else is an adapter.

1. **Set a goal.** Vidyut tells the agent in ASI:One (web chat fallback rehearsed): "a GPU for 1440p that fits my case and PSU, under $800, by Friday". Ownership memory skips the PSU Vidyut owns and cites the entry. The goal card appears. (Lanes A, B)
2. **Sellers bid and the advocate vetoes a trap with a source.** Three seller agents bid in a sealed round (origin badges visible). The advocate vetoes the cheapest bid: "listed as new, the page says open box" with the link. Fit is decided by code. (Lanes A, B, C)
3. **Shield blocks an injected listing live.** A listing carries a hidden instruction or a payee swap. Shield quarantines it before the advocate sees it, and shows the rule that fired. A judge can try the same in the "Hack the market" console. (Lanes D, C)
4. **The two-way call approves above the allowance.** The deal exceeds the allowance, so the agent calls. Vidyut asks "why not the cheaper one?", the advocate answers aloud from its cited reason, Vidyut says the word-pair code from the screen, hears the amount read back, says "approve". Stripe test charge on a Visa test card under a Trusted Agent Protocol signed mandate. A replayed mandate fails on screen. (Lanes D, A, B)
5. **The seller's loss report and learning.** The losing seller receives its loss report (banded gap, reason, source), its strategy diff, and Claude's "what to change". Shown as one deterministic, replayable diff, with no trend claim unless the wind tunnel proves it. (Lanes A, B, C)

**Sat 10:00 (talkable progress, sponsor and judge feedback round 2):** all five beats run end to end on MIRROR plus SIM data, every number labelled, in-browser call, Shield on a typed injected listing. Vidyut runs it once without help. Each lane's "BUILD ORDER TO SAT 10:00" ends in this.

**At judging (Sun 10:30):** the same five beats, plus what the evidence plan earned: the real teammate receipt, real quotes, an outside agent bidding live, judges attacking the console, the Lot Wall if it was built, and the scoreboard with dated numbers. Use the stage honesty line exactly as written above.

## ADAPTERS (named, not extra beats)

An adapter is a named add-on to a beat, not a lesser sponsor (every sponsor is a main sponsor, see SPONSORS). It is shown in the demo as a labelled add-on. If it is not green at its gate, it ships in its minimum form (slip ladder below), never silently gone.
- **CRS** (identity and fraud on business sellers): admission gate. One business seller is greyed out with the reason. Sandbox test identities, band only, consent card. Individual used-part sellers are not credit-checked; they show by seller record (FCRA caution).
- **Hyphenate** (IT buyer purchasing): PO number field, requester cannot approve, three-way match (PO, listing claim and page, delivery check), credit memo on a failed receiving check, audit page.
- **IT fleet view:** fleet memory (every machine the org owns), per-seat allowance, requester never the approver.
- **Tiger Data:** time series behind dated savings and the learning curve. After Sat 14:00 only.
- **Also adapters:** Bright Data (second source for baselines), the open seller protocol with an outside agent, the scoreboard, the Lot Wall, persona voices and 3D floor extras (the Lot Wall, voices and extras after Sat 14:00 only). **Coming later, or only if time remains after the agentic path:** a real non-agent seller side, where a shop with no agent takes part by approving drafted bids by hand. It is not in the plan.

## SPONSORS: every sponsor is a main sponsor

Every sponsor below is a main sponsor and gets the same depth: each carries something in the loop, has a demo moment, a lane that owns it, and hard requirements we must meet. Where a sponsor's track text is not yet read, the entry says so; Vidyut or the owner re-reads the Live Site at kickoff and posts the exact text on the board.

**Fetch.ai** (Lane A)
- Carries: every buyer, advocate and seller agent is a uAgent on Agentverse (fully agentic); ASI:One is the buyer's front door; the open seller protocol lets an outside agent register and bid; Payment Protocol carries checkout; Interactive Cards show bids and the review.
- Breaks without it: no seller can join, the round opens with zero bidders, and the outside-agent proof is gone.
- Demo moment: beat 1 (the goal typed in ASI:One) and beat 2 (an outside agent's LIVE bid).
- Hard requirements: register at least one agent on Agentverse; Agent Chat Protocol; discoverable and usable in ASI:One; tool use or multi-agent orchestration; the primary workflow completes inside an ASI:One chat; public GitHub repo with run instructions; README lists every agent's name and address plus the innovationlab and hackathon badges; ASI:One Submission Agent registration; 3 to 5 minute demo video (required).

**Visa** (Lane D signing, Lane C merchant simulator)
- Carries: Trusted Agent Protocol signs every buyer-agent request and carries the mandate hash; payment is a Stripe test-mode charge on a Visa test card; a Visa Intelligent Commerce adapter swaps in only if Visa grants sandbox access.
- Breaks without it: our merchant simulator rejects the unsigned request, and the replay has nothing to fail.
- Demo moment: beat 4, a replayed or altered mandate fails on screen.
- Hard requirements: Reimagining Shopping judging criteria are Innovation 25, UX 25, Technical Execution 20, Commerce Impact 15, Trust and Responsibility 15 (no Visa API requirement found; the Visa API is not required). Never say "Visa settles". The README states exactly what is live and what is an adapter.

**Apify** (Lane C build, Lane A Store publish; credits in hand)
- Carries: seller listings mirrored from real stores, and our own claim-check Actor that the advocate cites in every veto.
- Breaks without it: the veto has no source link ("seems risky" is not the beat).
- Demo moment: beat 2, the veto shows the live page link.
- Hard requirements: Apify used in a meaningful way (Best Use of Apify); Best Actor asks for an Actor built for this event, so the claim-check Actor is published to the Apify Store (a14) with cost per run documented.

**Bright Data** (Lane C)
- Carries: pages behind anti-bot walls, SERP and Web Unlocker, and a dated second baseline price for the savings tile. Any spend needs Vidyut's OK first (a Newegg dataset is $250 minimum, reported).
- Breaks without it: the savings tile loses its second source and reads "unverified".
- Demo moment: the savings tile with two dated sources (shown with the beat 4 receipt).
- Hard requirements: track text not yet read (prize text is in the guide or "coming soon"); owner posts it at kickoff. Meanwhile: Bright Data used for a real, named step (the second baseline and one blocked page), recorded in data/README.md.

**CRS** (Lane A gate; credits in hand; Lane C supplies sandbox test identities)
- Carries: identity and fraud check on business sellers. Sandbox test identities only, band output, consent card; individual used-part sellers are not credit-checked (FCRA caution).
- Breaks without it: unverified sellers bid, and the greyed-out seller beat disappears.
- Demo moment: one business seller's bid is greyed out with the reason, inside beat 2.
- Hard requirements: the CRS sandbox shown live (calhacks.crscreditapi.com or the CRS MCP server), provided test identities only; Best Identity and Fraud Innovation asks for protecting people or businesses from fraud; Best Financial AI Agent asks for an agent doing real work with CRS data through the API or MCP.

**Armadin** (Lane D core, Lane C product layer, Lane A `/verify-agent`)
- Carries: Bazaar Shield: `/v1/shield/screen`, `/verify-agent`, `/check-claim`, `/verify-mandate`, signed verdict receipts, rules as data, the attack corpus, a key and a `shield-bench` for any attack swarm.
- Breaks without it: the injected listing reaches the advocate, a payee swap goes through, and the block-rate tile reads zero.
- Demo moment: beat 3, Shield blocks an injected listing live; judges attack it in the "Hack the market" console.
- Hard requirements: Best Security Hack, sponsored by Armadin (posted prize: headphones, possibly hacking tools; not cash). Report "blocked X of Y on this corpus" in three columns (dev, held-out, adaptive), never "secure"; hand them a key and the bench.

**Cartesia** (Lane D core, Lane B screens, Lane C Photon spike)
- Carries: the two-way call: the buyer asks "why not the cheaper one?", the advocate answers aloud, the buyer speaks the word-pair code, the amount is read back. Photon SIP first, in-browser call as default and fallback.
- Breaks without it: nothing above the allowance can be approved, so the first buy stalls.
- Demo moment: beat 4.
- Hard requirements: voice must be core to the product, not a feature added for the demo; make clear what Cartesia contributes; submit a working demo, a 2-minute demo-first presentation and a short README with setup, the Cartesia features used and known limitations.

**Hyphenate** (Lane B pages, Lane C `three_way_match`)
- Carries: the IT buyer's procurement seats as an autonomous system: PO number, the requester cannot approve, three-way match (PO, listing claim and page, delivery check), credit memo on a failed receiving check, an audit page where every call traces to its data, rule or person.
- Breaks without it: the IT buyer view loses its PO and audit page; the core loop is unaffected.
- Demo moment: a seeded IT order showing the PO, a failed match writing a credit memo, and the audit trail (with the simulated company around it labelled SIM).
- Hard requirements (Finance track): an autonomous system for a few seats in one corner of a finance team plus the simulated company around it; a live demo running for real; a video that opens with the moment; one line on the seats it fills; proof of what is real, what is simulated and how you know. Nobody who requests a payment can approve it.

**Anthropic** (Lane A)
- Carries: Claude is the advocate (closed output schema), writes sellers' "what to change" lines, powers Shield's ambiguous-case classifier, and generates hostile builder and attack variants.
- Breaks without it: no veto reasons, no seller notes, no attack variants.
- Demo moment: beat 2 (the veto reason) and beat 5 (the "what to change" line).
- Hard requirements: track text not yet read; owner posts it at kickoff. The portal asks that you know where it could go wrong: our scoreboard and Honest limits section show where.

**Spacetime** (Lane B)
- Carries: the arena itself: sealed rounds, reducers that enforce the floor, flat fee, ledger, goal states and approval-before-payment; every agent and screen shares one world; the floor and scoreboard subscribe to it. Fri 23:00 go or no-go (Convex fallback).
- Breaks without it: bids cannot be sealed or refereed, and the screens drift apart.
- Demo moment: two laptops show the same round at once (beats 1, 2 and 5).
- Hard requirements: Spacetime is the core real-time backend (live shared state, instant sync between agents and users, "AI systems coordinating in a persistent world state"), meaningfully used and not added on the side. README names the Python bridge as the single point of failure.

**Tiger Data** (MLH track, Lane C): time series behind dated savings and the learning curve; after Sat 14:00 only; plain Postgres could do this, say so. Slip form: plain queries.

**Capital One (Nessie):** maybe, only if Capital One is present at the event. Not planned; no lane has time for it.

**Phone for the call:** Photon SIP first (the team used it at LA Hacks and won its voice prize), with Cartesia over SIP. Anoop spikes it (decision Sat 09:00); the in-browser Cartesia call is the default and fallback. Do not buy Twilio before Photon is proven.

**Credits in hand: Apify and CRS.** Anything else that costs money (Bright Data, Twilio; Stripe is test mode and free) needs Vidyut's OK first.

## REAL vs MIRROR vs SIM (rules)

- **LIVE/real:** produced by a real outside party or a real object right now (an outside Agentverse agent's bid, the CPSC recall API, the live page checked by the claim-check Actor, Stripe test API, Shield verdicts on judge attempts, a real teammate receipt).
- **MIRROR:** our agent acting on a real listing scraped and dated (Apify). Shows listing URL, snapshot date and floor.
- **SIM:** anything we generated: wind-tunnel builders, pooled "other universes", recorded price feed on the sim clock, seeded sellers, planted liar pages we host ("Honest Hal", "Shady Sam").
- Every bid, claim, number and screen carries LIVE, MIRROR or SIM. SIM numbers are never added to real ones; they sit in separate columns. docs/REAL_VS_SIMULATED.md exists from hour one and is updated whenever a thing changes status.
- Claims use tense by status: present tense only for built; say "mocked" or "planned" plainly, or cut it.

## Seller model (LOCKED Fri 22:36)
One seller agent per SELLER OF RECORD: whoever takes the money and ships. Amazon selling directly is one agent; each third-party merchant on Amazon is its own agent; Newegg, a local shop, a brand's own store are each one agent. One agent may bid several condition lines (new, open-box, refurbished, bundle) for the same SKU inside one sealed bid. Every listing normalizes to one canonical SKU (MPN or UPC) in SpecCard. The advocate ranks on quality-adjusted landed price (condition, warranty, returns, seller record); the buyer's goal sets which conditions are allowed. Manufacturers bid only when they sell direct.

## Invariants (never break these)
1. No payment row without an approval row for the same mandate hash. A reducer invariant, tested in CI (Vedant writes it, Vidyut reviews). Idempotency key on the mandate hash: a second approval is rejected and shown.
2. Voice is never the credential. The credential is a one-time word-pair code on the buyer's authenticated screen, spoken inside a call about one exact mandate. The model never decides "approve"; code does. Default deny.
3. The mandate binds deal id, amount, payee, expiry and nonce. Stripe charge and TAP verification both check the hash.
4. Amount and payee are read by TTS from a code-filled template, never from seller text, and the amount is never parsed from speech.
5. No agent acts on another agent's text before a Shield screen. Shield fails closed on timeout (quarantine).
6. Every seller claim shown carries a live-check result: verified, unverified or false, with source and time.
7. Sealed bids. Sellers never see the buyer's budget, allowance or each other's bids, and see only aggregate pool data (SKU, quantity, ceiling band, deadline).
8. A seller agent never bids below its floor; the ledger balances after every order; the fee is flat and never feeds ranking or the advocate (test it).
9. CRS fields never leave their lane; both sides see only a band or pass or fail.
10. Sandbox and test identities only; no real cards; no secrets in the repo (.env.example lists names only). Shield logs hashes and rule ids, not message bodies, by default.
11. Everything on screen renders real market state only (3D floor included), and anything simulated is labelled.
12. The agent never re-buys a part in ownership memory unless asked, and advice cites the entry.

## Contracts (in contracts/; every lane mocks the others from these)

Existing: Need, SpecCard, SupplierTerms, Bid, Claim, ShieldVerdict, SupplierSignal, AdvocateCard, OrderPlan, Order, ReceivingEvent, QualityRecord, LedgerEntry, Persona, FloorEvent v2 (Vedant's proposals SpecCard, SupplierTerms, OrderPlan, ReceivingEvent, QualityRecord, FloorEvent v2 stand). Add to Bid and Claim: `origin` (LIVE, MIRROR, SIM) and `source`.

**New proposals. Each is logged in a new file in docs/changes/ (`<HHMM>-<lane>-<topic>.md`) before merge; everyone reviews on the board by Fri 22:30 (contracts frozen).**
- `LossReport {id, round_id, seller_id, won, gap_band: within5|within10|within20|over20, reason: price|fit|condition|delivery|record|advocate_veto, source_url, created_at}` (owner Vedant). Never carries thresholds or model details. Rate limited per seller.
- `OwnedPart {id, buyer_id, sku_spec, item_name, condition, acquired_on, source: bought_here|told_by_user|imported, attrs{as SpecCard}, notes}` (owner Abhinav). The buyer's profile is its OwnedParts plus its allowance. For an IT buyer it is fleet memory.
- `Goal {id, buyer_id, type: budget_cap|part_by_date|build_by_date, items[], cap, deadline, state: ACTIVE|HUNTING|HOLD_FOR_CALL|DONE|EXPIRED|PAUSED, reserved_amount, po_number?, created_at}` (owner Vedant with Abhinav; reducer is Vedant's).
- `Mandate {id, deal_id, amount, payee, expiry, nonce, hash, tier_price?, max_price}` (owner Vidyut). Hash covers deal id, amount, payee, expiry and nonce.
- `Allowance {buyer_id, auto_approve_up_to (starts 0), currency, seat_id?, raised_by: [receiving_event_id], phone_ref}` (shape Vidyut, reducer Vedant). phone_ref is a reference, never a raw number in the repo.
- Also proposed: `VoiceApproval {id, mandate_hash, called_at, code_ok, approve_token, answer: approve|deny|no_answer, transcript_ref}` (Vidyut), `ShieldVerdict` v1 schema `{verdict: allow|quarantine|block, rule_ids[], severity, evidence_spans[], latency_ms, request_id, version}` with no free text from a model, plus a signed receipt (Vidyut).

Contract changes go in a new file in docs/changes/ (`<HHMM>-<lane>-<topic>.md`) first; unobjected proposals stand.

## Term map (words to use in code, tests, UI and docs)
buyer (the agent's owner; "builder" only for DIY upgraders), seller, goal, bid, lot (a pooled SKU order), mandate, allowance, condition (new, open-box, refurbished, used), variant (retail or OEM, cooler included, model number), CPSC recall, loss report, advocate, advocate veto, Lot Wall, origin badge (LIVE, MIRROR, SIM), wind tunnel, Bazaar Shield. Say "charges worth questioning" or "the price claim did not match the price history", never "wrong" or "liar".

## Repo layout (each lane owns its folder; touch others only through contracts/)
- contracts/ shared JSON schemas (change only with a note in a new file in docs/changes/ (`<HHMM>-<lane>-<topic>.md`))
- agents/ Lane A: Python uAgents (buyer, advocate, sellers, goal loop, CRS gate, open seller protocol, Shield /verify-agent, sim clock)
- market/ Lane B: SpacetimeDB module (rounds, goals, lots, allowance, reservation ledger) and market/rules
- web/ Lane B: Next.js buyer screen, seller screen, Lot Wall (later item), 3D floor, Hyphenate pages
- data/ Lane C: Apify mirrors, claim-check Actor, fit checker, hosted liar pages, baselines, price feed
- sim/ Lane C: wind tunnel runner (builders, attack arm, control seller, seeds)
- shield/ Lane D core (`/v1/shield/screen`, `/verify-mandate`, receipts, rules as files) with Lane C's OpenAPI, keys, meter, client and `shield-bench`
- pay/ Lane D: mandate, TAP signing, call core; Lane C: merchant simulator (verifies TAP, Stripe test charge, replay failure)
- docs/ README, sponsor map, real-vs-simulated table, kickoff/, BOARD.md, CHANGES.md, INTERVIEWS.md

## Lane shares (equal, Vidyut ruling)

Hours of planned work to Sun 03:00, judgement estimates, roughly equal: A Abhinav 24.25 h, B Vedant 25.0 h, C Anoop 24.25 h, D Vidyut 25.0 h. Vidyut's share includes watching the repo and the hub page (PRs, the board, live-versus-mock labels), counted inside his 25.0 h. After Sun 03:00 Anoop owns integration for 6 h. When a lane is ahead, it takes the next item passed back in the team chat (see working rules).

## Milestones (PDT)
- **Fri 22:30** contracts frozen (new proposals reviewed).
- **Fri 23:00** Spacetime go or no-go (Convex fallback), posted on the board.
- **Sat 03:00** first real path: real Apify mirror bids, real Claude advocate, real Shield verdict (mocks allowed for one hop).
- **Sat 09:00** Photon spike decision (Anoop).
- **Sat 10:00 TALKABLE PROGRESS:** five beats run end to end, labelled. Sponsor and judge feedback round 2. Then: fold in feedback, then visual polish, then demo and pitch.
- **Sat 14:00 DEMO PATH GREEN** on the deployed build. Deferred items start only after this (the Lot Wall, Snowflake, Gemini, persona voices, Tiger Data, extra 3D).
- **Sat 19:00** video storyboard approved. Lot Wall gate Sat 22:00. No new 3D work after Sat 22:00.
- **Sun 03:00 FEATURE FREEZE.** Anoop owns integration from here (6 h).
- **Sun 06:00** Devpost complete. **Sun 08:30** submitted. **Sun 09:00** deadline. Judging Sun 10:30, whole team at the table.

## Working rules
- No secrets in the repo, chat or logs. Never read or edit `.env`. Sandbox and test identities only.
- Never add Co-Authored-By or any attribution trailer to a commit. Stage only files you changed. Never push or merge to main unless Vidyut says "push"; he ships.
- Branch per task, small PRs, main always runs. Write the failing test first for logic (reducers, fit rules, Shield, mandate, call).
- Post one line per finish or need in docs/board/<your lane>.md (newest at the bottom). Anything more than 90 minutes behind a gate goes to Vidyut at once.
- Never write "Visa settles". Say "Stripe test mode on a Visa test card, signed under Visa's Trusted Agent Protocol; our merchant simulator verifies the signature".
- Never call a real store a liar. Say "the price claim did not match the price history", "differs from the listing at time T", "could not verify". The planted liar runs only on pages we host.
- Never claim more than built. Never "secure": say "blocked X of Y on this corpus". Never say "many buyers use it".
- No em dashes or en dashes anywhere (copy, code, comments, commits).
- Outward contact (quotes, interviews, asking a booth to point an agent at us) is Vidyut's call and Vidyut's voice.
- **If you cannot finish an item, pass it back in the team chat and it moves to whoever is ahead.** Say it early, with what is done and what is left. Do not sit on it.
- Open a PR to main per finished item. Never add Co-Authored-By.

## Slip ladder: the minimum shown form (replaces "drop")

If an item is not green at its gate, it ships in the smaller form, labelled MOCK or SIM, and the claims list marks it `mocked` or `planned`. Hour estimates are judgement, not measurements. Lane load is 93 to 100 percent of capacity before Sat 10:00, so these forms are mandatory, not optional.

| Item | Gate | Minimum shown form |
|---|---|---|
| Phone call path (Photon) | Sat 09:00, then Sat 18:00 | In-browser Cartesia call; typed fallback code |
| Wind tunnel at 50 builders | Sat 20:00 | 10 builders, 3 seeds, same two numbers, SIM |
| Seller learning trend | Sat 22:00 | One deterministic strategy diff from one loss report, no trend claim |
| Open seller protocol | Sat 18:00 | Protocol plus a registered stub agent tagged MIRROR; outside bid only if one arrives |
| Hyphenate | Sat 16:00 | PO, three-way match and audit page on seeded data, SIM |
| Build goal | Sat 20:00 | Scripted 3-part build solved by the fit checker, labelled |
| Lot Wall (a later item) | Sat 22:00 | Plain lot table with the tier ladder, read live from the lot reducer, no wall animation; never a hardcoded picture |
| 3D floor extras, persona voices | Sat 22:00 | 2D row mirror plus text bubbles |
| Tiger Data | Sun 00:00 | Plain queries, with the note that Postgres could do this |
| Real purchase | Sat 18:00 | Receiving check on a teammate photo of a part already owned, labelled demo |
| Shield API extras (keys, metering, bench) | Sat 22:00 | Keys and schema stay; metering as a counter; bench as a script |

## The evidence plan (what lifts the score; owners and times)

1. **Tonight 21:45 to 23:00 (Vidyut):** 8 venue interviews (target 8; INTERVIEWS.md first names, role, exact words, with permission). Three questions: "What did you last buy, and what went wrong or almost went wrong?", "Would you let an agent buy it if it called you first? Above what amount?", and for org buyers "Who approves, and what would you pay to have this?".
2. **Sat morning to 14:00 (Vidyut):** one real seller quote (2 local PC shops or 3 used-part sellers; a quote, and "would you pay 3 percent, capped at $25, only on a verified sale?") and one IT buyer quote or written pilot interest.
3. **Sat by 18:00 (Vidyut, needs his OK on spend):** one real teammate purchase. "The agent chose and you approved; the payment was by the teammate", receiving check on the real box, filling the real savings column even if the saving is $0.
4. **During judging:** an outside agent bids live (another team or the Fetch booth), and every judge is invited to the "Hack the market" console. Every attempt counts, pass or fail.
5. **Scoreboard tiles**, each with count, date range and label: dated verified savings (real and SIM columns separate, baseline from 2 sources within 24 h before the buy, negative savings shown); attack block rate (dev 30, held-out 20, adaptive after the rules freeze, plus false blocks on 50 benign listings, plus judge attempts, plus voice attacks); fit accuracy (40 hand-checked builds frozen before tuning, "false OK" shown on its own); seller learning lift (SIM, held-out builder archetypes, 5 seeds, interval shown, negative shown if it happens).
6. **Business, shown not built:** consumers free; first payer is the IT buyer. The IT buyer is priced per refresh (proposed, finalized later), with the $49 Team and $199 Business monthly plans as alternatives; naming Amazon Business, CDW and Dell as incumbents is also finalized later; sellers bid free and pay 3 percent, minimum $1, capped at $25, only on a delivered sale that passed the receiving check; Shield is a usage-priced API set after a design partner. All numbers are ASSUMED until the first quotes.
