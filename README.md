# Bidding Royale

**Suppliers bid for your restaurant's weekly ingredient order. Your agent predicts what you need, checks every bid, and orders the best verified offer within limits you set.**

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Built at Cal Hacks 13.0 (October 23 to 25, 2026) by a team of four.

> **Status, Fri Oct 23, 20:10 PDT.** Hacking started at 18:00. This README describes the design we are building. A piece counts as working only when the [Status](#status) table says "built" and links the proof. The demo video and live link go here once they exist.

**Jump to:** [Problem](#the-problem) · [How it works](#how-it-works) · [Architecture](docs/ARCHITECTURE.md) · [Sponsors](#sponsor-technology) · [Real vs simulated](#real-vs-simulated) · [Agents](#fetchai-agents) · [Quickstart](#quickstart) · [Safety](#invariants-safety-by-design) · [Status](#status)

---

## The problem

**Who feels it:** owners and kitchen managers of independent restaurants with 1 to 5 locations, who order ingredients every week from several suppliers. Next: any business that buys raw materials at volume, such as manufacturers.

**What hurts:**

- **Food is the biggest cost they can control, and its price moves every week.** Independents have no procurement team, so they pay more than chains.
- **Ordering eats hours.** It happens by phone, text and supplier portals, every week.
- **Quantities are a guess.** Over-order and it becomes waste. Under-order and dishes run out.
- **Cheapest is not always best.** A lower quote is only worth taking if the spec really matches (grade, pack size, case count), the delivery promise holds, and the supplier is stable enough to keep delivering. An owner cannot see a supplier's finances, and the supplier should not have to show them.

## What Bidding Royale does

The restaurant gets a **buyer agent** that learns how fast the kitchen uses each ingredient ("200 carrots lasted a week"), predicts next week's order, and puts it up for a **sealed auction**. **Supplier agents** bid. Before anything is bought, the restaurant's **devil's advocate** argues against weak bids, **Shield** screens every agent message, and **CRS** confirms each supplier's financial stability without revealing their private data. Then the buyer agent orders within the owner's limits and tells the owner what it did.

Suppliers get a **wind tunnel**: they train their bidding agent against simulated buyers, honest and hostile, before it goes live.

A **3D market floor** shows supplier personas haggling. It draws the live market state and nothing else.

Commodity items with the same spec are what make this work: when every bid is for the same grade, pack size and case count, price, delivery and supplier quality can be compared fairly, which branded goods do not allow.

## How it works

1. **Learn.** The buyer agent reads past orders and counts and records weekly usage per item.
2. **Predict.** It forecasts next week's quantity for each item, with a reason and last week's forecast error.
3. **Request.** It posts the order as a sealed request for bids: items with exact specs, a delivery window, and a short auction window. The owner can start or change an order by chatting with the agent in ASI:One.
4. **Bid.** Supplier agents bid until the deadline. Bids stay sealed, suppliers never see the restaurant's spend limit, and the market rejects any bid below the supplier's floor price. Prices come from policy code; the language model only writes the persona's line.
5. **Screen.** Shield screens every agent-to-agent message, verifies each request's Visa Trusted Agent Protocol signature, and checks supplier claims (stock, delivery, fees, price) against the live page.
6. **Challenge.** The devil's advocate checks each bid for spec equivalence, delivery claims, price against the USDA wholesale baseline and public supplier prices, and the CRS stability signal. It shows at most three warnings, each with a source.
7. **Order.** If the best verified bid fits the owner's limits, the agent orders and notifies the owner. If not, an approval card waits in ASI:One. Payment runs through the Fetch.ai Payment Protocol over Stripe test mode, charging a Visa test card, under a signed single-use mandate.
8. **Watch.** A second screen shows the 3D floor and dashboards on the same market state: same market, two views.

Diagram, components and data flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Why this is different

- **The buyer has a skeptic on its side.** A price list tells you what is cheapest. The devil's advocate tells you when the cheapest bid is not the same item, will not arrive in time, or comes from a supplier under strain, and it cites a source for every warning.
- **Known agent-market failures are designed out.** Microsoft's Magentic Marketplace study (arXiv 2510.25779) found that buyer agents favor the first proposal they see and that malicious sellers can redirect payments. Sealed bids remove the first-mover advantage. Shield's mandate check blocks any payment whose payee or amount differs from what the owner approved.
- **Identity says who; Shield says whether it is true.** Visa's Trusted Agent Protocol proves which agent sent a request. Shield checks whether what that agent claims holds up.
- **Privacy by design.** CRS checks a supplier's credit and pending loans inside our system and shares only a signal (verified stable, caution, or not verified). Neither side sees the other's private data.

## Sponsor technology

| Sponsor | Product | What it does in Bidding Royale | Depth |
|---|---|---|---|
| Fetch.ai | uAgents, Agentverse, ASI:One, Agent Chat Protocol | Every agent is a uAgent registered on Agentverse. The owner's whole order (request, bids, warnings, approval, payment) runs in an ASI:One chat. | Core |
| Fetch.ai | Payment Protocol, Interactive Cards | The supplier sends `RequestPayment`; the buyer sends `CommitPayment` with a signed mandate, only within limits or after approval. Bids, warnings and approvals appear as cards, with a plain-text fallback (numbered bids, reply `APPROVE <id>`). | Core |
| Visa | Trusted Agent Protocol | Every agent request to a supplier is signed with HTTP Message Signatures and verified at the supplier and in Shield. The UI shows "signature verified". | Core |
| Visa | Visa card over Stripe test mode or Link | The payment is a Stripe test-mode charge on a Visa test card, made through the Payment Protocol. | Core |
| Visa | Intelligent Commerce (tokenized agent credentials) | An adapter behind the same payment interface. It replaces the Stripe path only if Visa grants sandbox access. | Adapter |
| Apify | MCP server, Store actors, our own Actor | Mirrors public supplier catalogs and prices: WebstaurantStore, Sysco, CHEF'STORE (Restaurant Depot, Sysco and US Foods prices), Instacart and Costco. We also build and publish a claim-check Actor: claim and URL in, verified, unverified or false plus evidence out. | Core |
| Bright Data | MCP server, SERP API, Web Unlocker | Price and claim checks across the wider web. | Core |
| CRS | Credit API sandbox, MCP server | Checks each supplier's financial stability inside our system and shares only the signal. Provided test identities only. | Core |
| Armadin | Shield API (our build) | Shield is our agent-to-agent security API. In the demo a judge attacks the market and Shield blocks it. | Core |
| Spacetime | SpacetimeDB | Holds the live auction state that every screen and the 3D floor read, and enforces the floor price and approval-before-payment rules in reducers. | Core |
| Anthropic | Claude | Reasoning for the devil's advocate and the one line each supplier persona speaks. | Core |
| Cartesia | Voice | Supplier personas haggle aloud on the floor. | Tier 1 |
| Hyphenate | Purchasing and accounts payable seat | Purchase order, delivery, invoice, three-way match and approval. | Stretch |

Public data, not a sponsor: **USDA Market News** wholesale prices are the neutral price baseline.

## Real vs simulated

Every bid, claim and screen carries a badge (**LIVE**, **MIRROR**, **SIM**, **SANDBOX** or **RECORDED**) driven by the `source` field in the contracts. The working copy of this table is [docs/REAL_VS_SIMULATED.md](docs/REAL_VS_SIMULATED.md).

| Component | Label | What that means |
|---|---|---|
| Restaurant order and usage history | SIM | Seeded demo history until a real restaurant shares its data |
| Supplier catalogs and prices | MIRROR | Real public prices, mirrored by Apify with a date |
| Supplier bids | SIM over MIRROR | Our agents bid with demo floor prices over real public prices. These are price mirrors, not participating suppliers. Any real supplier that joins bids LIVE. |
| Claim checks | LIVE or MIRROR | LIVE against supplier pages we host for the demo; MIRROR for real suppliers |
| The caught liar | LIVE, planted | A planted attack on a page we host, with a lie toggle and an answer key. We never call a real supplier a liar; real pages get neutral wording ("differs from the listing at time T", "could not verify"). |
| Market price baseline | LIVE or cached | Public USDA Market News data, with the source on every price warning |
| CRS supplier stability | SANDBOX | Real sandbox calls on CRS-provided test identities |
| Payments | SANDBOX | Stripe test mode, Visa test card, no real money |
| Visa Trusted Agent Protocol signatures | LIVE | Real signing and verification on every request |
| Visa Intelligent Commerce | Adapter | Swaps in only with Visa sandbox access |
| Shield verdicts | LIVE | Real screening on every message |
| Wind tunnel buyers | SIM | Simulated by design |
| 3D floor | LIVE state | Characters are drawn from market rows; click one to see its row |

## Fetch.ai agents

> **Team: fill this table as each agent registers on Agentverse.** A row marked *pending* is not registered yet.

| Agent name | Role | Agentverse address |
|---|---|---|
| *pending* | Buyer agent: learns usage, predicts the order, runs the auction, pays within limits | *pending* |
| *pending* | Devil's advocate: challenges each bid with cited warnings | *pending* |
| *pending* | Shield: screens messages, verifies signatures, checks claims | *pending* |
| *pending* | Supplier gateway: routes requests to the supplier fleet | *pending* |
| *pending* | Supplier agent, named persona 1 | *pending* |
| *pending* | Supplier agent, named persona 2 | *pending* |

The rest of the supplier fleet runs behind the gateway and is labelled as a fleet in the UI.

## Repo layout

Each lane owns its folders and talks to the others only through `contracts/`.

```
contracts/  shared JSON schemas: Need, Bid, Claim, ShieldVerdict, SupplierSignal,
            AdvocateCard, Order, LedgerEntry, UsageRecord, Forecast, Persona, FloorEvent
agents/     Lane A: Python uAgents (buyer, advocate, supplier agents), ASI:One chat, Payment Protocol
market/     Lane B: SpacetimeDB module (auction state and rules)
web/        Lane B: Next.js owner view, supplier dashboard, 3D floor (three.js)
data/       Lane C: Apify and Bright Data adapters, supplier mirrors, USDA baseline, claim checks
shield/     Lane D: FastAPI Shield API (/screen, /verify-agent, /check-claim)
pay/        Lane D: Stripe and Visa adapters, Trusted Agent Protocol signing, CRS adapter
sim/        Lane D: wind tunnel (simulated buyers, hostile agents)
docs/       architecture, sponsor map, real vs simulated, interviews, kickoff prompts, team board
```

## Quickstart

> Run commands are added as each lane's code lands. Until then, this section lists what you need.

1. **Clone and configure.** `git clone https://github.com/vs-githjk/cal-hacks-2026.git && cd cal-hacks-2026`, then:
   ```bash
   cd bidding-royale
   cp .env.example .env   # fill in your own sandbox keys; .env is gitignored
   ```
2. **Set these environment variables** (names from [.env.example](.env.example)):

   | Variable | Used for |
   |---|---|
   | `ANTHROPIC_API_KEY` | Devil's advocate and persona lines |
   | `AGENTVERSE_API_KEY`, `ASI1_API_KEY` | Agent registration and ASI:One |
   | `APIFY_TOKEN` | Supplier mirrors and the claim-check Actor |
   | `BRIGHT_DATA_API_KEY` | Wider web price and claim checks |
   | `USDA_MARKET_NEWS_API_KEY` | Wholesale price baseline |
   | `CRS_API_KEY` | Supplier stability check (sandbox) |
   | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` | Test-mode payments |
   | `VISA_TAP_PRIVATE_KEY_PATH` | Trusted Agent Protocol request signing |
   | `VISA_VIC_API_KEY` | Intelligent Commerce adapter, only with sandbox access |
   | `SPACETIMEDB_URI` | Live market state |
   | `CARTESIA_API_KEY` | Persona voices (optional) |
   | `NESSIE_API_KEY` | Optional; not used in the main flow |

3. **Run each lane:** agents, market, web, Shield. Commands are added here as each lane merges.

## Invariants (safety by design)

These are enforced in code and covered by tests, not left to prompts.

1. **No order beyond the owner's limits.** The agent orders on its own only inside limits the owner set, and notifies the owner every time. Anything outside them waits for an approval card.
2. **Every supplier claim shown to the owner has a check result:** verified, unverified or false, with evidence.
3. **No agent acts on another agent's text before Shield screens it.** Screening fails closed for payments.
4. **The 3D floor and every screen render real market state only.**
5. **No supplier agent bids below its floor**, enforced in the market reducers, so even a compromised agent cannot.
6. **Sealed bids.** Suppliers see the items, specs and delivery window, never the spend limit or each other's bids.
7. **Private financial data stays private.** CRS checks run inside our system; both sides see only the stability signal, never raw data.
8. **Scoped payments.** Each mandate has an amount cap, one supplier, an expiry, single use and an idempotency key.
9. **Sandbox only.** Test identities and test cards, no real money, no secrets in the repo.
10. **Anything simulated is labelled** in the UI and in this README.

## Numbers we will report

Nothing is measured yet. These are the methods; results go here with the date and dataset once measured, including results that show no effect.

| Number | Method |
|---|---|
| Price vs market baseline | Winning bid against the dated USDA and public-price baseline on 20 to 30 real items. Real price spread and simulated bid discount are reported separately, never blended. |
| Forecast error | Predicted vs actual weekly quantity per item, from the `Forecast` records |
| Advocate precision and recall | Against a hand-labelled answer key of 30 to 50 cases with planted issues and clean controls |
| Shield catch rate, false-positive rate, latency | On a frozen held-out attack set plus unseen wind-tunnel attacks. Design targets: rule checks under 50 ms, 1.5 s timeout. |
| Wind tunnel lift | Supplier policy tuned on a training set; before and after on held-out simulated buyers, against a cheapest-wins baseline |

## Team and lanes

> **Team: add your names and GitHub handles.**

| Lane | Owns | Member |
|---|---|---|
| A: Agents | Buyer, advocate and supplier agents; ASI:One chat; Payment Protocol; Interactive Cards | *to add* |
| B: Market and floor | SpacetimeDB market, owner and supplier views, 3D floor, voices | *to add* |
| C: Data and truth | Apify and Bright Data mirrors, USDA baseline, claim checks, measured numbers | *to add* |
| D: Pay and trust | Shield, Visa and Stripe, Trusted Agent Protocol, CRS, wind tunnel | *to add* |

## Status

Updated with every merge. States: **planned**, **in progress**, **built** (with a link to the PR or test).

| Piece | State |
|---|---|
| Contracts (JSON schemas) | in progress: first version in `contracts/` |
| Buyer agent on Agentverse, reachable in ASI:One | planned |
| Usage learning and order forecast | planned |
| Supplier agents bidding from Apify mirrors | planned |
| Sealed auction with floor enforced in reducers | planned |
| Devil's advocate with cited warnings | planned |
| Shield `/screen`, `/verify-agent`, `/check-claim` | planned |
| Trusted Agent Protocol signing and verification | planned |
| Stripe test-mode payment through the Payment Protocol | planned |
| CRS supplier stability signal | planned |
| Wind tunnel | planned |
| 3D floor | planned |
| Visa Intelligent Commerce adapter | planned, needs sandbox access |

## Roadmap

**During the hackathon**
- **Tier 0, by Sat Oct 24, 14:00 PDT:** the hero loop. An order request in ASI:One, 3 to 6 sealed bids, one planted liar caught with evidence, the advocate card, approval, payment, and the floor mirroring every step.
- **Real people:** two real restaurants or suppliers in the loop and one real order by the same time.
- **Tier 1:** a Shield console where judges type a hostile message and see the verdict, wind tunnel numbers, persona voices.
- **Tier 2:** 3D polish, extra personas, the purchasing and payables seat.

**After the hackathon**
- Supplier onboarding: paste a catalog URL, set a floor and perks, go live.
- Manufacturers and other high-volume raw material buyers.
- Visa Intelligent Commerce tokens in place of the Stripe path.
- Bidding Royale as an MCP server, so any agent can request bids.

## License

MIT. See [LICENSE](LICENSE).
