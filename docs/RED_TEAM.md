# Bazaar red team and judging merge

Written 2026-10-23, 17:34 PDT. The idea stays. Every flaw below is a concrete change to the build.

## Scorecard

Judge mean 32.30 of 50 (range 30 to 34, ten judges). Overall-winner range is 42 plus. Applying the fixes, judges estimate 37 to 40, which is sponsor-track-winning range.

| Metric | Mean | Reading |
|---|---|---|
| Problem | 2.7 | Weak: no named community, no lived pain |
| Application | 2.05 | Weakest: no real counterparty, Monday story missing |
| Intentionality | 3.05 | Two heroes (shopper and store) split the story |
| Functionality | 2.1 | Weakest: scope too wide for 4 people in 39 hours |
| Creativity | 3.6 | Good, but the haggling shape looks done |
| Technical | 4.0 | Strong, needs visible numbers |
| Moment | 4.0 | Strong, must land in the first 30 seconds |
| Business | 2.75 | No buyer, price, cost per order or moat |
| Sponsor | 4.1 | Strong fit for Visa, Fetch, Apify, Spacetime |
| Trust | 3.95 | Strong, needs on-screen real versus simulated |

Where the points are: application, functionality, problem and business are the four low scores. The 15 changes are ordered by how much they move those four and the sponsor tracks.

## The 15 improvements, ordered by impact on winning

### 1. Name the community and open on one real person
- Flaw: "Shoppers" is too broad. Anthropic, Cal Hacks and Visa all want a named group with a lived problem, and nothing in the plan quotes a person.
- Change: Pick one group and one hero category with real price dispersion (suggested: Berkeley and Bay Area students buying a laptop, headphones or dorm electronics). Interview 3 to 5 people at the venue Friday night, put one quote and one real receipt on slide 1, and make the advocate's first demo warning replay that real case.
- Lane: pitch (C supplies the receipt-based numbers)
- Priority: do before 18:00 (choose the group now, run interviews Friday evening)

### 2. Freeze one hero loop, three tiers, hard time gates and a kill list
- Flaw: Four lanes touch about ten sponsors plus a 3D floor, wind tunnel, ledger and hardware. Judges can tell a wide shallow build from a deep one, and Lane D alone holds five big items.
- Change: Write the hero loop as the contract: need in ASI:One, 3 to 6 bids, one liar caught with evidence, advocate card with cited warnings, approval card, payment, floor reflects each step. Tier 0 must be green Sat 14:00. Tier 1 is Shield console, wind tunnel numbers, Nessie, voice. Tier 2 is 3D polish, hardware, extra personas. Kill rules with times: Spacetime go or no-go moves to Fri 23:00 (Convex fallback), Visa go or no-go Sat 03:00, 2D versus 3D decided Sat 03:00, no 3D feature work after Sat 22:00. Drop order if Tier 1 slips: Cartesia depth, Nessie writes, then Hyphenate. Never drop Shield, Apify or the claim check. Name one integration owner who runs the demo path every 3 hours from Sat 03:00. Add a Friday 18:00 to 22:00 spike list: hello shopper agent discoverable in ASI:One, hello Spacetime reducer called from Python, all credential requests fired.
- Lane: all
- Priority: do before 18:00

### 3. Make the store side real: one real merchant and a 60 second onboarding flow
- Flaw: No real store bids. Bids come from our agents over scraped catalogs with invented floors, so "stores fight for you" is shown against our own puppets, and the savings are modeled.
- Change: Build a store onboarding a judge can watch: paste a store URL, Apify mirrors the catalog, owner sets floor, max discount, perks and the controller threshold with sliders, the store agent goes live. Run one real, human-owned store (a teammate's or friend's Shopify dev store) so the table has one fully real row, ideally issuing a real discount code. Label every non-participating store "price mirror, not a participating merchant" and every floor "demo floor". Prefer 6 real mirrored stores over 20 seeded ones and remove "real mirrors become seeded stores" from the cut list.
- Lane: B market and floor
- Priority: build in the first 12 hours (decide the real merchant before 18:00)

