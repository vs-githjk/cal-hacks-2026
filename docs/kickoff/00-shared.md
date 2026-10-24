# Bidding Royale: shared kickoff context (every teammate pastes this first)

## LATEST DIRECTION (Fri 20:00; overrides anything below that conflicts)
- Name: Bidding Royale (repo cal-hacks-2026). Older text below says "Bazaar"; read it as Bidding Royale.
- Who it is for: independent restaurants (1 to 5 locations) that order ingredients weekly from several suppliers. Later: any business buying raw materials at volume (manufacturers).
- The problem (sponsor feedback: say why, for whom, what problem): food is a restaurant's biggest controllable cost, prices move weekly, ordering eats hours of the owner's or kitchen manager's week by phone, text and portals, over-ordering becomes waste and under-ordering runs dishes out, and independents have no procurement team, so they pay more than chains.
- What we build: the restaurant's agent learns usage from past orders and counts ("200 carrots lasted a week"), predicts next week's order, posts it as a need, and supplier agents bid in a sealed auction. The devil's advocate checks spec equivalence (grade, pack size, case count), delivery claims, price against a market baseline, and supplier stability; then the agent auto-orders within the owner's limits and tells the owner.
- Same-spec commodity items from many suppliers make price and quality comparable (unlike branded goods).
- CRS (their suggestion, agreed): CRS checks each supplier's financial stability (credit, pending loans) inside our system; buyers and sellers see only a verified signal, never the private data.
- Data: Apify actors for WebstaurantStore, Sysco, CHEF'STORE (Restaurant Depot, Sysco, US Foods prices), Instacart and Costco; Bright Data for the wider web; USDA market news as a public wholesale price baseline. Students buying electronics remain a possible second demo.
- Real-people goal: two real restaurants or suppliers in the loop and one real order by Sat 14:00. Log interviews in docs/INTERVIEWS.md.
- VISA FEEDBACK (Fri 20:20): trust is everything, and it must not be a chatbot or a chat window over agents. It must be an intelligent agent that acts on its own (it runs the weekly ordering cycle without being asked), saves real time and makes or saves real money, and shows both on screen (hours saved, dollars saved this week, with how each was computed). Chat in ASI:One is for approvals and questions, not the product.
- QUALITY ADVOCATE (replaces "devil's advocate"; quality is the top priority): before any order it checks (1) need: does the forecast and current stock justify this quantity, or will it go to waste; (2) quality: spec match (USDA grade, pack size, case count, origin, certifications), shelf life and ripeness window against the delivery date, open recalls (openFDA food enforcement API), and each supplier's quality record (past rejected cases and credits from our receiving check, public reviews and complaints via Apify and Bright Data); (3) price against the USDA baseline; (4) supplier stability (CRS signal). Every warning cites a source.
- RECEIVING CHECK (closes the quality loop): when a delivery arrives, the kitchen snaps a photo of each case; a vision model compares it to the spec (count, size, ripeness, damage), and a reject or credit is recorded against that supplier and changes how the agent ranks it next week.
- Commits: never add a Co-Authored-By line or any Claude attribution.

You are one of four coding agents building Bazaar at Cal Hacks 13.0 (hacking Fri Oct 23 18:00 to HARD deadline Sun Oct 25 09:00 PDT; judging needs a live demo). All code is written during the hackathon.

## The product in one line
Shoppers: stores fight for you, and your agents make sure you get the best price and deal. Stores: your agent trains to win the most customers.

## What it does
- A shopper states a need in ASI:One (Fetch.ai), by voice, or by scanning a product. Store agents bid for the order in a live reverse auction.
- The shopper's devil's advocate agent (Claude) argues against bad buys: hidden fees, price history, fake-review signals, better timing, and (with consent) affordability from CRS credit data and the shopper's Capital One Nessie accounts.
- Bazaar Shield screens every agent-to-agent message, verifies agent identity and checks store claims against the live web (Apify, Bright Data). Liars are thrown out.
- Checkout: the Fetch.ai Payment Protocol on the rails ASI:One supports today, Stripe (test mode) or Link, charging a Visa card, always within the shopper's limit. Every agent request to a store is signed under Visa's Trusted Agent Protocol (real, not mocked). A Visa Intelligent Commerce adapter (tokenized agent credentials) sits behind the same interface and swaps in if Visa grants sandbox access.
- Stores train their bidding agents in the wind tunnel: hundreds of simulated shoppers, honest and hostile, built from CRS test identities, against an Apify mirror of the store's catalog.
- The store's finance desk books every order, discount and refund to a double-entry ledger and reconciles with Visa settlement (Hyphenate track).
- The 3D Bazaar floor shows the live auction as persona characters haggling, each with a Cartesia voice. It only renders real market state.

