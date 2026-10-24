# Tech Bazaar

**A buyer's agent for scarce, scam-prone goods, starting with computer gear. You give it a goal, seller agents bid for it, an advocate vetoes the traps with a source, and nothing is paid until you approve on a two-way voice call.**

A refereed arena for agent commerce. Seller agents learn from every loss, and Bazaar Shield, our security API, blocks agents that try to cheat.

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Built at Cal Hacks 13.0 (October 23 to 25, 2026) by a team of four.

> **Status, Fri Oct 23, about 21:45 PDT.** Hacking started at 18:00. This README describes the design we are building. A piece counts as working only when the [Status](#status) table says "built" and links the proof. The demo video and live link go here once they exist.

**The five beats of the demo:** (1) set a goal; (2) sellers bid and the advocate vetoes a trap with a source; (3) Shield blocks an injected listing live; (4) the two-way call approves above the allowance; (5) the seller's loss report and learning. Everything on screen is labelled LIVE, MIRROR or SIM.

**Jump to:** [Problem](#the-problem) · [What it does](#what-tech-bazaar-does) · [How it works](#how-it-works) · [Architecture](docs/ARCHITECTURE.md) · [Sponsors](#sponsor-technology) · [Real vs simulated](#real-vs-simulated) · [Agents](#fetchai-agents) · [Quickstart](#quickstart) · [Safety](#invariants-safety-by-design) · [Status](#status)

---

## The problem

**Who feels it:** people who upgrade or build a PC. The one we design for first is the **upgrader**: someone who already owns a rig and needs one scarce part, a graphics card or memory, at a fair price from a seller they can trust. Our growth path is **small IT buyers** (a school, an office, an esports cafe) buying 10 to 50 PCs.

**What hurts:**

- **Prices are wild.** An RTX 5090 lists at $4,999 against a $1,999 launch price, and an RTX 5070 Ti is about 49 percent over its launch price (Capital & Compute, citing Tom's Hardware, Sep 1 2026). 32 GB of DDR5 now costs at least $375 (Tom's Hardware). PC gaming hardware is a $44.5 billion market, up 35 percent in 2025 (Jon Peddie Research). Sources and caveats are in the team's PC research notes (plan/research-pc.md, section 6), which list a link and a verified or reported label for each fact.
- **Parts must fit each other.** CPU socket and motherboard, RAM generation, power supply wattage and connectors, case and cooler clearance. A part that does not fit is a return and lost days.
- **Cheapest is not always safe.** Marketplace listings can be used or open-box parts sold as new, a "was" price can fail to match the price history, and a third-party seller carries more risk than the retailer. Press reports of an RTX 5090 shipped without its chip and of return-swap scams show where the risk sits (each is reported, not verified by us; see the research file).
- **Sellers fly blind.** They cannot see what builders asked for, at what ceiling, or why they lost.

We have no sourced number for research time, compatibility mistakes or return rates, so we do not claim one. Our interviews ask for theirs ([docs/INTERVIEWS.md](docs/INTERVIEWS.md)).

## What Tech Bazaar does

You give your **buyer agent a goal**, not a one-shot order: "spend at most X", "this part under this price by this day", or "assemble this build under this price by this day". It **remembers the parts you already own**, so it never re-buys them. It hunts over time and **tells you after each step** (deal found, bid in, veto, progress to goal). **Seller agents** bid in a sealed round. Your **advocate** checks fit with code and every claim against the live page, and **vetoes the cheapest bid when it is a trap, with the source** ("listed as new, the page says open box"). **Bazaar Shield** screens every message and blocks an injected listing before it reaches the advocate.

You set an **allowance**, which starts at $0 and rises with each clean delivery. Above it, the agent **calls you**. You can ask "why not the cheaper one?" and it answers aloud. You approve by speaking a one-time word-pair code from your screen, and the system reads the amount back. Silence or any mismatch means no. The approval is bound to a signed mandate for that exact deal.

Losing sellers get a **loss report** (a banded gap and the reason with its source) and their agents adjust a small, inspectable strategy inside their owner's rules.

**The multiverse.** The demo is one universe of one order. The real market has many buyers whose requests pool by exact SKU, and sellers bid a price ladder by quantity on the pooled lot. The **Lot Wall** (a later item, built from real lot rows once the core loop works) shows it: Joe's brick is gold and labelled REAL, the rest are grey and labelled SIM, and the sealed bids slide down the price tiers. One or two bids are real, the rest are labelled simulated. We do not claim many people use it.

**Fully agentic:** every seller is a Fetch.ai uAgent on Agentverse. A real non-agent seller side is coming later, or only if time remains after the agentic path.

**Scope:** all computer gear (PCs, parts, laptops, monitors, peripherals). The first payer we design for is the small IT buyer (10 to 50 machines, with approvals and purchase orders), priced per refresh (proposed, finalized later). Named adapters, shown as add-ons and not extra beats: CRS identity and fraud check on business sellers, Hyphenate IT buyer purchasing (PO, three-way match, audit), the IT fleet view, Tiger Data time series, and Bright Data baselines.

**Shield as an API.** `POST /v1/shield/screen`, `/verify-agent`, `/check-claim` and `/verify-mandate`, with a versioned schema, signed verdict receipts and a `shield-bench` for any attack swarm. A "Hack the market" console lets a judge write a hostile listing and watch it blocked or not; every attempt is counted.

## How it works

1. **Goal.** You state a goal in ASI:One. The agent turns it into a Goal (budget cap, part price by date, or build price by date) and a sealed request, after skipping parts you already own and citing the memory entry.
2. **Bid.** Seller agents bid until the deadline from their owner's real listings (MIRROR) or as simulated builders' counterparts (SIM); an outside Agentverse agent that speaks the open seller protocol bids LIVE. Bids stay sealed, sellers never see your budget, and a reducer rejects any bid below a seller's floor. Every bid carries an origin badge and a listing link.
3. **Screen.** Shield screens every seller message, listing title and claim before the advocate sees it: injection patterns, payee changes, identity mismatch. A blocked message is quarantined on screen with the rule that fired. Business sellers pass a CRS identity and fraud check first.
4. **Veto.** The advocate (Claude, closed output schema) checks fit by code (socket, length, PSU wattage), condition and price claims against the live page with our Apify claim-check Actor, CPSC recalls and the seller record. It can veto the cheapest bid with the source. It never sees the fee.
5. **Notify.** After each step you get one event per class (deal found, bid in, veto, progress), throttled to one per class per 10 minutes. Quotes expire after 10 minutes.
6. **Call.** Above your allowance the agent calls you (in-browser Cartesia call by default, phone via Photon SIP if proven). It reads amount and payee from a template filled by code, answers "why not the cheaper one?" from the advocate's cited reason, and asks for the code. The mandate binds deal id, amount, payee, expiry and nonce, and a typed fallback is labelled.
7. **Pay.** The request is signed under Visa's Trusted Agent Protocol and the Fetch.ai Payment Protocol charges a Visa test card through Stripe test mode. Our merchant simulator verifies the signature. A replayed or altered mandate fails on screen. No payment exists without an approval for the same mandate hash.
8. **Receive.** Photos of the delivery are checked against the spec. A clean check raises your allowance and the seller's record; a failed one writes a credit memo and the loss report says why.
9. **Learn.** Each losing seller gets a loss report and updates its strategy (price step, bundle, delivery promise, condition disclosure). Before going live, sellers train in a wind tunnel of simulated builders against a frozen control seller; the result is labelled SIM and reported with seeds and intervals.

Diagram, components and data flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Why this is different

- **The buyer has a skeptic on its side.** A price list tells you what is cheapest. The advocate tells you when the cheapest bid will not fit, is not new, or carries a price claim that did not match the price history, and it cites a source for every warning.
- **It remembers your rig.** Existing scanners cover one brand's memory or storage (Crucial, Corsair and Kingston scanners, per our research). We found no checked tool that remembers your whole rig across sellers and advises from it (not proof that none exists).
- **Voice is the trust step, and voice is never the credential.** Spending above your allowance needs a one-time word-pair code from your screen, spoken on a call about one exact mandate. A recording of your voice cannot approve it.
- **Known agent-market failures are designed out.** Microsoft's Magentic Marketplace study (arXiv 2510.25779) found that buyer agents favor the first proposal they see and that malicious sellers can redirect payments. Sealed bids remove the first-mover advantage. Shield's mandate check blocks any payment whose payee or amount differs from what you approved.
- **Identity says who; Shield says whether it is true.** Visa's Trusted Agent Protocol proves which agent sent a request. Shield checks whether what that agent claims holds up.
- **Privacy by design.** CRS identity and fraud checks on business sellers share only a band. Sellers see aggregate pool data (SKU, quantity, ceiling band, deadline), never an individual buyer.

## Sponsor technology

| Sponsor | Product | What it does in Tech Bazaar | Depth |
|---|---|---|---|
| Fetch.ai | uAgents, Agentverse, ASI:One, Agent Chat Protocol | Every agent is a uAgent registered on Agentverse. Your whole request (brief, bids, warnings, approval, payment) runs in an ASI:One chat. | Core |
| Fetch.ai | Payment Protocol, Interactive Cards | The seller sends `RequestPayment`; the buyer sends `CommitPayment` with a signed mandate, only after the approval gate. Bids, warnings and approvals appear as cards, with a plain-text fallback (numbered bids, reply `APPROVE <id>`). | Core |
| Visa | Trusted Agent Protocol | Every agent request to a seller is signed with HTTP Message Signatures and verified at the seller and in Shield. The UI shows "signature verified". | Core |
| Visa | Visa test card over Stripe test mode or Link | The payment is a Stripe test-mode charge on a Visa test card, made through the Payment Protocol. | Core |
| Visa | Intelligent Commerce (tokenized agent credentials) | An adapter behind the same payment interface. It replaces the Stripe path only if Visa grants sandbox access. | Adapter |
| Cartesia | Line voice agent | Above your allowance, a voice agent calls you, reads the deal and records your yes or no before payment. In-browser call first; phone call via an imported Twilio number or SIP trunk is to be verified. Personas can also speak their bids on the floor. | Core |
| Apify | MCP server, Store actors, our own Actor | Mirrors listings from Newegg, PCPartPicker, Micro Center, Best Buy, B&H, eBay (sold and live) and Amazon (actor slugs in the research file). We also build and publish a claim-check Actor: claim and URL in, verified, unverified or false plus evidence out. | Core |
| Bright Data | MCP server, SERP API, Web Unlocker | Price and claim checks across the wider web. | Core |
| CRS | Credit API sandbox, MCP server | Identity and fraud check on business sellers; a failed check greys out the seller's bid with the reason. Test identities only, band output. | Adapter |
| Armadin | Bazaar Shield API (our build) | Shield is our agent-to-agent security API with a versioned schema, signed verdict receipts and a `shield-bench` for any swarm. In the demo it blocks an injected listing live, and a judge can attack it in the "Hack the market" console. | Core |
| Spacetime | SpacetimeDB | Holds the live auction state that every screen and the 3D floor read, and enforces the floor price and approval-before-payment rules in reducers. | Core |
| Anthropic | Claude | Reasoning and wording for the quality advocate and ownership-memory advice, and the line each seller persona speaks. | Core |
| Tiger Data (MLH) | Time-series Postgres | Time series behind dated savings and the learning curve. Starts after Sat 14:00. | Adapter |
| Hyphenate | IT buyer purchasing | PO number, requester cannot approve, three-way match, credit memo and audit page. | Adapter |

Also under consideration, each marked optional: Snowflake, Gemini, a GoDaddy Registry domain, and the MLH Commit Fellowship opt-in ([docs/SPONSORS.md](docs/SPONSORS.md)).

Public data, not a sponsor: **CPSC recalls API** (no key), **docyx/pc-part-dataset** (MIT) for compatibility fields, and eBay sold listings for a used-price baseline.

## Real vs simulated

Every bid, claim and screen carries a badge (**LIVE**, **MIRROR**, **SIM**, **SANDBOX** or **RECORDED**) driven by the `source` field in the contracts. The working copy of this table is [docs/REAL_VS_SIMULATED.md](docs/REAL_VS_SIMULATED.md).

| Component | Label | What that means |
|---|---|---|
| Builder's owned parts | SIM until a real builder shares them | A seeded rig for the demo builder |
| Seller catalogs and prices | MIRROR | Real public listings, mirrored by Apify with a date |
| Seller bids | SIM over MIRROR | Big-box stores will not change their price for one order. Our demo sellers are agents for marketplace or used sellers, built from real scraped listings. Real prices are sources, not bidders. Any real seller that joins bids LIVE. |
| Fit checks | LIVE code | Rules over a dated open dataset plus two small tables we wrote; unknown means "uncertain" |
| Claim checks | LIVE or MIRROR | LIVE against seller pages we host for the demo; MIRROR for real stores |
| The caught liar | LIVE, planted | A planted attack on a page we host, with a lie toggle and an answer key. We never call a real store a liar; real pages get neutral wording ("differs from the listing at time T", "the price claim did not match the price history"). |
| Price history and baseline | MIRROR or SIM | Dated sources where they work; a labelled seeded series where they do not |
| CPSC recalls | LIVE | Real API call; a labelled fixture if no real record fits a demo part |
| CRS seller stability | SANDBOX | Real sandbox calls on CRS-provided test identities |
| Allowance and voice approval | LIVE code, call path to verify | Auto-approval is code. The Cartesia call starts in the browser; the phone path is labelled when it works |
| Payments | SANDBOX | Stripe test mode, Visa test card, no real money |
| Visa Trusted Agent Protocol signatures | LIVE | Real signing and verification on every request |
| Visa Intelligent Commerce | Adapter | Swaps in only with Visa sandbox access |
| Shield verdicts | LIVE | Real screening on every message |
| Seller demand and trends | SIM plus MIRROR | Simulated requests from the wind tunnel plus public best-seller ranks |
| Wind tunnel builders | SIM | Simulated by design |
| 3D floor | LIVE state | Characters are drawn from market rows; click one to see its row |

## Fetch.ai agents

> **Team: fill this table as each agent registers on Agentverse.** A row marked *pending* is not registered yet.

| Agent name | Role | Agentverse address |
|---|---|---|
| *pending* | Buyer agent: remembers your parts, runs the auction, pays within your allowance | *pending* |
| *pending* | Quality advocate: challenges each bid with cited warnings | *pending* |
| *pending* | Shield: screens messages, verifies signatures, checks claims | *pending* |
| *pending* | Seller gateway: routes requests to the seller fleet | *pending* |
| *pending* | Seller agent, named persona 1 | *pending* |
| *pending* | Seller agent, named persona 2 | *pending* |

The rest of the seller fleet runs behind the gateway and is labelled as a fleet in the UI.

## Repo layout

Each lane owns its folders and talks to the others only through `contracts/`.

```
contracts/  shared JSON schemas: Need, SpecCard, Bid, Claim, ShieldVerdict, SupplierSignal,
            AdvocateCard, OrderPlan, Order, ReceivingEvent, QualityRecord, LedgerEntry,
            Persona, FloorEvent (OwnedPart, Allowance, VoiceApproval, DemandRecord,
            TrendSignal are proposed in docs/CHANGES.md)
agents/     Lane A: Python uAgents (buyer, advocate, seller agents), ownership memory, ASI:One chat, Payment Protocol
market/     Lane B: SpacetimeDB module (auction state) and market/rules (sealing, scoring, optimizer, outcomes)
web/        Lane B: Next.js builder view, voice approval screen, seller dashboard, 3D floor (three.js)
data/       Lane C: Apify and Bright Data adapters, seller mirrors, price history, fit checker, demand trends, claim checks
shield/     Lane D: FastAPI Bazaar Shield API (/screen, /verify-agent, /check-claim)
pay/        Lane D: approval gate, Stripe and Visa adapters, Trusted Agent Protocol signing, CRS adapter
sim/        Lane D: wind tunnel (simulated builders, hostile agents)
docs/       architecture, sponsor map, real vs simulated, interviews, kickoff prompts, team board
```

## Quickstart

> Run commands are added as each lane's code lands. Until then, this section lists what you need.

1. **Clone and configure.** `git clone https://github.com/vs-githjk/cal-hacks-2026.git && cd cal-hacks-2026`, then:
   ```bash
   cp .env.example .env   # fill in your own sandbox keys; .env is gitignored
   ```
2. **Set these environment variables** (names from [.env.example](.env.example); two are new with the pivot and need adding there: the Cartesia call setup and the telephony credentials):

   | Variable | Used for |
   |---|---|
   | `ANTHROPIC_API_KEY` | Quality advocate, memory advice and persona lines |
   | `AGENTVERSE_API_KEY`, `ASI1_API_KEY` | Agent registration and ASI:One |
   | `APIFY_TOKEN` | Seller mirrors and the claim-check Actor (paid actors, run only with approval) |
   | `BRIGHT_DATA_API_KEY` | Wider web price and claim checks |
   | `CRS_API_KEY` | Seller stability check (sandbox) |
   | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` | Test-mode payments |
   | `VISA_TAP_PRIVATE_KEY_PATH` | Trusted Agent Protocol request signing |
   | `VISA_VIC_API_KEY` | Intelligent Commerce adapter, only with sandbox access |
   | `SPACETIMEDB_URI` | Live market state |
   | `CARTESIA_API_KEY` | Voice approval call and persona voices |
   | Telephony (Twilio number or SIP trunk) | Phone path for the approval call, to be verified; test numbers only |

3. **Run each lane:** agents, market, web, Shield. Commands are added here as each lane merges.

## Invariants (safety by design)

These are enforced in code and covered by tests, not left to prompts.

1. **No payment without a limit check and an approval.** The agent buys on its own only inside the allowance you set, and sends a receipt. Above it, a recorded voice yes (or the approval card) is required. No answer means no payment.
2. **Every seller claim shown to a builder has a check result:** verified, unverified or false, with evidence.
3. **No agent acts on another agent's text before Shield screens it.** Screening fails closed for payments.
4. **The 3D floor and every screen render real market state only.**
5. **No seller agent bids below its floor**, enforced in the market reducers, so even a compromised agent cannot.
6. **Sealed bids.** Sellers see the parts, conditions and delivery window, never your budget, allowance or each other's bids.
7. **Private financial data stays private.** CRS checks run inside our system; both sides see only the stability signal.
8. **Scoped payments.** Each mandate has an amount cap, one seller, an expiry, single use and an idempotency key.
9. **Sandbox only.** Test identities and test cards, no real money, no secrets in the repo.
10. **Anything simulated is labelled** in the UI and in this README.
11. **Sellers never see an individual builder.** Demand and trend views are aggregates with a minimum group size of 5 (proposed).
12. **The agent never re-buys a part you own** unless you ask, and its advice cites the memory entry.

## Numbers we will report

Nothing is measured yet. These are the methods; results go here with the date and dataset once measured, including results that show no effect. We do not report research time, incompatibility rate or return rate: no source was found.

| Number | Method |
|---|---|
| Price spread across sellers and vs baseline | Winning bid against a dated baseline on real parts. Real price spread and simulated bid discount are reported separately, never blended. |
| Fit-checker accuracy | Against a hand-checked set of part combinations, including known mismatches |
| Advocate precision and recall | Against a hand-labelled answer key of 30 to 50 cases with planted issues (fit, condition, false "was" price, recall) and clean controls |
| Shield catch rate, false-positive rate, latency | On a frozen held-out attack set plus unseen wind-tunnel attacks. Design targets: rule checks under 50 ms, 1.5 s timeout. |
| Wind tunnel lift | Seller policy tuned on a training set; before and after on held-out simulated builders, against a cheapest-wins baseline |

## Team and lanes

Hour-by-hour plan: [docs/HOUR_PLAN.md](docs/HOUR_PLAN.md). Next gate: Sat 10:00, a demo we can show sponsors.

| Lane | Owns | Member |
|---|---|---|
| A: Agents | Buyer, advocate and seller agents; ownership memory; goal hunt loop; ASI:One; Payment Protocol; CRS gate; open seller protocol; Shield `/verify-agent` | Abhinav |
| B: Market and screens | Spacetime market (rounds, goals, lots, allowance), buyer and seller screens, seller console, the Lot Wall, 3D floor, Hyphenate pages | Vedant |
| C: Data, truth, then integration | Apify mirrors and claim-check Actor, fit checker, wind tunnel, merchant simulator, Shield OpenAPI, keys and bench, scoreboard; integration owner from Sun 03:00 | Anoop |
| D: Trust and pitch | Mandate and Visa TAP, the hardened call, Shield core, interviews and real quotes, the real purchase, pitch and video | Vidyut |

## Status

Updated with every merge. States: **planned**, **in progress**, **built** (with a link to the PR or test).

| Piece | State |
|---|---|
| Contracts (JSON schemas) | in progress: first version in `contracts/`, PC renames proposed |
| Market rules (sealing, scoring, split optimizer, outcomes) | in progress on branch `lane-b-market-floor`, tested; renames to PC terms pending |
| Buyer agent on Agentverse, reachable in ASI:One | planned |
| Ownership memory | planned |
| Seller agents bidding from Apify mirrors | planned |
| Fit checker | planned |
| Quality advocate with cited warnings | planned |
| Shield `/screen`, `/verify-agent`, `/check-claim` | planned |
| Trusted Agent Protocol signing and verification | planned |
| Allowance and Cartesia voice approval | planned |
| Stripe test-mode payment through the Payment Protocol | planned |
| CRS seller stability signal | planned |
| Seller demand and trend dashboard | planned |
| Wind tunnel | planned |
| 3D floor | planned |
| Visa Intelligent Commerce adapter | planned, needs sandbox access |

## Roadmap

**During the hackathon**
- **Sat Oct 24, 10:00 PDT, talkable progress:** the five beats run end to end on MIRROR plus SIM data, labelled.
- **Sat Oct 24, 14:00 PDT, demo path green** on the deployed build. After this: the Lot Wall, the wind tunnel at 50 builders, Tiger Data, persona voices.
- **Real people:** interviews tonight, one real seller quote, one IT buyer quote, one real teammate purchase with a receiving check, and an outside agent bidding live.
- **Sun Oct 25, 03:00 PDT:** feature freeze, then integration and the Devpost write-up. Deadline 09:00.

**After the hackathon**
- Small IT buyers (10 to 50 PCs), where sealed bids on volume are believable.
- Seller onboarding: paste a catalog URL, set a floor and perks, go live.
- Visa Intelligent Commerce tokens in place of the Stripe path.
- Tech Bazaar as an MCP server, so any agent can request bids.

## License

MIT. See [LICENSE](LICENSE).