### 4. LIVE / MIRROR / SIM badge on every bid, claim and screen, driven by a contract field
- Flaw: Mirrored catalogs, invented floors, CRS test personas, sandbox Visa and simulated shoppers could read as a staged demo unless each is visibly labelled. Invariant 7 is only prose and the honesty table has no owner.
- Change: Add a source field (live page, mirror with date, simulated policy, sandbox, recorded) to Bid and Claim and render a legend on every card and screen. Create docs/REAL_VS_SIMULATED.md at hour one (component, real or simulated, how we know) and update it per merge. Mirror it in the README and as a pitch slide. Click any floor character to see its Spacetime row (proves invariant 4). Use the same file to extend contracts before 20:00: Need (spend_limit, consent, auction_window_s), Bid (total_landed_price, floor_check_passed, mirror_snapshot_id, decision_trace), Claim (checked_at, method, evidence_hash), Order (idempotency_key, approval_id, limit_checked), FloorEvent.
- Lane: all
- Priority: do before 18:00 (contract fields), UI build in the first 12 hours

### 5. Make the "liar caught" moment deterministic, and never call a real store a liar
- Flaw: Live claim checks on real retail pages are brittle (bot walls, layout drift, stale mirrors), may breach terms, and a false "liar" label on a real brand is a trust and legal risk. A claim checked against the same mirror it came from is circular.
- Change: Host 3 to 4 storefront pages the team controls ("Honest Hal", "Shady Sam") with stock, shipping and fee fields and a toggle so Sam's agent really lies. The live check runs against that page on any wifi, with a real evidence URL, timestamp and screenshot. Real stores only supply price and policy truth, with neutral wording ("differs from the listing at time T", "could not verify"). Keep one cached real-store check per demo. Add a "try my claim" box so a judge can type a claim and see it checked. Label the planted liar as a planted attack with an answer key.
- Lane: C data
- Priority: build in the first 12 hours

### 6. Script the first 30 seconds and make ASI:One the driving surface, the floor its mirror
- Flaw: Fetch requires the primary workflow to finish inside ASI:One while Visa, Spacetime and the wow live on the web floor, so judges can see two half-demos. The strongest beat (advocate says no, liar is thrown out) is not guaranteed to appear early.
- Change: Run it as a two-screen layout: the judge types or speaks in ASI:One on the main laptop (need, carousel card, advocate card, approval, payment), the floor on the second screen is a read-only view of the same Spacetime state. Say aloud "same market, two views". Opening beat: spoken need, floor wakes, three stores bid, one claim turns red with an evidence link, guard drags it out, advocate says "wait, price dropped 12 percent last month". Add a beat sheet with a clock, roles and a one-click Reset. Register about 6 agents on Agentverse (shopper, advocate, Shield, a store gateway, two named stores) and run the rest inside one labelled fleet. Stream progress messages during a 12 to 15 second auction window so chat never looks frozen. Host agents on Agentverse or a cloud VM, never a team laptop.
- Lane: A agents (pitch owns the script)
- Priority: do before 18:00 (script and surface decision), build in the first 12 hours

### 7. One-slide business model with measured unit cost
- Flaw: No buyer, price, take rate or moat. A reverse auction pushes store margin down, so it is unclear why a store joins or pays. Fetch scores monetization and Visa scores merchant outcomes.
- Change: State it in five lines (docs/BUSINESS.md and one slide). Shoppers free. Stores pay a success fee only on a won, approved order (about 1 to 2 percent, versus 8 to 15 percent marketplace fees), collected via RequestPayment. Shield is metered per screened message. Wind tunnel is a monthly per-store plan sold as "agent readiness testing". Make bids price plus perks, speed and verified-claim reputation so stores win without being cheapest. Log tokens, Apify and Bright Data credits and Cartesia characters per auction and show "cost of this auction: $0.0x" on the store dashboard. Moat sentence: the verified-claim record per store and the attack corpus compound with every auction. Do not claim customers we do not have.
- Lane: pitch (A owns the fee wiring, B the cost counter)
- Priority: do before 18:00 (slide and doc), counter in the first 12 hours

