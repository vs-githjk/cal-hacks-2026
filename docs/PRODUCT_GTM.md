# Fish Market: product, ICP, demo and go-to-market (PC direction)

Rewritten Fri Oct 23 2026, about 21:05 PDT for the pivot from restaurants to PC upgraders and builders. The restaurant version is in git history and docs/RESEARCH_RESTAURANTS.md. Every fact below comes from plan/research-pc.md (team plan folder), docs/kickoff/00-shared.md or plan/decisions.md. Anything not sourced is marked as an assumption or OPEN. No number is given for research time, incompatibility rate or return rate: none were found.

## 1. The product and its job

**One sentence (working line; the final pitch line is OPEN, Vidyut decides):** Fish Market is the buying agent for PC builders. Tell it your parts and budget: sellers bid, it checks every part fits and every price is real, and you get the best verified deal.

**The job:** an upgrader who already owns a rig wants one scarce part (a GPU or RAM) inside an allowance. The agent knows what they own, gets sellers to bid in a sealed round, throws out parts that do not fit, used parts sold as new and price claims that did not match the price history, buys inside the allowance, and calls the builder by voice for anything above it. At delivery it checks photos against the spec.

**Customer to demo:** the upgrader with remembered parts, because single scarce parts are where prices and marketplace scams hurt most, so the advocate's veto is visible. **Growth path and payer:** small IT buyers (a school, office or esports cafe buying 10 to 50 PCs), where sealed bids on volume are believable and the Hyphenate purchasing angle fits. We say both in Q&A and demo the consumer. Windows 10 support ended Oct 14 2025 (Microsoft, reported in the research file), a reason small buyers are upgrading; SMB buyer pain itself was not checked.

**Honest weakness, said openly:** big-box retailers will not change their price for one consumer order. Demo sellers are agents for marketplace or used sellers, or SIM sellers built from real scraped listings, labelled SIM over MIRROR.

## 2. The technical core (what judges should see as hard)

Each component has a deterministic core in code (tested), a model only where perception or wording is needed, and a toggle or number that proves the code causes the result.

| # | Component | Why it is hard | Proof a judge can see | Lane |
|---|---|---|---|---|
| 1 | **Fit checker and spec normalizer.** SpecCards with attributes (socket, chipset, RAM type, power draw, lengths, form factor, connectors) from docyx/pc-part-dataset plus two small tables (CPU microarchitecture to socket, GPU chipset to board power). Verdict: fits, does not fit (reason) or uncertain | Data gaps are real (the dataset has no CPU socket field and no GPU power draw); unknown must say "uncertain", never guess | Accuracy on a hand-checked set of part combinations; "board is AM4, CPU is AM5" with the reason on screen | C |
| 2 | **Sealed round plus split-order optimizer.** Sealed until the deadline, floor in the reducer, then the best split across sellers after shipping fees and free-shipping thresholds (built and tested on lane-b-market-floor) | Per-line cheapest is wrong once fees and thresholds exist | Toggle "cheapest per line" versus "optimizer"; property tests on the rules | B, A |
| 3 | **Quality advocate with veto.** Fit (from 1), condition (new, open-box, refurbished, used sold as new), price truth against history and a used baseline, seller record, third-party and counterfeit risk signals, return policy, CPSC recalls, CRS stability. At most 3 warnings, each with a source; a validator drops any warning its evidence does not support; "buy anyway" stays | Grounding enforced in code; a cheaper bid loses only for a cited reason | Toggle "advocate off": the wrong-socket board and the open-box part get ordered. Precision and recall on a 30 to 50 case key | A, C |
| 4 | **Ownership memory.** OwnedPart records; never re-buys what the builder owns; advice cites the entry ("you already own a 750 W PSU, skip it") | Advice must come from a stated rule, not a guess ("these should last a while" needs data) | A card line citing the memory entry; a test that an owned part is dropped from the Need | A |
| 5 | **Allowance gate and Cartesia voice approval.** Inside the allowance: auto-approve with a receipt. Above it: a voice call reads the deal, the spoken yes or no is recorded before payment | The approval must be bound to the deal it was read for; no answer means no payment | Test that a yes for deal A cannot approve deal B; a recorded call in the demo | D, B |
| 6 | **Trust rails for money and messages.** Shield screens every seller reply; signed mandate (amount cap, one seller, expiry, single use) under Visa Trusted Agent Protocol signatures; payment via the Fetch.ai Payment Protocol on Stripe test mode with a Visa test card | An injection that lands still cannot pay because the mandate's payee and amount do not match | Shield quarantines a planted payee swap with "mandate mismatch"; the payment reference appears on the card | D |
| 7 | **Receiving check.** Photos compared to SpecCard photo checks (sealed box, model label, serial, contents, damage); rejects feed the seller record | A photo catches wrong model, not-new condition, missing parts and visible damage, not performance (we say so once) | The seller rejected last time ranks lower next time, with the decision trace | C, B |
| 8 | **Seller demand and trends.** Anonymized requests aggregated (minimum group of 5): what was asked, at what ceiling, what lost and why, where demand went unfilled | In the demo it is SIM plus a public MIRROR signal; its value to sellers is a hypothesis, not evidence | The dashboard panel with SIM and MIRROR badges; the interview answers from a real seller | C, B |

