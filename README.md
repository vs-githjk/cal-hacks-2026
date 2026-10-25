<div align="center">

# Tech Bazaar

### A buyer's agent that is hard to fool and can't pay without you.

Tell it the computer part you need. It reads real store listings, vetoes the traps with a source, blocks listings that try to hijack it, and phones you before it pays more than your allowance.

<p>
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg">
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-3776AB.svg">
  <img alt="TypeScript 5" src="https://img.shields.io/badge/typescript-5-3178C6.svg">
  <img alt="Tests passing" src="https://img.shields.io/badge/tests-passing-brightgreen.svg">
  <img alt="tag:innovationlab" src="https://img.shields.io/badge/innovationlab-3D8BD3">
  <img alt="tag:hackathon" src="https://img.shields.io/badge/hackathon-5F43F1">
</p>

[How it works](#how-it-works) · [For sellers](#for-sellers) · [Real vs simulated](#what-is-real-and-what-is-simulated) · [In progress](#in-progress) · [Results](#measured-results) · [Getting started](#getting-started) · [Architecture](docs/ARCHITECTURE.md)

</div>

## Status

**The headline flow is the full PC build, and it is in progress.** You describe the whole PC. The agent plans it, runs one sealed knockout round per part, re-plans when two parts clash, and makes one phone call to approve the whole build. Buying a single card, the reference scenario below, is one part of that flow, and it works today.

**Live now:** the web app at [tech-bazaar-app.vercel.app](https://tech-bazaar-app.vercel.app), backed by the market on SpacetimeDB Maincloud (database `tech-bazaar`). A round appears there when one is run.

## Overview

Tech Bazaar is a buyer's agent for computer gear. You give it a goal, not a one-shot order: this part, under this price, by this date. Three things stand between you and a bad buy:

1. **A quality advocate** checks every offer against the parts you already own and the seller's own page, and vetoes a trap with the source. It is deterministic code; no model decides the veto.
2. **Bazaar Shield**, our agent security API, screens every listing and message before the agent acts on it, and quarantines one that hides instructions or swaps the payee.
3. **Your allowance decides who approves.** Inside the allowance you set, a deal pays without a call. Above it, the phone call is the only approval: a voice agent calls you, reads the deal, and only the one-time code on your screen plus "approve" signs a mandate for that exact deal. Silence, a hang-up or a failed call means nothing is paid. Every spend, inside the allowance or above it, sends you a receipt.

**It works today without a single outside seller agent.** It reads real, dated store listings (labelled MIRROR) and turns each into a bid, so the protection above runs on real prices now. If no bid comes in, it names the best public listing and buys nothing.

**The reference scenario.** Vidyut needs an RTX 5070 Ti that fits his 305 mm case, under $1,300. Seventeen offers arrive in a sealed round: twelve from real store listings, five from simulated sellers. The cheapest, $757.44, claims "new" while its page says open box, so the advocate vetoes it with the link. Two more cheap offers are too long for the case, and the advocate vetoes each with a source. Best Buy's two cheaper cards (338 mm and 342 mm by the maker's spec) never become bids for the same reason. The winner is the ASUS Prime RTX 5070 Ti at 304 mm by the maker's spec, $1,299.99 at Best Buy before sales tax (shipping: not captured). That is over Vidyut's $250 allowance, so the agent calls him before it pays.

**The referee is deterministic.** The same offers always rank the same way. Outcomes change only because sellers and their stock change ([docs/ARENA_RULES.md](docs/ARENA_RULES.md)).

**Sellers are how it grows.** Seller agents compete for the buyer within their shop's own prices and policy and learn why they lost. Next, they show the shop which strategy won. See [For sellers](#for-sellers).

## The problem

**Who feels it:** people who upgrade or build a PC. We design first for the upgrader, who already owns a rig and needs one scarce part at a fair price from a seller they can trust. The growth path is small IT buyers (a school, an office, an esports cafe) buying 10 to 50 machines.

- **Prices are wild.** The lowest US listing for an RTX 5070 Ti was $1,119 against a $749 launch price, 49 percent over, on Sep 1, 2026.[^1]
- **Parts must fit each other.** Socket and motherboard, memory generation, power supply wattage and connectors, case and cooler clearance. A part that does not fit is a return and lost days.
- **Cheapest is not always safe.** Open-box parts sold as new, a "was" price that does not match the history, a third-party seller with no record.
- **Shopping agents are easy to fool.** Without defenses, prompt injection succeeded against an AI browser agent 23.6 percent of the time.[^2] In a simulated agent market, buyer agents gave fast sellers a 10x to 30x edge over better ones.[^3]
- **Sellers fly blind.** They cannot see what a buyer asked for, at what ceiling, or why they lost.

We found no sourced number for research time, compatibility mistakes or return rates in PC building, so we claim none.

## How it works

Five steps protect the buyer. A sixth, for sellers, makes the market better over time.

| Step | What happens | Where it lives |
|---|---|---|
| 1. Goal | You state a goal ("this part, under this price, by this date"). The agent skips parts you already own. | `agents/buyer/`, `demo/goal.py` |
| 2. Offers and veto | Offers arrive in a sealed round, today from real, dated store listings (MIRROR) and labelled simulated sellers (SIM). No seller sees your budget or another bid. The advocate checks fit by code (socket, length, wattage) and claims against the page, and vetoes a trap, with the source. | `agents/sellers/`, `agents/advocate/`, `data/fit_checker/` |
| 3. Screen | Shield screens every seller message, listing title and claim before any agent acts on it. An injected listing is quarantined with the rules that fired. | `shield/` |
| 4. Check the winner | Only the market's real rank 1 gets a mandate. Before any call or charge, the agent re-checks the winner's price live with Bright Data (when its key is set; otherwise the dated MIRROR price stays and the line says so) and runs one CRS check on the payee, whose id is bound into the mandate. | `demo/bridge.py`, `demo/sponsors_live.py`, `pay/crs_gate.py`, `agents/crs.py` |
| 5. Pay and receipt | Inside your allowance the deal pays without a call. Above it, a Cartesia voice agent phones you, reads the deal from a template filled by code, and answers "why not the cheaper one?". Code, not the voice agent, approves: only the one-time word pair on your screen plus "approve" passes, and it signs one mandate (deal, amount, payee, expiry). After the charge and again at settlement, you get a receipt. | `pay/approval.py`, `pay/voice_cartesia.py`, `pay/mandate.py`, `agents/buyer/checkout.py` |
| 6. Sellers learn | Each losing seller gets a loss report (a banded gap and the reason with its source, never a rival's price) and can adjust its next bid, never below its floor. | `demo/learning.py`, `sim/` |

The referee that ranks offers is deterministic: one ranking rule, ties broken in a fixed order, and the seller fee never enters the ranking.

```mermaid
flowchart LR
    U["Buyer<br/>(ASI:One or web)"] --> B["Buyer agent"]
    B -- "sealed request" --> S["Seller agents<br/>(Agentverse)"]
    S -- "bids" --> SH["Bazaar Shield<br/>screen, verify"]
    SH --> A["Quality advocate<br/>fit + claim checks"]
    M[("Dated listing mirrors<br/>Apify, Bright Data")] --> S
    M --> A
    A --> MK[("Market state<br/>SpacetimeDB")]
    MK --> W["Buyer and market screens"]
    MK -- "rank 1 only" --> G["Winner checks<br/>Bright Data price, CRS payee"]
    G -- "inside allowance" --> P["TAP-style signing<br/>Stripe test mode"]
    G -- "above allowance" --> C["Cartesia approval call"]
    C --> J["Approval judge<br/>(code)"]
    J -- "signed mandate" --> P
    P --> R["Receipt<br/>chat, Gmail via ASI:One"]
    A -- "loss report" --> S
```

Components and data flow in detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Key capabilities

- **A skeptic on the buyer's side.** The advocate is deterministic code, not a model. It can veto the cheapest bid and must cite a source for every warning.
- **Fit checking.** Rules over an open parts dataset plus maker specs; an unknown fit is "uncertain" and can never beat a confirmed fit.
- **Agent security as an API.** Bazaar Shield exposes `POST /v1/shield/screen`, `/verify-agent` and `/verify-mandate`, plus a claim check, with a published rule list. See [shield/API.md](shield/API.md).
- **Voice is the trust step, never the credential.** A recording of your voice cannot approve a payment: the code on your screen is single use, bound to one mandate, and silence, a hang-up or a mismatch all deny. A spoken approval with any other amount, payee or term denies.
- **Scoped, replay-proof payments.** Each mandate binds deal, amount, payee, expiry and nonce, and only the market's real winner gets one. A replayed or altered mandate fails, and a retry cannot charge twice.
- **A receipt for every spend.** The buyer agent tells you what it paid, with the charge reference and the mandate, after the charge and again at settlement.
- **IT purchasing controls.** PO numbers, a requester who cannot approve their own order, three-way match and an audit trail ([hyphenate/](hyphenate/)).

## For sellers

The buyer's protection needs no seller to join. The seller side is how the market grows.

The goal is a seller agent that works like a shop's best salesperson. It looks for real leeway to win a deal (another condition line, a perk, a small price step) and stays inside the shop's own prices and policy. When it loses, it learns why. When a strategy wins, the shop can see it and learn from it too.

What exists today:

- **Seller Kit.** A shop enters its store, pricing, perks and a floor for each condition, and gets a seller agent config and the command to start it ([seller_kit/api.py](seller_kit/api.py), the `/sell` screen, and a Claude conversation path in [docs/SELLER_SKILL.md](docs/SELLER_SKILL.md)). A shop made this way is labelled SIM, because the kit cannot verify a real shop.
- **UCP on every Seller Kit shop.** Each shop publishes a Universal Commerce Protocol profile and checkout sessions, and the buyer side has a UCP client ([seller_kit/ucp.py](seller_kit/ucp.py), [agents/buyer/ucp_client.py](agents/buyer/ucp_client.py)). It follows the draft spec and is not certified.
- **Floors the referee enforces.** No bid lands below the seller's floor, even from a compromised agent.
- **Loss reports.** Every losing seller gets a banded gap, the reason and its source. It never sees the buyer's cap or a rival's price.
- **A learning step you can inspect.** In the reference run, Gadget Grove (Vedant), a simulated shop, lost round 1 on price by under 5 percent. Its strategy moved its price step from 0 to 3 percent, it bid $1,247.44 open-box against a $1,190 floor, and it won round 2. A control seller that does not learn stayed at $1,329 ([demo/learning.py](demo/learning.py)).
- **A wind tunnel.** Simulated buyers test seller strategies against fixed controls ([sim/](sim/)). It shows no lift we can quote yet (see Measured results).
- **Seller Agent-Readiness Report.** A public, pay-per-event Actor on the Apify Store that shows a shop what an AI shopper sees on its listing, at $0.02 per listing ([Store page](https://apify.com/anoopibrampur/seller-agent-readiness-report)). Its source is in review ([#309](https://github.com/vs-githjk/cal-hacks-2026/pull/309)).

In progress: Market Pulse, a trend note for each losing seller built from its loss report and Tiger Data history, with a coaching line Claude picks from a closed list and that never goes below the floor. The module is merged and tested ([agents/pulse/market_pulse.py](agents/pulse/market_pulse.py)); no screen or agent sends it yet.

Planned, not built: richer selling moves (bundles, perks chosen per buyer) and a shop-level view of which strategies won, so a company can reuse what worked.

## What is real and what is simulated

Every bid, claim and screen carries a badge driven by the `source` field in the contracts. Full table: [docs/REAL_VS_SIMULATED.md](docs/REAL_VS_SIMULATED.md). Status as of Oct 24, 2026, 17:00 PDT.

| Component | Label | Notes |
|---|---|---|
| Store listings and prices | MIRROR | Real public listings in dated snapshots ([data/mirror/](data/mirror/)). We also used Apify to collect 12 real RTX 5070 Ti listings from Central Computers in San Francisco; the store is a listing source, not a partner. Its listing adapter is merged; it does not bid in the reference round yet |
| Seller agents and their bids | SIM | Our agents bid from mirrored listings; no outside shop has bid yet |
| Buyer's goal and owned parts | SIM | Scripted for the reference scenario; the buyer is Vidyut |
| Fit checks, claim checks, Shield | LIVE | Real code on every bid; claim checks run on pages we host for the demo |
| Approval call | LIVE | A real Cartesia phone call to one registered number, the only approval above the allowance; silence, a hang-up or a failed call denies, and nothing is paid. The reference runner types the call transcripts and says so |
| Request signing | LIVE | Signed in the style of Visa's Trusted Agent Protocol and verified by our merchant simulator, not by Visa |
| Payment | SIM by default | One Stripe test-mode charge on a Visa test card with `--stripe`; no real money |
| Receipts | LIVE in chat | The buyer agent sends the receipt after the charge and at settlement. The emailed receipt goes through ASI:One's Gmail connector from the buyer's own Gmail account, tested once live. Order, shipped and tracking messages are written ([agents/buyer/post_purchase.py](agents/buyer/post_purchase.py)) but not yet sent by the running agent; carrier and tracking are SIM |
| Bright Data | built, env-gated | Re-checks the winner's price live just before the call when its key is set; without it the dated MIRROR price stays, and the line says so. One live call returned the ASUS Prime at $1,299.99 (Sat 02:55) |
| Tiger Data | built, env-gated | Each round's prices are written to Tiger Data when its service is set, never on the money path; connection checked Sat 02:53 |
| CRS identity and fraud check | built, env-gated | One CRS check of the winning seller at the payment gate, before the call and the charge; a business payee needs a verified check, and an error, a timeout or "not configured" holds the payment. Run live against the CRS sandbox on Oct 24 at 16:37 PDT, with test identities for three simulated sellers: seller 1 and seller 2 came back verified_stable, seller 3 not_verified |
| UCP | built, draft spec | Seller Kit shops and the buyer client follow the draft spec; not certified |
| Wind tunnel buyers | SIM | Simulated by design |

## In progress

Not merged, or merged but not yet running in the app. None of this is described above as working.

- **The full PC build.** One sentence becomes a build plan, one round per part, one call for the whole build, one mandate per seller and a receipt per part ([#343](https://github.com/vs-githjk/cal-hacks-2026/issues/343), [#344](https://github.com/vs-githjk/cal-hacks-2026/issues/344), [#345](https://github.com/vs-githjk/cal-hacks-2026/issues/345)).
- **Sealed knockout rounds.** Up to three best-and-final stages; rule-breakers and last place are knocked out with reasons, and survivors only hear "still in" ([#336](https://github.com/vs-githjk/cal-hacks-2026/issues/336), [#337](https://github.com/vs-githjk/cal-hacks-2026/issues/337)).
- **Market Pulse** on a screen and in the seller agents (module merged, see For sellers).
- **Visa TAP conformance.** Matching `pay/tap.py` to Visa's published Trusted Agent Protocol ([#284](https://github.com/vs-githjk/cal-hacks-2026/issues/284)).
- **Central Computers bidding in the round.** Its MIRROR listing adapter and a dated snapshot are merged ([data/mirror/central_computers.py](data/mirror/central_computers.py)); it does not bid in the reference round yet.
- **No typed APPROVE in ASI:One.** Today a typed APPROVE reply starts the approval call (the call still decides); this change removes the reply ([#234](https://github.com/vs-githjk/cal-hacks-2026/pull/234)).
- **Order, shipped and tracking messages** sent by the running buyer agent.

## Measured results

Every number comes from [data/scoreboard.json](data/scoreboard.json), regenerated by `python3 -m data.scoreboard`. Headlines are first runs; anything fixed after reading a result is marked as no longer blind. All runs are dated 2026-10-24.

| Measure | Result | Reproduce |
|---|---|---|
| Shield, held-out attacks | 12 of 20 stopped; 2 of 10 honest listings wrongly blocked | `python3 -m shield.bench` |
| Fit checker | 39 of 39 right on maker-checked builds; 48 of 49 on all; 0 false OK (tuned set, not held out) | `python3 -m data.fit_checker.eval_builds` |
| Voice approval attacks | 9 of 10 denied on the first run (10 of 10 after one fix, not blind) | `python3 -m pytest pay/tests/test_voice_attacks.py -q` |
| Purchasing controls, blind planted errors | 26 of 27 caught on the first run; 2 of 7 clean cases falsely flagged | `python3 -m hyphenate.scenarios.blind_run --write` |
| Seller learning lift | No lift to quote: the learner beats the control on 1 of 4 held-out buyer types | `python3 -m sim.wind_tunnel --builders 48 --seeds 3` |
| Verified savings | None yet: the price reference is ready (7 retail asks from 2 providers), but no verified purchase is recorded | `python3 -m data.baselines` |

Shield on its development set stops 30 of 30, but its rules were written against that set, so we never pool it with the held-out result and never call Shield "secure."

## Built with

| Partner | What we use | Role in Tech Bazaar |
|---|---|---|
| Fetch.ai | uAgents, Agentverse, ASI:One and its Gmail connector, Agent Chat Protocol, Payment Protocol | Every agent is a uAgent; the buyer takes goals in ASI:One, a caller agent for the approval call runs locally, and ASI:One emails the receipt from the buyer's own Gmail |
| Visa | Trusted Agent Protocol (style), Visa test card | Signed agent requests; the test card behind the Stripe charge. Conformance to the published spec is in progress |
| Stripe | Test mode | The one sandbox charge, idempotent on the mandate hash |
| Cartesia | Voice agent, outbound calls | The approval call, the only approval above the allowance |
| Apify | Store Actors, plus four public Actors of our own on the Apify Store: [Listing Claim Checker](https://apify.com/anoopibrampur/tech-bazaar-claim-check), [PC Build Compatibility Checker](https://apify.com/anoopibrampur/pc-build-compatibility-checker), [Electronics Recall Checker](https://apify.com/anoopibrampur/electronics-recall-checker), [Seller Agent-Readiness Report](https://apify.com/anoopibrampur/seller-agent-readiness-report) | Listing mirrors, claim checks, fit checks and real San Francisco listings. Four Actor sources are in this repo: claim check, compatibility and recall (all on the Store) and an injection screen (not on the Store). The readiness Actor's source is in review ([#309](https://github.com/vs-githjk/cal-hacks-2026/pull/309)) |
| Bright Data | Scraper API | A live re-check of the winner's price before the call (built, env-gated) |
| Tiger Data | Time-series Postgres | Each round's prices, the history behind Market Pulse (built, env-gated) |
| CRS | Credit API sandbox | One identity and fraud check of the payee at the payment gate (built, env-gated; run live against the sandbox) |
| SpacetimeDB | Reducers and live state | Auction state; floors, one winner and approval-before-payment enforced in reducers. Live on Maincloud as `tech-bazaar` |
| Anthropic | Claude Haiku 5.5 | An opt-in Shield classifier for secret asks (`shield/classifier.py`, fails closed for sellers), Market Pulse coaching from a closed list (in progress), and optional seller persona lines. Claude never decides money |

Public data: the CPSC recalls API and [docyx/pc-part-dataset](https://github.com/docyx/pc-part-dataset) (MIT) for compatibility fields.

### Our Apify Actors

IDs and run ids read from the Apify account on Oct 24 2026 (anoopibrampur). Four are public; the Listing Injection Screen is private (Apify only needs the IDs).

| Actor | Actor ID | `username/actor-name` | URL | Pricing (pay per event) | Last successful run |
|---|---|---|---|---|---|
| Listing Claim Checker | `U4g8XPRpuGhDa97cM` | `anoopibrampur/tech-bazaar-claim-check` | https://apify.com/anoopibrampur/tech-bazaar-claim-check | $0.01 per `claim-checked` (only verified or false claims), $0.00005 per `apify-actor-start` | `T0ASSKGvCUf8DclZ5` (Oct 24 19:53 UTC) |
| PC Build Compatibility Checker | `djo1yhWs81xud1DkO` | `anoopibrampur/pc-build-compatibility-checker` | https://apify.com/anoopibrampur/pc-build-compatibility-checker | $0.005 per `build-checked`, $0.00005 per `apify-actor-start` | `oNgFAznvcXn3RCO7H` (Oct 24 20:04 UTC) |
| Electronics Recall Checker | `uMK7F4tqYnnbBkknU` | `anoopibrampur/electronics-recall-checker` | https://apify.com/anoopibrampur/electronics-recall-checker | $0.002 per `product-checked`, $0.00005 per `apify-actor-start` | `ItvSaUKtsjwhXd5jg` (Oct 24 22:48 UTC) |
| Seller Agent-Readiness Report | `whYB0iBdGanGPVv05` | `anoopibrampur/seller-agent-readiness-report` | https://apify.com/anoopibrampur/seller-agent-readiness-report | $0.02 per `listing-reported` (unreadable pages are free); default run 1 GB and 300 s | `Ug5TASTEbVcwSeCnV` (Oct 24 22:47 UTC) |
| Listing Injection Screen | `pzSsctJHHdNzrLJH8` | `anoopibrampur/listing-injection-screen` | https://console.apify.com/actors/pzSsctJHHdNzrLJH8 (private) | not set (private, free to run) | `CyjW4NhXhXlD9JFBL` (Oct 24, about 19:20 PDT: the honest SIM listing passed, the injected one was blocked) |

How useful each one is, and which are thin: [docs/ACTORS.md](docs/ACTORS.md).

## Fetch.ai agents

| Agent name | Role | Agentverse address |
|---|---|---|
| Tech Bazaar Buyer (@techbazaarbuyer) | Takes goals over the Chat Protocol, remembers owned parts, runs the sealed round, pays within the allowance | `agent1qwxhy93uzmw5prlqldm8a2mz9gsmc2563um6th2l6z0pudw63juej97nmj8` |
| Bazaar Advocate (@techbazaaradvocate) | Checks fit and claims; at most 3 cited warnings; can veto the cheapest bid; never sees the fee | `agent1qvxvlletez0ywdcq7da76ufzz4lvh5xvtd4fxam22g6phqzr07kvjcmhv05` |
| Bazaar Shield (@techbazaarshield) | Chat front door to Shield screening; makes no purchases | `agent1q0m2z43cf3hg4cfy87hatf69ulyqkvuylm6mjv53e6y05weqmhjj6k4lknp` |
| Byte Bros Outlet (@techbazaarseller1) | Seller agent: bids from its listings, never below its floor | `agent1qd3gvg54tsaezed0wzpgg34rza4y6kvvfd778nj6h27j20k99d38zd3et9m` |
| Silicon Sally's Surplus (@techbazaarseller2) | Seller agent | `agent1qw9dvuwgnh570wyk8uukp0w48a03tdpmtuv8csm3qxy6t3udl3ahs2264np` |
| FlashDeal Frankie (@techbazaarseller3) | Seller agent; carries the planted condition trap (SIM) | `agent1qdcrmqy2ra2tvshq2qhc8q5rvqzpr7du77st32qynwazy48gtuvyspdm26l` |
| Bay Area PC Shop (@techbazaarseller4) | Seller agent: fixed margin | *not registered yet* |
| ReNew Refurb (@techbazaarseller5) | Seller agent: refurbished and open-box lines | *not registered yet* |
| Bazaar Caller (@techbazaarcaller) | Places the one approval call for a mandate; approves and charges nothing itself | *runs locally, not registered yet* |

Each agent has a short name, a full README and a themed avatar. Registration details and profile checks: [agents/README.md](agents/README.md).

## Getting started

**Prerequisites:** Python 3.12, Node.js with npm, the SpacetimeDB CLI, and sandbox keys for the services you want live (names in [.env.example](.env.example)). The launcher tells you what is missing.

```bash
git clone https://github.com/vs-githjk/cal-hacks-2026.git tech-bazaar && cd tech-bazaar
cp .env.example .env                                  # your own sandbox keys; .env is gitignored
python3 scripts/launch.py up --env-file .env          # preflight, then start every service that can start
python3 scripts/launch.py status                      # service, port, pid, health
python3 scripts/launch.py down                        # stop only what it started
```

`up` prints one OK or MISSING line per prerequisite with its fix, then starts SpacetimeDB, Shield (8787), the seller, advocate and buyer agents, and the web app (3100). A service without its prerequisites shows as SKIPPED, never as up. Nothing is installed globally.

<details>
<summary>Run the reference scenario and the tests</summary>

```bash
python3 demo/run_demo.py              # all five steps; writes demo/out/run-<timestamp>.json
python3 demo/run_demo.py --stripe     # adds one Stripe test-mode charge (needs an sk_test_ key)
python3 -m pytest -q --ignore=agents  # Python tests
agents/.venv/bin/python -m pytest -q agents
```

More: [demo/README.md](demo/README.md), [pay/README.md](pay/README.md), [shield/API.md](shield/API.md).
</details>

## Repository structure

```
agents/      Fetch.ai uAgents: buyer, quality advocate, sellers, Shield client, caller, Market Pulse
contracts/   Shared JSON schemas (Goal, Bid, ShieldVerdict, Mandate, LossReport, ...)
data/        Listing mirrors, fit checker, claim checks, baselines, scoreboard, Apify Actors
demo/        The reference scenario, stage runner and market bridge
hyphenate/   IT purchasing controls and blind test scenarios
market/      SpacetimeDB module and auction rules (sealing, scoring, outcomes)
pay/         Approval judge, mandates, CRS gate, request signing, merchant simulator, Cartesia call client
seller_kit/  Seller Kit API and UCP profile
shield/      Bazaar Shield API, rules, attack corpus and bench
sim/         Wind tunnel: simulated buyers and hostile agents
web/         Next.js buyer and market screens
docs/        Architecture, real vs simulated, red team, research notes
```

## Safety and design invariants

These live in code and tests, not in prompts.

1. **No payment without a limit check and an approval** for the same mandate hash. Inside the allowance the limit check is the approval; above it, only the call approves. No answer means no payment.
2. **No agent acts on another agent's text before Shield screens it.** Screening fails closed for payments.
3. **No seller bids below its floor,** enforced in market reducers, so even a compromised agent cannot.
4. **Sealed bids.** Sellers never see your budget, your allowance or each other's bids.
5. **Scoped mandates:** one seller, an amount cap, an expiry, single use and an idempotency key, and only for the market's real winner.
6. **The agent never re-buys a part you own** unless you ask.
7. **Sandbox only:** test cards and test identities, no real money, no secrets in the repository.
8. **Anything simulated is labelled** on screen and in this README.

## Roadmap

- Outside sellers bidding live through the Seller Kit and an open seller protocol.
- Seller agents that sell better within their shop's policy, and a shop-level report of the strategies that won.
- Small IT buyers (10 to 50 machines), where sealed volume bids matter most.
- Visa Intelligent Commerce tokens in place of the Stripe path, given sandbox access.
- Tech Bazaar as an MCP server, so any agent can request bids.

## Team

Vidyut Sriram, Vedant Shirvi, Abhinav, Anoop Ibrampur.

## License

Tech Bazaar is released under the [MIT License](LICENSE). Copyright (c) 2026 the Tech Bazaar team.

Third-party data keeps its own license, including [docyx/pc-part-dataset](https://github.com/docyx/pc-part-dataset) (MIT). Product and retailer names belong to their owners and are shown for price comparison only.

[^1]: Capital & Compute, [NVIDIA GPU prices](https://capitalandcompute.net/gpu-prices/nvidia/), citing Tom's Hardware, Sep 1, 2026.
[^2]: Anthropic, [Piloting Claude for Chrome](https://www.anthropic.com/news/claude-for-chrome), Aug 25, 2025: 23.6 percent attack success without mitigations, 11.2 percent with them.
[^3]: Microsoft Research, [Magentic Marketplace](https://arxiv.org/abs/2510.25779), arXiv 2510.25779, Oct 2025.