### 8. Close the wind tunnel loop on a held-out set and show one before and after chart
- Flaw: "Stores train their agents" has no mechanism, and simulated shoppers written by us are tuned and measured on the same set, so any lift is meaningless. SimGym reached only 77 percent agreement with real behavior.
- Change: Define the store policy as a small parameter set (discount curve, perk choice, counter rule, minimum margin). Split shoppers and attacks into train and held-out, fix seeds, tune on train, and publish before and after on held-out only, with a naive baseline (cheapest-wins, first-offer-wins). Show the run in the demo with 50 shoppers (a few hostile): conversion, margin kept, attacks landed, one Claude-proposed patch the store owner approves, then the improved re-run. Say "20 CRS personas, synthetic variants" honestly and cache CRS profiles. Every hostile message becomes a Shield test case.
- Lane: D pay and trust
- Priority: build in the first 12 hours (the 50-shopper chart), full 300 is nice to have

### 9. Make Shield commerce-specific and prove it on a held-out corpus
- Flaw: /screen duplicates Superagent, Lakera and InjectShield, and /verify-agent duplicates Visa TAP and Skyfire. A catch rate on a corpus we wrote and tuned on is overfit. Screening in the hot path adds latency and a failure mode.
- Change: Differentiate with three commerce checks: mandate consistency (payee or amount differs from the approved Need, the Magentic redirect attack), claim truth against the page, and cross-bid collusion or lookalike signals. Consume TAP-style signatures instead of inventing identity ("identity says who, Shield says whether it is true"). Contain, not only detect: typed contracts and signed mandates so an injection that lands still cannot pay. Split the corpus 60 percent tuning, 40 percent frozen, plus an unseen set from the wind tunnel's hostile agents. Report catch rate, false-positive rate on benign messages that merely quote instructions, and latency. Enforce screening with one shared decorator in a bazaar_kit package (rules under 50 ms, small model only for ambiguous text, 1.5 s timeout, fail closed for payments). Add a "Hack the Bazaar" console where a judge types a hostile message and sees the verdict.
- Lane: D pay and trust
- Priority: build in the first 12 hours

### 10. Run modes, timeouts and health panel so no single dependency kills the demo
- Flaw: The demo chains about eight live services (ASI:One, Agentverse, Spacetime, Apify, Bright Data, Claude, Shield, Visa, Cartesia). At 95 percent each, the path works about 66 percent of the time on conference wifi, with judges visiting repeatedly. Silent fallbacks would also break invariant 7.
- Change: Add a RunMode of live, cached or replay per adapter with an env flag, a 4 to 6 second timeout and a committed snapshot fallback. Footer badge shows the active mode ("Visa: sandbox live, Apify: cached 14 min ago"). Add /health per service and a pre-flight page the sentinel runs at T-60 and T-10. Schedule Apify mirrors hourly and pin snapshots. Pre-warm Actors, cache Claude advocate output and Cartesia audio for the demo products (budget the 20K character tier, captions on, muted by default). Keep a labelled recorded run of the full path by Sat 14:00. Test every required domain from each cloud session in the first 30 minutes, bring two hotspots, and rehearse once with wifi off. Add a budget breaker and concurrency limiter for Claude calls and get runtime credits from the Anthropic booth.
- Lane: all
- Priority: build in the first 12 hours (curl domain test and credential requests before 18:00)

