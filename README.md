# Tech Bazaar

**A buyer's agent for scarce, scam-prone goods, starting with computer gear. You give it a goal, seller agents bid for it, an advocate vetoes the traps with a source, and nothing is paid until you approve on a two-way voice call.**

A refereed arena for agent commerce. Seller agents adjust after a loss (a SIM stand-in today), and Bazaar Shield, our security API, is scored in the open: blocked X of Y on a named corpus, never "secure" ([Numbers](#numbers-we-report)).

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Built at Cal Hacks 13.0 (October 23 to 25, 2026) by a team of four.

> **Status, Sat Oct 24, about 03:00 PDT.** This README says what is built and labels the rest. A piece counts as working only when the [Status](#status) table says "built" and names its code. The demo video and live link go here once they exist.

Store prices are real dated mirrors; the bidding agents are ours (SIM) until a shop runs the Seller Kit.

**The demo order:** an RTX 5070 Ti that fits a 305 mm case, under $1,300. The winner is the ASUS Prime RTX 5070 Ti OC Edition (304 mm, maker spec) at Best Buy, $1,299.99 before sales tax, shipping: not captured (a MIRROR listing, bid by a SIM seller; proof: [demo/tests/test_demo_winner.py](demo/tests/test_demo_winner.py)). Cards that do not fit, or whose fit we cannot confirm, are vetoed or lose, with a source.

**The five beats of the demo:** (1) set a goal; (2) sellers bid and the advocate vetoes a trap with a source; (3) Shield blocks an injected listing live; (4) the two-way call approves above the allowance; (5) the seller's loss report and learning. Everything on screen is labelled LIVE, MIRROR or SIM.

**Jump to:** [Problem](#the-problem) · [What it does](#what-tech-bazaar-does) · [How it works](#how-it-works) · [Architecture](docs/ARCHITECTURE.md) · [Sponsors](#sponsor-technology) · [Real vs simulated](#real-vs-simulated) · [Cartesia](#cartesia-the-approval-call) · [Agents](#fetchai-agents) · [Quickstart](#quickstart) · [Safety](#invariants-safety-by-design) · [Status](#status)

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

**The multiverse (planned, not built).** The demo is one universe of one order. The real market has many buyers whose requests pool by exact SKU, and sellers bid a price ladder by quantity on the pooled lot. The **Lot Wall** (planned, not built on this branch; it would be built from real lot rows) would show it: Vidyut's brick is gold and labelled REAL, the rest are grey and labelled SIM, and the sealed bids slide down the price tiers. One or two bids are real, the rest are labelled simulated. We do not claim many people use it.

**Agents:** three seller agents, an advocate, a buyer and a Shield client are registered on Agentverse (see [agents/README.md](agents/README.md); their listings are SIM). The demo runner's sellers are code over real dated listings, not uAgents. A real non-agent seller side (a shop with no agent) is planned, not built.

**Scope:** all computer gear (PCs, parts, laptops, monitors, peripherals). The first payer we design for is the small IT buyer (10 to 50 machines, with approvals and purchase orders), priced per refresh (proposed, finalized later). Add-ons, not extra beats: Hyphenate IT buyer purchasing (PO, three-way match, audit) is built ([hyphenate/](hyphenate/)). Bright Data prices are in progress (a real integration that is live only when its key is set; [data/baselines/brightdata.py](data/baselines/brightdata.py) is a stub that says not configured today). CRS identity checks on business sellers, Tiger Data time series and the IT fleet view are planned, not built.

**Shield as an API.** `POST /v1/shield/screen`, `/v1/shield/verify-agent`, `/v1/shield/verify-mandate` ([shield/api.py](shield/api.py)) and `/v1/check-claim` ([shield/product.py](shield/product.py)), with a versioned schema, and `shield-bench` ([shield/bench.py](shield/bench.py)) scoring any attack file. Signed verdict receipts and the adaptive attack set are planned, not built. A "Hack the market" console where a judge writes a hostile listing is planned, not built; today a judge can send attacks to the API or the bench.

## How it works

1. **Goal.** On the Agentverse path you state a goal in ASI:One ([agents/buyer/](agents/buyer/)). The agent turns it into a Goal (budget cap, part price by date, or build price by date) and a sealed request, after skipping parts you already own. The stage runner uses a scripted SIM goal ([demo/goal.py](demo/goal.py)).
2. **Bid.** Seller agents bid until the deadline from their owner's real listings (MIRROR) or as simulated builders' counterparts (SIM). An outside Agentverse agent that speaks the open seller protocol would bid LIVE (planned, not built: no outside agent has bid). Bids stay sealed, sellers never see your budget, and a reducer rejects any bid below a seller's floor. Every bid carries an origin badge and a listing link.
3. **Screen.** Shield screens every seller message, listing title and claim before the advocate sees it: injection patterns, payee changes, identity mismatch. A blocked message is quarantined on screen with the rule that fired. A CRS identity and fraud check on business sellers is planned, not built.
4. **Veto.** The advocate ([agents/advocate/checks.py](agents/advocate/checks.py)) is code, not a model: it checks fit by the fit checker (socket, length, PSU wattage), condition and price claims against the page with our claim-check Actor, and a recall list and seller records that are SIM fixtures today. It can veto the cheapest bid with the source. It never sees the fee.
5. **Notify.** After each step you get one event per class (deal found, bid in, veto, progress), throttled to one per class per 10 minutes. Quotes expire after 10 minutes.
6. **Call.** Above your allowance the agent calls you (a Cartesia managed agent places a phone call, [pay/voice_cartesia.py](pay/voice_cartesia.py); a typed fallback is labelled). It reads amount and payee from a template filled by code, answers "why not the cheaper one?" from the advocate's cited reason, and asks for the code. The mandate binds deal id, amount, payee, expiry and nonce, and a typed fallback is labelled.
7. **Pay.** The request is signed in the style of Visa's Trusted Agent Protocol ([pay/tap.py](pay/tap.py)) and our own merchant simulator verifies the signature, not Visa. The charge is a SIM stub unless the runner is started with `--stripe`, which makes one Stripe test-mode PaymentIntent on a Visa test card ([demo/approval_flow.py](demo/approval_flow.py)). A replayed or altered mandate fails. No payment exists without an approval for the same mandate hash.
8. **Receive.** Planned, not built for the buyer path: photos of the delivery checked against the spec. The IT buyer path has a receiving step and a credit memo ([hyphenate/procurement.py](hyphenate/procurement.py)).
9. **Learn.** Each losing seller gets a loss report. The demo's learner adjusts a price step ([demo/learning.py](demo/learning.py), a SIM stand-in; Claude writing the "what to change" line is planned, not built). The wind tunnel ([sim/wind_tunnel.py](sim/wind_tunnel.py)) runs simulated builders against control sellers; its result is labelled SIM and reported with seeds, and it shows no headline lift yet (see Numbers).

Diagram, components and data flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Why this is different

- **The buyer has a skeptic on its side.** A price list tells you what is cheapest. The advocate tells you when the cheapest bid will not fit, is not new, or carries a price claim that did not match the price history, and it cites a source for every warning.
- **It remembers your rig.** Existing scanners cover one brand's memory or storage (Crucial, Corsair and Kingston scanners, per our research). We found no checked tool that remembers your whole rig across sellers and advises from it (not proof that none exists).
- **Voice is the trust step, and voice is never the credential.** Spending above your allowance needs a one-time word-pair code from your screen, spoken on a call about one exact mandate. A recording of your voice cannot approve it.
- **Known agent-market failures are designed out.** Microsoft's Magentic Marketplace study (arXiv 2510.25779) found that buyer agents favor the first proposal they see and that malicious sellers can redirect payments. Sealed bids remove the first-mover advantage. Shield's mandate check ([shield/verify.py](shield/verify.py)) blocks any payment whose payee or amount differs from what you approved.
- **Identity says who; Shield says whether it is true.** Visa's Trusted Agent Protocol proves which agent sent a request. Shield checks whether what that agent claims holds up.
- **Privacy by design.** Sellers see aggregate pool data (SKU, quantity, ceiling band, deadline), never an individual buyer. CRS checks on business sellers would share only a band (planned, not built).

## Sponsor technology

| Sponsor | Product | What it does in Tech Bazaar | Depth |
|---|---|---|---|
| Fetch.ai | uAgents, Agentverse, ASI:One, Agent Chat Protocol | Every agent is a uAgent registered on Agentverse. Your whole request (brief, bids, warnings, approval, payment) runs in an ASI:One chat. | Core |
| Fetch.ai | Payment Protocol, Interactive Cards | The seller sends `RequestPayment`; the buyer sends `CommitPayment` with a signed mandate, only after the approval gate. Bids, warnings and approvals appear as cards, with a plain-text fallback (numbered bids, reply `APPROVE <id>`). | Core |
| Visa | Trusted Agent Protocol | Requests to a seller are signed in the style of HTTP Message Signatures (RFC 9421) and verified by our merchant simulator and by Shield. Visa does not verify them. | Built: [pay/tap.py](pay/tap.py), [pay/merchant_sim.py](pay/merchant_sim.py) |
| Visa | Visa test card over Stripe test mode | One Stripe test-mode PaymentIntent on a Visa test card, only with `--stripe`; the default charge is a SIM stub. | Built: [demo/approval_flow.py](demo/approval_flow.py) |
| Visa | Intelligent Commerce (tokenized agent credentials) | An adapter behind the same payment interface. It replaces the Stripe path only if Visa grants sandbox access. | Planned, not built |
| Cartesia | Line voice agent | Above your allowance, a Cartesia managed agent phones you, reads the deal and asks for the code on your screen; our code, not the agent, decides. See the [Cartesia section](#cartesia-the-approval-call). | Built: [pay/voice_cartesia.py](pay/voice_cartesia.py), [pay/approval.py](pay/approval.py) |
| Apify | Store actors, our own Actor | Mirrors listings from Amazon, Best Buy, B&H, Micro Center and eBay into dated snapshots. Our claim-check Actor ([Apify Store](https://apify.com/anoopibrampur/tech-bazaar-claim-check)): claim and URL in, verified, unverified or false plus evidence out. | Built: [data/mirror/](data/mirror/), [data/claim_check/](data/claim_check/) |
| Bright Data | Scraper API (price source) | A second, dated price source. In progress: a real integration that is live only when `BRIGHT_DATA_API_KEY` is set; today [data/baselines/brightdata.py](data/baselines/brightdata.py) raises not configured, and nothing in the demo uses it. | In progress |
| CRS | Credit API sandbox | Identity and fraud check on business sellers; a failed check would grey out the bid with the reason. Planned, not built: there is no CRS code on this branch. | Planned |
| Armadin | Bazaar Shield API (our build) | Screens every message, listing and claim before the advocate sees it; blocks an injected listing live in beat 3. Scored per set in [Numbers](#numbers-we-report). The "Hack the market" console is planned, not built. | Built: [shield/](shield/) |
| Spacetime | SpacetimeDB | Holds the live auction state that the buyer and market screens read, and enforces the floor price and approval-before-payment rules in reducers. The 3D floor is planned, not built. | Built: [market/spacetimedb/](market/spacetimedb/) |
| Anthropic | Claude | Optional: the one-line persona voice of a seller agent ([agents/sellers/seller_agent.py](agents/sellers/seller_agent.py), falls back to a template without a key) and Shield's ambiguous-case classifier ([shield/classifier.py](shield/classifier.py), off by default). The advocate is code, not a model. | Built, optional |
| Tiger Data (MLH) | Time-series Postgres | Time series behind dated savings and the learning curve. Planned, not built: there is no Tiger code on this branch. | Planned |
| Hyphenate | IT buyer purchasing | PO number, requester cannot approve, three-way match, credit memo and audit trail, scored on a blind planted-error set ([hyphenate/RESULTS-blind.md](hyphenate/RESULTS-blind.md)). | Built: [hyphenate/](hyphenate/) |

Also under consideration, each marked optional: Snowflake, Gemini, a GoDaddy Registry domain, and the MLH Commit Fellowship opt-in ([docs/SPONSORS.md](docs/SPONSORS.md)).

Public data, not a sponsor: **CPSC recalls API** (no key), **docyx/pc-part-dataset** (MIT) for compatibility fields, and eBay sold listings for a used-price baseline.

## Real vs simulated

Every bid, claim and screen carries a badge (**LIVE**, **MIRROR**, **SIM**, **SANDBOX** or **RECORDED**) driven by the `source` field in the contracts. The working copy of this table is [docs/REAL_VS_SIMULATED.md](docs/REAL_VS_SIMULATED.md).

| Component | Label | What that means |
|---|---|---|
| Builder's owned parts | SIM until a real builder shares them | A scripted rig for the demo builder ([demo/goal.py](demo/goal.py)) |
| Seller catalogs and prices | MIRROR | Real public listings, mirrored by Apify with a date ([data/mirror/snapshots/](data/mirror/snapshots/)) |
| Seller bids | SIM over MIRROR | Big-box stores will not change their price for one order. Our demo sellers are code that bid from real dated listings, plus labelled SIM sellers. Real prices are sources, not bidders. No outside seller has bid, so nothing is LIVE. |
| Fit checks | LIVE code | Rules over a dated open dataset plus two small tables we wrote; unknown means "uncertain" and cannot win over a confirmed fit |
| Claim checks | LIVE or MIRROR | LIVE against seller pages we host for the demo; MIRROR for real stores |
| The caught liar | LIVE, planted | A planted attack on a page we host, with a lie toggle and an answer key. We never call a real store a liar; real pages get neutral wording. |
| Price history and baseline | MIRROR or SIM | Dated sources where they work; a labelled seeded series where they do not. Bright Data is not configured. |
| CPSC recalls | SIM fixture | One unrelated entry in [agents/advocate/mock_data.py](agents/advocate/mock_data.py); the live CPSC API is not called |
| CRS seller stability | planned, not built | No CRS code on this branch |
| Allowance and voice approval | LIVE code, call proven separately | The approval judge is code ([pay/approval.py](pay/approval.py)); the Cartesia call client is [pay/voice_cartesia.py](pay/voice_cartesia.py); the phone path is labelled when it works |
| Payments | SIM stub, SANDBOX with `--stripe` | One Stripe test-mode charge on a Visa test card; no real money |
| Request signatures | LIVE code, checked by our simulator | TAP-style signing; Visa does not verify them |
| Visa Intelligent Commerce | planned, not built | Swaps in only with Visa sandbox access |
| Shield verdicts | LIVE code | Real screening on every message; scored per set in Numbers |
| Seller demand and trends | planned, not built | No dashboard on this branch |
| Wind tunnel builders | SIM | Simulated by design |
| 3D floor | planned, not built | No three.js in web/package.json |

## Cartesia: the approval call

Voice is the trust step: above the allowance, a call asks for a one-time word-pair code that appears only on the buyer's screen.

**Features used.** A Cartesia managed agent that only talks; outbound calls (`POST /agents/calls`); dynamic variables (`buyer_name`, `deal_script`, `why_answer`); the call transcript (`GET /agents/calls/{id}`). Code: [pay/voice_cartesia.py](pay/voice_cartesia.py).

**What the voice does and does not decide.** The agent reads a script that code fills from the mandate (amount and payee), answers "why not the cheaper one?" from the advocate's closed-schema reason, asks for the code and repeats what it heard. It never decides. Our code reads the transcript and feeds every buyer utterance to the approval judge in [pay/approval.py](pay/approval.py): it approves only on the exact word pair plus the word "approve", and silence, a hang-up, voicemail, a failed dial, a timeout or a missing transcript all deny. The judge, not the call, is what the tests cover ([pay/tests/test_approval.py](pay/tests/test_approval.py), [pay/VOICE_ATTACKS.md](pay/VOICE_ATTACKS.md): 10 of 10 attack cases denied after one fix).

**Setup.** Env names (values never printed): `CARTESIA_API_KEY`, `CARTESIA_AGENT_ID`, `APPROVAL_CALL_TO` (the only number ever dialed). Then `python3 -m pay.voice_cartesia --dry-run --env-file /abs/path/.env` prints the variables with no network, `--check` is a read-only look at the agent, and `--demo` places one real call. Details: [pay/README.md](pay/README.md).

**Known limits.**
- A noisy room can make the speech-to-text miss the code. We have not measured a noise level; the answer to a miss is the typed fallback, which goes through the same judge and is labelled typed.
- 3 tries per mandate, shared by voice and typed, then the mandate is denied and needs a new one. A failed try starts a 30 second cooldown.
- A spoken different amount ("approve nine hundred dollars") is caught; not every phrasing is ("approve nine fifty" still passes). The real money control is the signed mandate hash, which a call cannot change.
- Cartesia does not document how long after a call ends the transcript is complete, or a call-cancel endpoint, so a wait timeout denies and the call may still be ringing.
- The call is a phone call to one registered number. An in-browser Cartesia call is planned, not built; the typed card is the fallback today.

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
web/        Lane B: Next.js buyer and market screens (seller dashboard and 3D floor are planned, not built)
data/       Lane C: Apify mirrors (Bright Data is a stub), seller mirrors, price history, fit checker, claim checks (demand trends planned)
shield/     Lane D: FastAPI Bazaar Shield API (/screen, /verify-agent, /check-claim)
pay/        Lane D: approval gate, TAP-style signing, merchant simulator, Cartesia call client (Stripe test charge in demo/)
sim/        Lane D: wind tunnel (simulated builders, hostile agents)
docs/       architecture, sponsor map, real vs simulated, interviews, kickoff prompts, team board
```

## Run it

One command brings the whole product up locally and tells the truth about what is up (Python 3.12, stdlib only):

```bash
python3 scripts/launch.py up       # preflight, then start every service that can start
python3 scripts/launch.py status   # table of service, port, pid, health; exit 1 if a service is down
python3 scripts/launch.py down     # stop only the processes it started
```

`up` prints one OK or MISSING line per prerequisite with the fix command, then starts SpacetimeDB (publishes `tech-bazaar` and runs `seed_demo`), Shield (8787), the seller, advocate and buyer agents (8010, 8003, 8001) and the web app (3100). Logs are in `.run/logs/<service>.log`, pids in `.run/pids.json` (both gitignored). A service whose prerequisite is missing is shown as SKIPPED with the exact install command, never as up. Keys come from `--env-file` (default `~/hackathons/cal-hacks-13-2026/lane-d/.env`) into child environments only; only key names are printed. Nothing global is installed: the only installs are a project-local `uv` venv in `agents/.venv` and `npm ci` in `web/` and `market/`. Port flags: `--shield-port`, `--web-port`, `--stdb-port` (the agent ports are fixed in `agents/` code). Tests: `python3 -m pytest scripts/tests -q`.

## Quickstart

> Run commands are added as each lane's code lands. Until then, this section lists what you need.

1. **Clone and configure.** `git clone https://github.com/vs-githjk/cal-hacks-2026.git && cd cal-hacks-2026`, then:
   ```bash
   cp .env.example .env   # fill in your own sandbox keys; .env is gitignored
   ```
2. **Set these environment variables** (names from [.env.example](.env.example); two are new with the pivot and need adding there: the Cartesia call setup and the telephony credentials):

   | Variable | Used for |
   |---|---|
   | `ANTHROPIC_API_KEY` | Optional: seller persona lines and the Shield classifier |
   | `AGENTVERSE_API_KEY`, `ASI1_API_KEY` | Agent registration and ASI:One |
   | `APIFY_TOKEN` | Seller mirrors and the claim-check Actor (paid actors, run only with approval) |
   | `BRIGHT_DATA_API_KEY` | Second price source (in progress, not used by the demo yet) |
   | `CRS_API_KEY` | Seller stability check (planned, not built) |
   | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` | Test-mode payments |
   | `VISA_TAP_PRIVATE_KEY_PATH` | Trusted Agent Protocol request signing |
   | `VISA_VIC_API_KEY` | Intelligent Commerce adapter, only with sandbox access |
   | `SPACETIMEDB_URI` | Live market state |
   | `CARTESIA_API_KEY` | Voice approval call |
   | `APPROVAL_CALL_TO`, `CARTESIA_AGENT_ID` | The approval call: the only number dialed, and the managed agent |

3. **Run each lane:** agents, market, web, Shield. Commands are added here as each lane merges.

## Invariants (safety by design)

These are enforced in code and covered by tests, not left to prompts.

1. **No payment without a limit check and an approval.** The agent buys on its own only inside the allowance you set, and sends a receipt. Above it, a recorded voice yes (or the approval card) is required. No answer means no payment.
2. **Every seller claim shown to a builder has a check result:** verified, unverified or false, with evidence.
3. **No agent acts on another agent's text before Shield screens it.** Screening fails closed for payments.
4. **Every screen renders market state or a labelled sample, never an unlabelled one.** (The 3D floor is planned, not built.)
5. **No seller agent bids below its floor**, enforced in the market reducers, so even a compromised agent cannot.
6. **Sealed bids.** Sellers see the parts, conditions and delivery window, never your budget, allowance or each other's bids.
7. **Private financial data stays private.** Planned with CRS (not built): checks run inside our system and both sides see only the stability signal.
8. **Scoped payments.** Each mandate has an amount cap, one seller, an expiry, single use and an idempotency key.
9. **Sandbox only.** Test identities and test cards, no real money, no secrets in the repo.
10. **Anything simulated is labelled** in the UI and in this README.
11. **Sellers never see an individual builder.** Demand and trend views are aggregates with a minimum group size of 5 (proposed).
12. **The agent never re-buys a part you own** unless you ask, and its advice cites the memory entry.

## Numbers we report

Every number here is copied from a results file named in its row, with the date the file gives. Sets the rules were written against are marked in-sample. We do not report research time, incompatibility rate or return rate: no source was found. Results that show no effect are reported too.

| Number | Set and honest reading | Result | Source | Date |
|---|---|---|---|---|
| Shield, attacks stopped | dev and dev2, in-sample (rules were written looking at them) | 30 of 30 and 30 of 30 | `shield/corpus/RESULTS.md` | 2026-10-23 |
| Shield, attacks stopped | frozen probe, an upper bound (the author had read it) | 6 of 10 (60.0%) | `shield/corpus/RESULTS.md` | 2026-10-23 |
| Shield, attacks stopped | post-freeze check, run once, not tuned: our best guess of real recall | 6 of 12 (50.0%) | `shield/corpus/RESULTS.md` | 2026-10-23 |
| Shield, clean controls wrongly stopped | dev and dev2 controls | 0 of 10 and 0 of 15 | `shield/corpus/RESULTS.md` | 2026-10-23 |
| Shield, held-out set in the wind tunnel run | 20 attacks, 12 stopped (60%); 2 false blocks on clean rows | 60% | `sim/RESULTS-2026-10-24-b48x3.md` | 2026-10-24 |
| Fit checker, decided builds correct | full frozen set of 44 builds, specs partly unconfirmed, tuned on once: not held out | 42 of 43 | `data/RESULTS.md` | 2026-10-23 |
| Fit checker, decided builds correct | the 12 builds whose specs we confirmed on maker pages | 12 of 12 | `data/RESULTS.md` | 2026-10-23 |
| Hyphenate, planted errors caught | blind run before any fix; 5 of 7 clean cases passed, 2 false flags | 26 of 27 | `hyphenate/RESULTS-blind.md` | 2026-10-24 |
| Wind tunnel lift | SIM. The learner beats the field-median control on 1 of 4 held-out archetypes and the gate needs 2: no headline lift | 1 of 4 | `sim/RESULTS-2026-10-24-b48x3.md` | 2026-10-24 |
| Real store asks for an RTX 5070 Ti | MIRROR, 11 in stock or stock unknown, lowest $1,199.99, median $1,299.99, highest $1,489.00; median is +48% over the eBay sold median | $1,299.99 | `data/RESULTS.md` | 2026-10-24 |

After the Hyphenate fixes the same file reports 27/27 planted and 7/7 clean, but three of those cases are no longer blind; quote the first-run line. Advocate precision and recall, Shield latency on the keyed API and the Seller Kit are not measured yet.

## Team and lanes

Hour-by-hour plan: [docs/HOUR_PLAN.md](docs/HOUR_PLAN.md). Next gate: Sat 10:00, a demo we can show sponsors.

| Lane | Owns | Member |
|---|---|---|
| A: Agents | Buyer, advocate and seller agents; ownership memory; goal hunt loop; ASI:One; Payment Protocol; open seller protocol; the CRS gate (planned, not built); Shield `/verify-agent` | Abhinav |
| B: Market and screens | Spacetime market (rounds, goals, lots, allowance), buyer and seller screens, seller console, Hyphenate pages; the Lot Wall and 3D floor are planned, not built | Vedant |
| C: Data, truth, then integration | Apify mirrors and claim-check Actor, fit checker, wind tunnel, merchant simulator, Shield OpenAPI, keys and bench, scoreboard; integration owner from Sun 03:00 | Anoop |
| D: Trust and pitch | Mandate and Visa TAP, the hardened call, Shield core, interviews and real quotes, the real purchase, pitch and video | Vidyut |

## Status

Updated with every merge. States: **planned**, **in progress**, **built** (the Code column names the files; the test `scripts/tests/test_readme_honesty.py` checks that a built row's files exist and a planned row's do not).

| Piece | State | Code |
|---|---|---|
| Contracts (JSON schemas) | built, v1 | `contracts/` |
| Market rules (sealing, scoring, split optimizer, outcomes) and the SpacetimeDB module | built | `market/rules`, `market/spacetimedb` |
| Buyer, advocate, seller and Shield-client agents on Agentverse | built: registered with a mailbox; replies seen in ASI:One; checkout not exercised ([evidence](agents/ISSUE14_EVIDENCE.md)) | `agents/buyer`, `agents/advocate`, `agents/sellers` |
| Ownership memory | built for the demo goal (a scripted SIM rig) | `demo/goal.py` |
| Seller bids from Apify mirrors | built in the demo runner (MIRROR listings, SIM bidders); the Agentverse sellers use SIM listings | `demo/sellers.py`, `data/mirror` |
| Fit checker | built | `data/fit_checker` |
| Quality advocate with cited warnings | built as code, not a model; recalls and seller records are SIM fixtures | `agents/advocate/checks.py` |
| Claim-check Actor | built | `data/claim_check` |
| Shield screen, verify-agent, verify-mandate, check-claim | built | `shield/api.py`, `shield/product.py` |
| Shield signed verdict receipts and adaptive attack set | planned | none yet |
| TAP-style signing and our merchant simulator | built | `pay/tap.py`, `pay/merchant_sim.py` |
| Allowance and the approval judge | built | `pay/approval.py` |
| Cartesia approval call client | built; a rehearsed live call is not recorded in this repo | `pay/voice_cartesia.py` |
| Stripe test-mode charge | built in the runner (SIM stub by default, one real test charge with `--stripe`); through the Payment Protocol: not exercised | `demo/approval_flow.py` |
| Hyphenate IT buyer purchasing | built | `hyphenate/` |
| Wind tunnel | built, SIM, no headline lift yet | `sim/wind_tunnel.py` |
| Bright Data price source | in progress: a stub that says not configured; live only when the key is set | `data/baselines/brightdata.py` |
| CRS seller stability check | planned | none yet |
| Tiger Data time series | planned | none yet |
| Seller demand and trend dashboard | planned | none yet |
| "Hack the market" console | planned | none yet |
| 3D floor | planned | none yet |
| Lot Wall (many orders pooled) | planned | none yet |
| Visa Intelligent Commerce adapter | planned, needs sandbox access | none yet |

## Roadmap

**During the hackathon**
- **Sat Oct 24, 10:00 PDT, talkable progress:** the five beats run end to end on MIRROR plus SIM data, labelled.
- **Sat Oct 24, 14:00 PDT, demo path green** on the deployed build. After this (all planned, not built): the Lot Wall, Tiger Data, Bright Data live prices, persona voices.
- **Real people:** interviews tonight, one real seller quote, one IT buyer quote, one real teammate purchase with a receiving check, and an outside agent bidding live.
- **Sun Oct 25, 03:00 PDT:** feature freeze, then integration and the Devpost write-up. Deadline 09:00.

**After the hackathon**
- Small IT buyers (10 to 50 PCs), where sealed bids on volume are believable.
- Seller onboarding: paste a catalog URL, set a floor and perks, go live.
- Visa Intelligent Commerce tokens in place of the Stripe path.
- Tech Bazaar as an MCP server, so any agent can request bids.

## License

MIT. See [LICENSE](LICENSE).