## Invariants (never break these)
1. No money moves without the shopper's approval card and a limit check.
2. Every store claim shown to a shopper carries a live-check result: verified, unverified or false.
3. No agent acts on another agent's text before a Shield screen.
4. The 3D floor and every screen render real market state only.
5. A store agent never bids below its store's floor price; the ledger balances after every order.
6. Sandbox and test identities only; no real cards; no secrets in the repo (.env.example names only).
7. Anything simulated is labelled in the UI and the README.

## Repo layout (each lane owns its folder; touch others only through contracts/)
- contracts/  shared JSON schemas (owned by everyone; change only with a note in docs/CHANGES.md)
- agents/     Lane A: Python uAgents (shopper, advocate, store agents)
- market/     Lane B: SpacetimeDB module (auction state)
- web/        Lane B: Next.js shopper view, store dashboard, 3D floor (three.js)
- data/       Lane C: Apify and Bright Data adapters, store mirrors, price history, Nessie
- shield/     Lane D: FastAPI Shield API (/screen, /verify-agent, /check-claim)
- pay/        Lane D: Visa, CRS adapters, finance ledger
- sim/        Lane D: wind tunnel (simulated shoppers, hostile agents)
- docs/       README, sponsor map, real-vs-simulated table, demo script

## Contracts (create in contracts/ in the first hour; every lane mocks the others from these)
- Need {id, shopper_id, text, product_query, budget_max, deadline, constraints[]}
- Bid {id, need_id, store_id, persona, price, perks[], claims[], expires_at}
- Claim {id, bid_id, text, kind: stock|shipping|fees|returns|price, check: verified|unverified|false, evidence_url}
- ShieldVerdict {message_id, sender_agent, verdict: allow|quarantine|block, reasons[], attack_type}
- AdvocateCard {need_id, bid_id, warnings[{kind, text, source_url}], recommendation, wait_until}
- Order {id, need_id, bid_id, amount, approved_by, payment_ref, status}
- LedgerEntry {order_id, account, debit, credit, memo}
- Persona {store_id, name, archetype, voice_id, model_url}

## Milestones (PDT)
- Fri 20:00 contracts merged; every lane has a stub that reads and writes them.
- Fri 23:00 mocked end-to-end: need, three bids, advocate card, approve, fake payment, floor shows it.
- Sat 03:00 first real path: real Apify mirror bids, real Claude advocate, real Shield verdict, Visa or Nessie sandbox call.
- Sat 14:00 demo path green on the deployed build.
- Sat 19:00 video storyboard. Sun 03:00 feature freeze. Sun 06:00 Devpost done. Sun 08:30 submitted.

## Working rules
- Branch per task, small commits, open a PR to main; main must always run.
- Write the failing test first for logic (auction rules, Shield, ledger, claim checks).
- Post what you finished and what you need in docs/BOARD.md (one line per post, newest at the bottom).
- Demo path first, polish later. When behind, cut in this order: hardware terminal becomes webcam scan, 3D floor becomes 2D sprites, wind tunnel shrinks to 50 shoppers, real-store mirrors become seeded demo stores.
- Sponsor requirements are in docs/SPONSORS.md; keep README's sponsor table honest.