### What each sponsor contributes to the core vs what is optional

| Sponsor | Load-bearing in the core | Optional or labelled out |
|---|---|---|
| Fetch.ai | Buyer, advocate and 2 or 3 seller agents on Agentverse with Chat Protocol; the approval card; Payment Protocol commit | 10 to 20 persona seller agents (cut to a handful plus a labelled fleet) |
| Visa | TAP signatures on every request and order, the signed mandate, the Visa test card charge: the trust story Visa asked for | Intelligent Commerce adapter, only if sandbox access arrives |
| Cartesia | The approval call above the allowance: voice is the trust step (Tier 0). Phone path via imported Twilio number or SIP is TO VERIFY and needs credits (confirm cost first); in-browser call is the fallback | Persona voices on the floor (Tier 1) |
| Apify | Retailer actors feed the mirror (slugs in the research file; paid, need approval); our published claim-check Actor | Extra retailers |
| Anthropic (Claude) | Advocate wording, memory advice, receiving photo reading. Checks and math stay in code | Long free-text chat |
| Spacetime | Round state, sealed reveal and floor in reducers, live views | Convex fallback decision Fri 23:00 |
| CRS | Seller stability signal, signal only (never a raw score) | |
| Armadin | Shield screening is core | Attacker swarm and judge console are Tier 1 or 2 |
| Bright Data | Pages Apify misses; wider price checks (paid) | |
| Hyphenate | OPEN, Vidyut decides. Recommended Tier 2: seller finance desk, or the small IT buyer purchasing angle for the growth path | Drop from the README by Sat 14:00 if not built |
| Tiger Data (MLH) | Recommended: price history and demand trends as time series | Snowflake and Gemini optional; GoDaddy domain and Commit Fellowship are free adds |

## 3. ICP, payer, first 10, pricing, the one metric

- **ICP now:** Bay Area students and hobbyists who own a PC and are upgrading it (GPU or RAM first). **Next:** small IT buyers buying 10 to 50 PCs. **Seller side:** marketplace and used sellers, small PC shops, and later brands and retailers that would pay for demand data.
- **First 10 conversations, this weekend:** 3 to 5 builders at the venue tonight (parts list or receipt, their own numbers), 1 seller or small PC shop on Saturday, 1 small IT buyer if reachable. Scripts are in docs/INTERVIEWS.md. Never post to forums or cold-message on LinkedIn without Vidyut's approval (standing rules).
- **Pricing:** OPEN, Vidyut decides. The old test (15% of verified savings capped at $299 a month) was written for a restaurant buying weekly. Recommended option: builders free; sellers pay a small success fee only on a won, approved order; a paid demand-insights plan for sellers and brands tested in interviews. The research file has no sourced fee rates, so every rate is an assumption. Comparable data products exist (Keepa API from about EUR 49 a month, Similarweb small-business average about $12.4 thousand a year, both reported, not verified); nobody found sells "demand we saw but could not fill at your price", so its value is a hypothesis.
- **The one metric to prove:** verified dollars saved or scams and misfits avoided per request, each with a source and method. Report results that show no effect.

## 4. The 90-second demo (Vidyut the upgrader)