### 11. De-risk Visa and Fetch payments now, and make the mandate real
- Flaw: Visa VIC needs X-Pay and MLE credentials (a 4 hour plus risk) and the only fallback is a recorded call. Fetch's documented payment methods do not obviously include Visa, so the seam between CommitPayment and the Visa call may look disconnected. The Interactive Cards field list in the prompt is unverified.
- Change: At the 18:00 booths ask Visa for X-Pay and MLE credentials, and ask Fetch which payment methods uagents_core supports. Keep the seam honest either way: CommitPayment carries a signed mandate id and amount, the backend makes the Visa call, CompletePayment returns the transaction reference, shown on the ASI:One card. Make the approval card a scoped instruction (amount cap, one merchant, expiry, single use, signed, with the store verifying the signature) plus a spend-limit bar and one-tap revoke. If Visa is blocked at Sat 03:00, keep mandate, signature and verification fully real and use a clearly labelled stub (never a silent recording). Add idempotency keys. Fetch the Interactive Cards docs in the first 30 minutes and build a plain-text fallback (numbered bids, reply APPROVE id).
- Lane: D pay and trust (A owns the Fetch and cards verification)
- Priority: do before 18:00

### 12. Split the measured numbers into real, modeled and advocate precision, and define the method now
- Flaw: "Savings versus best public price" is circular when store agents bid from the same mirrored prices with a coded discount rule. The method is undefined, and the task is last in Lane C so it will be squeezed. "Cite a source" is a prompt instruction, not a guarantee.
- Change: Move the measurement to Friday night as a Lane C gate. Report three separate labelled numbers on N products (target 20 to 30): real price dispersion against a timestamped Bright Data baseline (median saved, share with no savings), simulated bid discount (marked simulated), and advocate warning precision and recall against a hand-labelled answer key of 30 to 50 items with planted issues and clean controls. Include the naive-agent counterfactual. Enforce grounding in code: drop any warning whose evidence URL or snippet does not support it, show "no objections found" when the key says so, cap warnings at three ranked by dollar impact, and keep a one-tap "buy anyway". Publish a null result honestly. Add a "where Claude can go wrong" table to the README.
- Lane: C data (A owns the advocate validator)
- Priority: build in the first 12 hours

### 13. Fix the auction design: sealed bids, redacted budget, collusion tests, floor in the reducer
- Flaw: Open first-come bidding invites the first-proposal bias Microsoft measured (10 to 30x). Need carries budget_max, so stores can bid up to the budget. Shill and collusion cases are untested. The floor invariant lives in a prompt or agent code.
- Change: Bids are sealed until the deadline with a short anti-snipe extension, and the shopper agent evaluates all bids at once. Stores see product query, constraints and deadline only, never budget. Add a reserve price and reject near-identical bids across stores. Compute bids in policy code (StorePolicy), use the LLM only for the persona line. Enforce floor, balanced ledger and approval-before-payment inside Spacetime reducers so a compromised store agent still cannot bid below floor. Unit and property test all of it. Show the badge "sealed bids, no first-mover advantage". Reproduce Magentic's two published failures (first-proposal bias, payment redirect) and show both fixed.
- Lane: B market and floor
- Priority: build in the first 12 hours

### 14. Consent and data minimisation, with CRS deciding something visible
- Flaw: Pulling credit and bank data for a shopping advocate is easy to attack (privacy, permissible purpose, paternalism), and a credit pull for a $200 monitor reads as a bolt-on. Nothing prevents shopper data leaking into store-bound messages.
- Change: Add invariant 8: shopper financial data never leaves the shopper side, and stores receive only constraints and a pass or fail signal. Add a consent card before any CRS or Nessie read that lists exact fields used, a toggle to turn it off, an access log, and bands only on screen ("tight", never raw scores). Add a Shield test that fails if a store-bound message contains profile fields. Make CRS flip a visible decision: financing perks (pay in 4) appear only for a persona whose soft-pull passes, so the same need shows different bids for two personas. Never display a "you cannot afford this" verdict. Use Nessie both ways: cash-flow-aware review card and a settlement deposit written to the store's account.
- Lane: D pay and trust (C owns Nessie and CRS caching)
- Priority: build in the first 12 hours

