# Bidding Royale: shared kickoff context (every teammate pastes this first)

Rewritten Fri Oct 23, about 21:00 PDT for the PC and consumer tech pivot (decided 20:53, see plan/decisions.md). The restaurant direction is retired; its research stays in docs/RESEARCH_RESTAURANTS.md as history.

## Open decisions (Vidyut decides; nobody builds around these until he rules)
1. **Pricing model.** OPEN, Vidyut decides. The old test was 15% of verified savings capped at $299 a month, written for a restaurant buying every week. A PC builder buys once, so a monthly cap makes no sense. Recommended option: builders pay nothing; sellers pay a 1 to 2 percent success fee only on a won, approved order (already red-team amendment 10), and a paid seller demand-insights plan is tested in seller interviews, price set by what they say. Why: the buyer has no reason to pay for a one-time purchase (plan/research-pc.md has no sourced fee rates, so any rate is an assumption we label), the seller pays only when they win, and component margins are reported thin (TO VERIFY), so the fee must stay small. Lane B keeps the fee as a config value, not a hard-coded constant.
2. **Hyphenate purchasing seat in Tier 1.** OPEN, Vidyut decides. The restaurant purchasing and accounts-payable seat does not fit one person building one PC. Recommended option: move it to Tier 2 and re-aim it at the seller side, and name it as the fit for the growth path (small IT buyers buying 10 to 50 PCs need purchase orders, receiving and returns). Seller-side version: (the store finance desk from the first Bazaar plan: order, discount, refund and return ledger, a human controller approves discounts above a limit). Why: that is a real seller need, it reuses the ledger Lane D already builds, and it frees Lane D's Saturday afternoon for the buyer demo. If Vidyut keeps it Tier 1, drop it from the README by Sat 14:00 if it is not built.
3. **The final pitch line.** OPEN, Vidyut decides. Working line used in the docs until he rules: "Bidding Royale is the buying agent for PC builders. Tell it your parts and budget: sellers bid, it checks every part fits and every price is real, and you get the best verified deal." Recommended: keep it, and add the seller line on the second beat: "Sellers see what builders want and where demand goes unfilled." Why: it passes the cold-read test (what it does, for whom) before any number.