## Red-team amendments (Fri 17:35; these override anything above)
0. Hero community: Bay Area students buying laptops, headphones and dorm electronics. Interview 3 to 5 at the venue Friday night; one quote and one real receipt open the pitch.
1. The hero loop is the contract: need in ASI:One, then 3 to 6 sealed bids, one planted liar caught with evidence, the advocate card with cited warnings, the approval card, payment, and the floor mirroring every step. Tier 0 (this loop) green by Sat 14:00. Tier 1: Shield console, wind tunnel numbers, Nessie, voice. Tier 2: 3D polish, hardware, extra personas.
2. Kill rules: Spacetime go or no-go Fri 23:00 (Convex fallback); Visa credentials go or no-go Sat 03:00; 2D or 3D decided Sat 03:00; no 3D feature work after Sat 22:00. Never drop Shield, Apify or the claim check. One integration owner runs the demo path every 3 hours from Sat 03:00.
3. Every Bid and Claim carries a source field (live, mirror with date, simulated, sandbox, recorded); every screen shows a LIVE, MIRROR or SIM badge; docs/REAL_VS_SIMULATED.md exists from hour one. Add to contracts: Need.spend_limit, Need.consent, Need.auction_window_s; Bid.total_landed_price, Bid.floor_check_passed, Bid.mirror_snapshot_id, Bid.decision_trace; Claim.checked_at, Claim.method, Claim.evidence_hash; Order.idempotency_key, Order.approval_id, Order.limit_checked; FloorEvent.
4. Sealed bids until the deadline (short anti-snipe extension); stores never see the shopper's budget; bids are computed by policy code (StorePolicy) and the LLM only writes the persona's line; floor, approval-before-payment and the balanced ledger are enforced in the market reducers. Reproduce Microsoft Magentic Marketplace's two published failures (first-proposal bias, payment redirect) and show both fixed.
5. The planted liar runs against storefront pages we host ("Honest Hal", "Shady Sam" with a lie toggle) so it works on any wifi. Real stores only supply price and policy truth, with neutral wording ("differs from the listing at time T", "could not verify"). Never call a real store a liar.
6. ASI:One drives; the floor is a read-only second screen of the same state ("same market, two views"). Register about 6 agents on Agentverse (shopper, advocate, Shield, store gateway, two named stores); run the rest as a labelled fleet. Stream progress during a 12 to 15 second auction window. Host agents on Agentverse or a cloud VM, never a laptop.
7. Invariant 8: the shopper's financial data never leaves the shopper side; stores get constraints and pass or fail only. A consent card before any CRS or Nessie read lists the exact fields; show bands ("tight"), never raw scores; never say "you cannot afford this". CRS visibly flips a decision: financing perks appear only for a persona whose check passes.
8. RunMode per adapter: live, cached or replay, 4 to 6 second timeouts, committed snapshot fallback, a footer badge showing the active mode, /health per service. A labelled recorded run of the full path exists by Sat 14:00. Test every required domain from the cloud sessions in the first 30 minutes.
9. Measured numbers, method fixed Friday night (Lane C gate): real price dispersion against a timestamped Bright Data baseline; simulated discount (labelled simulated); advocate precision and recall on a 30 to 50 item answer key with clean controls. Wind tunnel and Shield report on held-out sets, with Shield's false-positive rate and latency. Drop any advocate warning whose evidence does not support it; cap at three warnings; keep "buy anyway".
10. Business: shoppers free; stores pay a 1 to 2 percent success fee only on a won, approved order (via RequestPayment); wind tunnel as a monthly plan; Shield per call. Bids compete on price, perks, speed and verified-claim record, not price alone. Show "cost of this auction" on the store dashboard.
11. Payment seam: CommitPayment carries a signed mandate (amount cap, one merchant, expiry, single use) that the store verifies; idempotency keys; a plain-text fallback if Interactive Cards misbehave (numbered bids, reply APPROVE id).
12. Shield is commerce-specific: mandate consistency (payee or amount differs from the approved need), claim truth against the page, cross-bid collusion and lookalike signals. It consumes Trusted Agent Protocol signatures rather than inventing identity. One shared decorator enforces screening (rules under 50 ms, a small model only for ambiguous text, 1.5 second timeout, fail closed for payments). Add a "Hack the Bazaar" console for judges.
13. Sponsor depth: primary tracks are Fetch.ai, Visa, Apify and Spacetime. Apify: publish the claim-verification Actor by Sat 12:00. Every other sponsor gets one load-bearing beat with an owner, or is labelled out of the README by Sat 14:00.