Two screens, same state: ASI:One on a phone and the builder view on a laptop, with the 3D floor as the second view. Every price is filled live by Lane C and carries a LIVE, MIRROR or SIM badge; none is typed by hand.

| Time | Screen | Beat |
|---|---|---|
| 0 to 10 s | ASI:One | Vidyut already owns a rig (the rig data is labelled SIM) the agent remembers. Vidyut asks for a GPU that fits the case and PSU plus a 32 GB DDR5 kit, up to the allowance. "You already own a 750 W PSU, skip it" (memory entry cited). No chat window beyond the request. |
| 10 to 30 s | Builder view and floor | Sealed round opens to marketplace, used and SIM sellers. Bids reveal at the deadline. |
| 30 to 55 s | Builder view | The cheapest bid is vetoed with sources (does not fit, or used sold as new, or a price far below the used baseline). A "was" price is flagged: "the price claim did not match the price history". Shield quarantines a planted payee swap. The optimizer split beats cheapest-per-line once shipping is counted (toggle shown once). |
| 55 to 75 s | Phone | The deal is above the allowance, so the Cartesia agent calls, reads the parts, price, verdict and savings, and Vidyut says yes. The recorded answer appears, then the Stripe test charge on a Visa test card with the verified signature. A smaller deal inside the allowance auto-approves with a receipt. |
| 75 to 90 s | Phone camera, then seller dashboard | Delivery photo check; a reject updates the seller record. Switch to the seller dashboard: demand this week, why bids were lost, where demand went unfilled (SIM plus MIRROR badges). |

**Numbers safe to put on screen:** computed from the demo's own data with "how computed"; a context strip using only the sourced facts in the research file (GPU street prices against launch prices, DDR5 at $375 minimum, the $44.5 billion market), each with its source. Never on screen: research time, incompatibility rate, return rate, any claim that a big-box retailer bid, any wording that a real store lied.

## 5. Cuts and the riskiest assumptions

**Tier 0 hero loop (green by Sat 14:00; talkable version by Sat 10:00):** upgrade request, memory, sealed round, fit checker, advocate veto, allowance gate and voice call, signed mandate and test payment, receiving check. **Tier 1:** Shield console, wind tunnel numbers, seller dashboard polish, persona voices. **Tier 2:** 3D polish, extra personas, a seller finance desk.

| # | Assumption | Test | Pass line | If it fails |
|---|---|---|---|---|
| 1 | Sealed bids from marketplace or SIM sellers look believable to a judge | Show the round to 2 builders and 1 seller | They say the labels are clear and the round makes sense | Lead with the advocate veto and the voice call; say plainly which sellers are simulated |
| 2 | The fit checker is right on real combinations | 20 hand-checked cases with tests first | No false "fits" on known mismatches | Return "uncertain" more often and say so |
| 3 | A builder will let an agent buy inside an allowance and wants a call above it | 3 builder conversations (script in docs/INTERVIEWS.md) | 2 of 3 name an allowance and accept the call | Approve-every-order by default; keep the call for above a low limit |
| 4 | The phone call path works | Twilio or SIP test Sat by 09:00 | A call is placed and answered | In-browser call is the demo path, labelled |
| 5 | Sellers value demand trends | 1 seller interview | They name a decision it would change | Keep the dashboard as a SIM demo and say it is a hypothesis |

## 6. Claims this pitch makes (all planned until a lane proves them)
- C1 | planned | the agent remembers owned parts and skips them | proof: memory test and card citing the entry
- C2 | planned | sealed bid round, reveal at the deadline | proof: reducer property tests
- C3 | planned | rejects a part that does not fit | proof: fit-checker tests and answer key
- C4 | planned | flags a price claim that did not match the price history | proof: claim check with evidence and dates
- C5 | planned | above the allowance a voice call asks and records yes or no before payment | proof: approval gate test and a recorded call
- C6 | planned | Stripe test charge on a Visa test card with a verified Trusted Agent Protocol signature | proof: payment reference, signature verification test
- C7 | planned | seller record from receiving changes the next ranking | proof: decision trace across two runs
- C8 | built as a source fact | GPU and DDR5 price facts and the $44.5 billion market | proof: research-pc.md section 6 links