### 15. Sponsor depth rule: one load-bearing beat per sponsor, or label it out
- Flaw: Cartesia voice is floor decoration, the Hyphenate finance desk is a last-priority ledger with no time, no disagreeing sources and no controller who says no, and Armadin and Apify depth are thin. Bolt-ons dilute the story and invite shallow scores.
- Change: Primary tracks are Fetch, Visa, Apify and Spacetime. Apify: publish the claim-verification Actor (claim plus URL in, verified, unverified or false plus evidence out, pay-per-event) by Sat 12:00 and have the checker call it. Cartesia: shopper speaks the need and the advocate argues back in its own voice (cached lines, 4 distinct voices, typed fallback) or drop the claim. Hyphenate: one seat ("order-to-cash clerk for a small store"), a controller who can refuse a discount over the limit, about 12 planted discrepancies with an answer key and a period lock, or remove it from the README by Sat 14:00. Armadin: adaptive attacker swarm with a bypass-rate curve, and ask the booth at 18:00 what they want since criteria were still "Coming soon". Write docs/SPONSORS.md with one beat, one owner and one video per sponsor, and ask organizers the opt-in cap.
- Lane: all
- Priority: do before 18:00 (decide which sponsors are primary and which get labelled out), builds in the first 12 hours and nice to have after

### Below the cut (add if time allows)
- Expose Bazaar as an MCP server (post_need, get_bids, advocate card, approve) so any agent can shop in it (A, nice to have).
- Say Bazaar is protocol-neutral: shape Bid and Order close to UCP checkout fields and AP2 mandates, list "UCP adapter" as the first post-hackathon step (pitch, nice to have).
- Write a one-page Q and A with a number per answer (why a store joins, why not Honey or Perplexity, why not Lakera, who is liable when the advocate is wrong) and memorize it on two teammates (pitch, build in the first 12 hours).
- Make an executable invariants suite that drives a green "7 of 7 passing" panel (all, nice to have).
- Add a judge-playable "try a hostile message" console and per-sponsor 30 second drill-down tabs (D and pitch, nice to have).
- Run CI and a sleep rotation: two sleep Sat 02:00 to 06:00, two Sat 22:00 to 02:00 (all, build in the first 12 hours).

## Competitors found and our difference