## LATEST DIRECTION (Fri 20:53; overrides anything below that conflicts)
- Name: Bidding Royale (repo cal-hacks-2026). Older text below may say "Bazaar"; read it as Bidding Royale.
- **Who it is for:** people who upgrade or build a PC, and the sellers who compete to supply them. **Customer we demo (from plan/research-pc.md): the upgrader whose agent remembers the parts they own**, buying one scarce part (a GPU or RAM) from many sellers inside an allowance, for example Joe (a demo persona, labelled). That is where marketplace scams live, so the advocate's veto matters most. Whole-build requests still work through the same flow. **Growth path and payer: small IT buyers** (a school, office or esports cafe buying 10 to 50 PCs), where sealed bids on volume are believable and the Hyphenate purchasing angle fits. Say both in Q&A; demo the consumer. Sellers: marketplace and used sellers, small PC shops and, in the demo, seller agents built from real scraped listings.
- **The problem (sponsor feedback: say why, for whom, what problem):** buying PC parts means checking many stores. Prices are wild right now: sourced facts we may say (plan/research-pc.md, each with its link there): an RTX 5090 lists at $4,999 against a $1,999 MSRP and an RTX 5070 Ti about 49 percent over (Capital & Compute citing Tom's Hardware, Sep 1 2026, tier 3 page), 32 GB of DDR5 costs at least $375 (Tom's Hardware headline), and PC gaming hardware is a $44.5 billion market up 35 percent in 2025 (Jon Peddie Research). **Never put a number on research time, the incompatibility rate or the return rate: none were found.** The qualitative pain: Parts must fit each other (socket, chipset, RAM generation, power, case and cooler clearance), prices move daily, a "was" price may not match the price history, an open-box or refurbished part can be sold as new, third-party marketplace sellers carry more risk than the retailer itself, and shipping fees and free-shipping thresholds change the real total. Builders pay for mistakes in time, returns and money. Sellers, meanwhile, cannot see what builders want, what is selling, or why they lost.
- **What we build:** Joe already owns a PC and the agent remembers it. He says: "I want a GPU that runs my games at 1440p and fits my case and PSU, and a 32 GB DDR5 kit, up to my allowance." The agent turns it into a Need (parts with must-haves and allowed alternatives, minus what he owns), posts it, and seller agents bid in a sealed round. A whole build from scratch uses the same flow. The quality advocate checks every bid, can veto the cheapest with cited sources, and can split the order across sellers when that is cheaper after shipping. The agent buys within Joe's limit after one approval, then the receiving check compares his photos of the delivery to the spec.
- **Seller benefit (changes a little from before):** besides winning orders, sellers get demand and trend intelligence: anonymized requests, which parts and brands are being asked for (keyboards up, for example), what sold, what lost and why (price, condition, shipping fee), and price points where demand went unfilled. Sellers never see an individual buyer; only aggregates with a minimum group size (invariant 10).
- **Same-spec comparison makes it checkable:** a part has a model number and a condition (new, open-box, refurbished, used). Bids for the same model and condition compare fairly. Where the builder allows alternatives ("any 8-core AM5 CPU"), the SpecCard lists which substitutes count.
- **CRS (their suggestion, kept):** CRS checks each seller's financial stability (credit, pending loans) inside our system; buyers and sellers see only a verified signal, never private data. Most useful for small or third-party sellers.
- **SPENDING ALLOWANCE AND VOICE APPROVAL (LOCKED Fri 21:00):** the builder sets an allowance. A deal inside the allowance auto-approves and sends a receipt. When a deal above the allowance is about to be finalized, a Cartesia voice agent calls the builder, reads out the deal (the parts, the price, the advocate's verdict, the savings), and the builder answers yes or no by voice. The answer is recorded (who, when, what was read, transcript or audio reference) before payment, and a "no" or no answer means no payment. This is the core of the Cartesia track: voice is the trust step, not a gimmick. Phone path: TO VERIFY. Per plan/research-pc.md (docs snippets, pages not opened): a Cartesia Line agent calls out from an imported Twilio number (`cartesia call <number> <agent_id>`) or through our own carrier by SIP trunk to `sip.cartesia.ai` (beta). It needs a Twilio number and Cartesia credits: confirm cost with Vidyut before the first call. Fallback is an in-browser voice call, labelled as such. Owner: Lane D (approval gate before payment), Lane B (voice UI and call screen). Lane B's approval-before-payment rule already fits: the voice answer is one more way to produce the `approval_id`.
- **OWNERSHIP MEMORY (LOCKED Fri 21:00):** the buyer agent remembers which parts the builder already owns or has bought, and advises from that: "you already own a 750 W PSU, skip it", "your RAM is fine for this GPU, keep it", "these should last a while". It never re-buys what the builder owns, and every piece of advice cites the memory entry it came from. Owner: Lane A. Contract: OwnedPart (see Contracts).
- **Data (from plan/research-pc.md; paid actors need Vidyut's OK before the first run):** Apify Store actors exist (slugs verified live Fri 20:56, run one small test first, low-user ones may break): Newegg `kawsar/newegg-product-scraper`, PCPartPicker `lulzasaur/pcpartpicker-scraper`, Micro Center `sian.agency/microcenter-product-scraper`, Best Buy `benthepythondev/bestbuy-scraper`, B&H `shahidirfan/B-H-Photo-Scraper`, eBay sold prices (used baseline) `caffein.dev/ebay-sold-listings`, eBay live `memo23/ebay-search-scraper-ppe`, Amazon `junglee/Amazon-crawler`. Bright Data datasets and scrapers are paid (check sponsor credits). **Recalls:** CPSC recalls API `saferproducts.gov/RestWebServices/Recall`, no key, returned 200 (coverage of PC parts is thin; a live call returns real records such as laptop AC adapters). **Compatibility:** `docyx/pc-part-dataset` (MIT, last push 2025-07-23): motherboards carry socket and form factor, memory carries speed, PSUs wattage, cases carry PSU type; CPUs have no socket field (map microarchitecture to socket in a small table) and GPUs have no power draw (add a small chipset-to-board-power table). Its prices are a mid-2025, pre-shortage snapshot: use as a dated baseline, labelled, and flag data rights before any commercial use. **Price history:** PCPartPicker trend charts are images only (no API); Keepa is paid and Amazon only; eBay sold listings are the cheap used baseline; our own mirror snapshots cover only the hackathon window, so older history is a labelled SIM series unless a source works.
- **Honesty about who bids:** big-box retailers will not change their price for one consumer order. Demo sellers are marketplace or used sellers, or SIM seller agents built from real scraped listings, labelled that way (docs/REAL_VS_SIMULATED.md). Real retailer prices are MIRROR sources, never "bidders". Any real seller that joins bids LIVE.
- **Real-people goal:** two real PC builders (Joe type) and one real seller or small PC shop in the loop, and one real build request through the agent, by Sat 14:00. Log in docs/INTERVIEWS.md.
- **VISA FEEDBACK (Fri 20:20, still holds):** trust is everything, and it must not be a chatbot or a chat window over agents. It must be an intelligent agent that acts on its own, saves real time and makes or saves real money, and shows both on screen (hours of research saved, dollars saved with how each was computed). For a one-time PC buy, "acts on its own" means: after the brief it runs the whole round without being asked (searches, sealed auction, compatibility and price checks, split plan, receiving check) and pings Joe once, with one approval card. Chat in ASI:One is for the brief, approvals and questions, not the product.
- **QUALITY ADVOCATE (quality is the top priority):** before any order it checks (1) **fit**: socket, chipset, RAM generation and speed, PSU wattage with headroom and the right connectors, case and cooler clearance (GPU length, cooler height), form factor; (2) **condition**: new, open-box, refurbished, or used sold as new; (3) **price**: a "was" price or discount against the price history (wording: "the price claim did not match the price history"), and total landed price with shipping and tax; (4) **seller**: our seller record from receiving results, marketplace third-party risk, counterfeit or relabel risk signals (never a verdict), return policy and warranty; (5) **recalls**: CPSC; (6) seller stability (CRS signal). Every warning cites a source. It can veto the cheapest bid when quality is worse, and must say why.
- **RECEIVING CHECK (closes the quality loop):** when the parts arrive, Joe snaps photos (box seal, model label, serial, damage, contents); a vision model compares them to the SpecCard photo checks; a reject or return is recorded against that seller and changes how the agent ranks it next time. Limit to state once: a photo check catches wrong model, not-new condition, missing parts and visible damage; it does not benchmark performance.
- Commits: never add a Co-Authored-By line or any Claude attribution.

You are one of four coding agents building Bidding Royale at Cal Hacks 13.0 (hacking Fri Oct 23 18:00 to HARD deadline Sun Oct 25 09:00 PDT; judging needs a live demo). All code is written during the hackathon.

## The product in one line (working line; the final pitch line is OPEN, Vidyut decides)
Bidding Royale is the buying agent for PC builders. Tell it your parts and budget: sellers bid, it checks every part fits and every price is real, and you get the best verified deal. Sellers learn what builders want.

## What it does
- A builder states a need in ASI:One (Fetch.ai), by voice or text: use, budget, specs, must-haves, parts to keep. Seller agents bid in a sealed round.
- The buyer-side quality advocate (Claude) checks every bid for fit, condition, price truth, seller record, recalls and seller stability, and can veto the cheapest bid with sources. It also picks the best split across sellers once shipping and free-shipping thresholds are counted.
- Royale Shield (our security API, the Armadin pitch) screens every agent-to-agent message, verifies agent identity and checks seller claims against the live web (Apify, Bright Data). A seller whose claim does not match the page is flagged with evidence.
- Checkout: the Fetch.ai Payment Protocol on the rails ASI:One supports today, Stripe (test mode) or Link, charging a Visa test card, always within the builder's limit. Every agent request to a seller is signed under Visa's Trusted Agent Protocol (real, not mocked). Never say "Visa settles". A Visa Intelligent Commerce adapter sits behind the same interface and swaps in only if Visa grants sandbox access.
- Receiving check: photos of the delivery compared to the spec; rejects feed the seller's quality record.
- Allowance and voice approval: deals inside the builder's allowance auto-approve with a receipt; a bigger deal triggers a Cartesia voice call that reads the deal and records the builder's yes or no before payment.
- Ownership memory: the agent knows what the builder already owns, never re-buys it, and cites the memory entry in its advice.
- Sellers train their bidding agents in the wind tunnel: hundreds of simulated builders, honest and hostile, built from CRS test identities, against an Apify mirror of the seller's catalog. The seller dashboard shows demand and trend intelligence.
- The 3D persona floor shows the live auction as seller characters haggling. It only renders real market state.

## Term map (use these words in code, tests, UI and docs)
| Restaurant term (retired) | PC term |
|---|---|
| restaurant, owner, kitchen manager | builder (buyer), the agent's owner |
| supplier, Sysco, produce house | seller (retailer, marketplace seller, PC shop) |
| order guide, weekly order | build brief, parts list |
| grade (USDA Choice, No. 1) | condition (new, open-box, refurbished, used) |
| pack size, case count | variant (retail box or OEM, with or without cooler), model number |
| spec equivalence | spec and fit equivalence (same model, or an allowed substitute that still fits) |
| openFDA food recall | CPSC recall |
| USDA wholesale baseline | price history and best public price (dated) |
| supplier minimum order, cutoff | free-shipping threshold, shipping fee, ship-by time |
| receiving check on cases | receiving check on a delivered box |
| credit memo, reject credit | return or refund request, RMA |
| usage history and forecast | demand history and trend signal (seller side) |
| spoilage, waste avoided | wrong-part returns avoided |

## Invariants (never break these)
1. No money moves without a limit check and an approval: auto-approval only inside the builder's allowance (with a receipt), otherwise the approval card or the recorded voice yes from the Cartesia call. No answer means no payment.
2. Every seller claim shown to a builder carries a live-check result: verified, unverified or false.
3. No agent acts on another agent's text before a Shield screen.
4. The 3D floor and every screen render real market state only.
5. A seller agent never bids below its floor price; the ledger balances after every order.
6. Sandbox and test identities only; no real cards; no secrets in the repo (.env.example names only).
7. Anything simulated is labelled in the UI and the README.
8. Sealed bids: sellers never see the builder's budget or each other's bids.
9. Private financial data (CRS) stays inside Lane D; both sides see only the stability signal.
10. (New with the pivot) Sellers never see an individual builder. Demand and trend views are aggregates, shown only when a group has at least 5 requests (proposed minimum; Vidyut may change it). Requests are stripped of names and contact data before they enter the seller view.
11. The agent never re-buys a part in the builder's ownership memory unless the builder asks, and advice cites its memory entry.

## MLH tracks that help both sides (added Fri 21:00; source plan/research-sponsors-b.md "MLH tracks"; none of these changes the core)
| Track | Status | What it does for builders and sellers | Cost to us |
|---|---|---|---|
| Tiger Data (Best Use of Tiger Data) | Recommended | Price history and demand trends as time series in Postgres with continuous aggregates: builders see real price history behind a "was" price; sellers see demand by category per week. Owner: Lane C. Check free trial limits (TO VERIFY). | Low, and it fixes our thin price-history gap |
| Snowflake (Best Use of Snowflake API) | Optional | Seller insights warehouse. Overlaps with Tiger Data; pick one unless a lane is idle. | Medium |
| Gemini (Best Use of Gemini API) | Optional | One honest model step, for example photo reading in the receiving check, only if it works better than Claude there. Never add it just for the badge. | Low |
| GoDaddy Registry domain | Free add | Register a project domain; MLH code is usually free (REPORTED, TO VERIFY for 2026). Owner: Vidyut. | Near zero |
| MLH Commit Fellowship | Opt in | Real problem plus a team; opt in on Devpost with the supplemental form. Owner: Vidyut. | Near zero |

## Repo layout (each lane owns its folder; touch others only through contracts/)
- contracts/  shared JSON schemas (owned by everyone; change only with a note in docs/CHANGES.md)
- agents/     Lane A: Python uAgents (buyer, advocate, seller agents)
- market/     Lane B: SpacetimeDB module (auction state) and market/rules (sealing, scoring, optimizer, outcomes)
- web/        Lane B: Next.js builder view, seller dashboard, 3D floor (three.js)
- data/       Lane C: Apify and Bright Data adapters, seller mirrors, price history, compatibility rules, demand and trend
- shield/     Lane D: FastAPI Royale Shield API (/screen, /verify-agent, /check-claim)
- pay/        Lane D: Visa, CRS adapters, finance ledger
- sim/        Lane D: wind tunnel (simulated builders, hostile agents)
- docs/       README, sponsor map, real-vs-simulated table, demo script

## Contracts (first version is in contracts/; every lane mocks the others from these)
- Need {id, buyer_id, items[{sku_spec, condition, variant, quantity, unit}], use_case, budget, delivery_window, spend_limit, consent, auction_window_s, source}
- SpecCard {id, sku_spec, item_name, condition, variant, allowed_substitutes[], attrs{socket, chipset, ram_type, tdp_w, length_mm, height_mm, form_factor, connectors}, photo_checks[], source} (proposed by Lane B, attrs new with the pivot)
- SupplierTerms {supplier_id, shipping_fee, free_shipping_over, ship_by_time, delivery_days_est, return_window_days, source}
- Bid {id, need_id, supplier_id, persona, lines[], total_landed_price, perks[], claims[], floor_check_passed, mirror_snapshot_id, decision_trace, expires_at, source}
- Claim {id, bid_id, text, kind: stock|shipping|fees|returns|price|condition|warranty, check: verified|unverified|false, evidence_url, checked_at, method, evidence_hash}
- ShieldVerdict {message_id, sender_agent, verdict: allow|quarantine|block, reasons[], attack_type}
- SupplierSignal {supplier_id, signal: verified_stable|caution|not_verified}
- AdvocateCard {need_id, bid_id, warnings[{kind, text, source_url}], recommendation, wait_until}
- OrderPlan {id, need_id, mode: cheapest_per_line|optimizer, advocate, allocations[], subtotal, fees, total, savings_vs_baseline, explanation[], source}
- Order {id, need_id, bid_id, amount, approved_by, payment_ref, status, idempotency_key, approval_id, limit_checked}
- OwnedPart {id, buyer_id, sku_spec, item_name, condition, acquired_on, source: bought_here|told_by_user|imported, attrs{...as SpecCard}, notes} (new Fri 21:00, owner Lane A; log in docs/CHANGES.md before merge; the buyer's profile is the set of its OwnedParts plus its allowance)
- Allowance {buyer_id, auto_approve_up_to, currency, voice_confirm_above, phone_ref (a reference, never a raw number in the repo)} and VoiceApproval {id, order_id, called_at, deal_summary, answer: yes|no|no_answer, recorded_ref, approval_id} (new Fri 21:00, owner Lane D; log in docs/CHANGES.md)
- ReceivingEvent, QualityRecord (seller record), LedgerEntry, Persona, FloorEvent (v2)
- DemandRecord and TrendSignal replace UsageRecord and Forecast (proposed rename; seller side, aggregate only)
Contract changes go in docs/CHANGES.md first. Lane B's proposals (SpecCard, SupplierTerms, OrderPlan, ReceivingEvent, QualityRecord, FloorEvent v2) are on branch lane-b-market-floor and stand unless someone objects on the board.

## What we show sponsors at 10:00 (TALKABLE PROGRESS gate, Sat 10:00; real where possible, everything labelled LIVE, MIRROR or SIM)
1. Joe, an upgrader whose agent remembers his rig, asks in ASI:One for a GPU and a 32 GB DDR5 kit inside his allowance (Lane A); the buyer agent turns it into a Need and the sealed round opens with marketplace, used and SIM seller agents built from real scraped listings (Lanes A, B, C).
2. The advocate vetoes the cheapest bid (a used-as-new risk, a price far below the used baseline, or a part that does not fit), and flags a "was" price that did not match the price history, each with a source; the split plan beats cheapest-per-line once shipping is counted (Lanes A, B, C).
3. Memory skips the PSU Joe already owns, checks the GPU against his case and PSU, and says why, citing the entry (Lane A).
4. A deal above his allowance triggers the Cartesia call, he says yes, and the answer is recorded; Stripe test mode charges a Visa test card with a verified Trusted Agent Protocol signature, and Shield quarantines a planted payee swap (Lane D, Lane B voice UI).
5. The seller dashboard shows demand trends and why bids were lost (SIM plus a public MIRROR signal), and the 3D floor mirrors every step (Lane B, Lane C).
After 10:00 the plan is: fold in sponsor and judge feedback, then visual polish, then demo and pitch.

## Milestones (PDT)
- Fri 20:00 contracts merged; every lane has a stub that reads and writes them. (Met in the restaurant shape; rename pass for the PC terms by Fri 22:30.)
- Fri 23:00 mocked end-to-end: build brief, three to four bids, advocate card, approve, fake payment, floor shows it.
- Sat 03:00 first real path: real Apify mirror bids, real Claude advocate, real Shield verdict, Visa or CRS sandbox call.
- Sat 10:00 TALKABLE PROGRESS: a demo we can show sponsors (list above), real where possible and labelled. Second round of sponsor and judge feedback.
- Sat 14:00 demo path green on the deployed build.
- Sat 19:00 video storyboard. Sun 03:00 feature freeze. Sun 06:00 Devpost done. Sun 08:30 submitted.

## Working rules
- Branch per task, small commits, open a PR to main; main must always run.
- Write the failing test first for logic (auction rules, compatibility rules, Shield, ledger, claim checks).
- Post what you finished and what you need in docs/BOARD.md (one line per post, newest at the bottom).
- Demo path first, polish later. When behind, cut in this order: hardware terminal becomes webcam scan, wind tunnel shrinks to 50 builders, real-store mirrors become seeded demo sellers. The 3D floor was decided to be built from the start; 2D sprites are an emergency fallback only.
- Sponsor requirements are in docs/SPONSORS.md; keep README's sponsor table honest.
- Wording rule: never call a real store a liar. Say "the price claim did not match the price history" or "differs from the listing at time T" or "could not verify". The planted liar runs only on pages we host.
- No em dashes or en dashes anywhere (copy, code, comments, commits).

## Red-team amendments (Fri 17:35, updated for the pivot Fri 21:00; these override anything above)
0. Hero community: Bay Area students and hobbyists who already own a PC and are upgrading it (GPU or RAM first). Interview 3 to 5 at the venue Friday night, one seller or small PC shop on Saturday, and, if reachable, one small IT buyer (school, office, esports cafe); one quote and one real receipt or parts list open the pitch.
1. The hero loop is the contract: build brief in ASI:One, then 3 to 6 sealed bids, one planted liar caught with evidence, the advocate card with cited warnings, the approval card, payment, the receiving check, and the floor mirroring every step. Tier 0 (this loop) green by Sat 14:00. Tier 1: Shield console, wind tunnel numbers, seller demand dashboard, persona voices on the floor. The Cartesia approval call is Tier 0 (amendment 15). Tier 2: 3D polish, hardware, extra personas, the Hyphenate seller finance desk (pending Open decision 2).
2. Kill rules: Spacetime go or no-go Fri 23:00 (Convex fallback); Visa credentials go or no-go Sat 03:00; no 3D feature work after Sat 22:00. Never drop Shield, Apify or the claim check. One integration owner runs the demo path every 3 hours from Sat 03:00.
3. Every Bid and Claim carries a source field (live, mirror with date, simulated, sandbox, recorded); every screen shows a LIVE, MIRROR or SIM badge; docs/REAL_VS_SIMULATED.md exists from hour one. Contract fields: Need.spend_limit, Need.consent, Need.auction_window_s; Bid.total_landed_price, Bid.floor_check_passed, Bid.mirror_snapshot_id, Bid.decision_trace; Claim.checked_at, Claim.method, Claim.evidence_hash; Order.idempotency_key, Order.approval_id, Order.limit_checked; FloorEvent.
4. Sealed bids until the deadline (short anti-snipe extension); sellers never see the builder's budget; bids are computed by policy code (SellerPolicy) and the LLM only writes the persona's line; floor, approval-before-payment and the balanced ledger are enforced in the market reducers. Reproduce Microsoft Magentic Marketplace's two published failures (first-proposal bias, payment redirect) and show both fixed.
5. The planted liar runs against seller pages we host ("Honest Hal", "Shady Sam" with a lie toggle: for example a fake "was" price, an open-box part listed as new, a wrong socket) so it works on any wifi. Real stores only supply price and policy truth, with neutral wording. Never call a real store a liar.
6. ASI:One drives; the floor is a read-only second screen of the same state ("same market, two views"). Register about 6 agents on Agentverse (buyer, advocate, Shield, seller gateway, two named sellers); run the rest as a labelled fleet. Stream progress during a 12 to 15 second auction window. Host agents on Agentverse or a cloud VM, never a laptop.
7. Invariant 9 (was 8): the builder's and seller's financial data never leaves Lane D; the other side gets a signal or pass and fail only. A consent card before any CRS read lists the exact fields; show bands, never raw scores.
8. RunMode per adapter: live, cached or replay, 4 to 6 second timeouts, committed snapshot fallback, a footer badge showing the active mode, /health per service. A labelled recorded run of the full path exists by Sat 14:00. Test every required domain from the cloud sessions in the first 30 minutes.
9. Measured numbers, method fixed Friday night (Lane C gate): real price dispersion across sellers against a timestamped baseline; simulated discount (labelled simulated); advocate precision and recall on a 30 to 50 item answer key with clean controls (fit errors, wrong condition, false "was" prices, planted recall); fit-checker accuracy on a hand-checked set of part pairs. Wind tunnel and Shield report on held-out sets, with Shield's false-positive rate and latency. Drop any advocate warning whose evidence does not support it; cap at three warnings; keep "buy anyway".
10. Business: pricing is OPEN (Open decision 1, Vidyut decides). Until he rules, the repo shows the recommendation only as a proposal. Bids compete on price, perks, speed and verified-claim record, not price alone. Show "cost of this auction" on the seller dashboard.
11. Payment seam: CommitPayment carries a signed mandate (amount cap, one merchant per charge, expiry, single use) that the seller verifies; idempotency keys; a plain-text fallback if Interactive Cards misbehave (numbered bids, reply APPROVE id). A split order is several mandates, one per seller.
12. Shield is commerce-specific: mandate consistency (payee or amount differs from the approved need), claim truth against the page, cross-bid collusion and lookalike-shop signals. It consumes Trusted Agent Protocol signatures rather than inventing identity. One shared decorator enforces screening (rules under 50 ms, a small model only for ambiguous text, 1.5 second timeout, fail closed for payments). Add a "Hack the market" console for judges.
13. Sponsor depth: primary tracks are Fetch.ai, Visa, Apify and Spacetime. Apify: publish the claim-verification Actor by Sat 12:00. Every other sponsor gets one load-bearing beat with an owner, or is labelled out of the README by Sat 14:00.
14. (New with the pivot) The two judge toggles stay: "cheapest per line" versus "optimizer" (free-shipping thresholds and fees make per-line cheapest wrong) and "advocate off" (cheapest wins and the wrong-socket board and the open-box-as-new part get ordered). All demo numbers are filled live from Lane C data, never typed by hand.
15. (New Fri 21:00) The Cartesia call is a Tier 0 beat, not decoration: the demo includes one deal above the allowance that triggers the call, and one inside it that auto-approves with a receipt. Cartesia's rules apply: voice core to the product, README lists setup, the Cartesia features used and known limitations, 2-minute demo-first presentation. If the phone carrier is not working by Sat 03:00, the in-browser voice call is the demo path and the README says so.
16. (New Fri 21:00) Ownership memory is shown in the demo: one part the builder already owns is skipped, with the memory entry cited on the card.