| Competitor | Overlap | Our difference |
|---|---|---|
| Microsoft Magentic Marketplace (arXiv 2510.25779) | Open-source simulator, 100 buyers vs 300 sellers, found first-proposal bias and payments redirected by malicious sellers. Microsoft is a sponsor. | Research harness, no product, shield, payments or store coaching. Cite it as grounding. We reproduce its attacks in the wind tunnel and show the fixes (sealed bids, Shield). Best novelty hook. |
| Anthropic Project Deal | Claude agents bought and sold for 69 employees, 186 deals. Stronger models win and losers do not notice. | Cite as evidence of the problem. Bazaar is the answer: an advocate that argues against the buy, plus a screened counterparty. |
| TurnDeal (first place, Sea x OpenAI Codex Hackathon) | Buyer agent, five seller agents, simulated purchase in 60 seconds. Same demo shape. | No live-web claim check, attack screening, real payment protocol, store training or ledger. Open on the caught liar, not the haggle. |
| Pine AI ($25M Series A) | Consumer agent negotiating bills, 93 percent success, over $3M saved. | One company at a time over phone. We make sellers compete and add a skeptic. Report dollars saved with a counterfactual. |
| Shopify and Google UCP, OpenAI ACP, Google AP2, Perplexity shopping, Amazon Buy for Me | Agent checkout rails and distribution. | They standardize checkout at list price. We sit on top as a neutral negotiation, trust and testing layer. Platform risk is real, so own the layer they will not. |
| Visa Trusted Agent Protocol and Intelligent Commerce, Mastercard Agent Pay | Signatures to tell trusted agents from bots, tokenized payments. Visa is a sponsor and judge. | TAP says who the agent is. It does not check whether a store's claim is true. Consume TAP signatures in Shield. |
| Skyfire (KYA, KYAPay) | Funded identity tokens plus payment authorization. | Identity and payment plumbing only. No claim truth-checking or advocate. Verify existing identity, do not invent one. |
| Superagent, InjectShield, Silmaril, Lakera, Meta Prompt Guard | Prompt-injection firewalls with benchmarks. | They screen one agent's input. Shield is commerce-specific (mandate consistency, claim truth, collusion) and contains damage architecturally. |
| Shopify SimGym, Avada Shop Sim, tau-bench | Synthetic shoppers against a storefront. | They test human-style browsing. Our wind tunnel tests a bidding agent against hostile agents and closes the loop with a fix and re-run. |
| Goldie Chat (Shopify app) | Merchant-side haggler with a floor. | One store, human shoppers, no competition. Shows merchants accept floor-bounded discounting. |
| Priceline, RFQ marketplaces | Buyer states need, sellers compete. | Humans and fixed forms, no claim checks. Same cold-start weakness, so store-first onboarding matters. |
| Honey, Karma, Capital One Shopping, Google price tracking | Comparison and price history. | Passive merchants and affiliate conflicts. Our advocate cites sources and the merchant is accountable for claims. |
| A2A Market, Agoragentic | Early agent marketplaces. | Service marketplaces with little traction. Evidence the space is open but unvalidated. |
| Academic reverse-auction prior art | Agent reverse auctions since the 1990s. | Do not claim to have invented it. Claim LLM agents, live-web truth checks and an adversarial test bench. |
| A plain Claude prompt "Bazaar" | A teammate reproduced the shape from one prompt. | A prompt gives a transcript. We show a live check flipping a bid with a URL, a reducer rejecting a below-floor bid, a quarantined message, a reconciliation break and a payment reference. |

## Strongest objection and the best answer

Objection (raised by every judge and both red-team personas): "No real store bids. The stores that fight for you are your own simulated agents over scraped prices with floors you invented, so the savings are manufactured, and it sits on a chain of eight live dependencies."

Best answer: "Correct, and we label it on every screen. The bidders are agents we operate over real public listings, each tagged live, mirror or simulated, and the floor is a stated demo parameter. Two things in Bazaar are real without any store's cooperation: the advocate and claim checks work today on any real product, and the wind tunnel gives a store value on day one with zero shoppers (paste your URL, set a floor, get an agent and a before and after report). One store in this demo is a real, human-owned shop that set its own floor. Savings are reported as two separate numbers, real price dispersion against a timestamped public baseline and modeled discount, never blended. Stores pay only a success fee on a won, approved order, and compete on perks and verified-claim reputation, so they win without racing to the bottom."

## The 3 changes that add the most judge points

1. Named community plus a real counterparty (items 1, 3 and 4): lifts problem (2.7) and application (2.05) by roughly 1 point each, the two biggest gaps. One quote, one receipt, one real merchant, honest badges.
2. One frozen hero loop with time gates, run modes and a deterministic liar (items 2, 5, 6 and 10): lifts functionality (2.1) by 1 to 2 points and protects moment and trust. A smooth 3 minutes beats a wide stalled one, and every judge flagged scope as the way this loses.
3. Business slide plus measured proof (items 7, 8, 9 and 12): lifts business (2.75) and technical toward 4 to 5. Store fee with live cost per auction, wind tunnel before and after on held-out shoppers, Shield catch and false-positive rates, and the split real versus modeled savings.

Sponsor note: Visa, Fetch, Apify and Spacetime are the realistic wins (the team has Visa history). Items 11 and 13 protect those tracks directly.
