# Bidding Royale architecture

This is the design we are building at Cal Hacks 13.0. What is built so far is tracked in the README's [Status](../README.md#status) table; what is real versus simulated is in [REAL_VS_SIMULATED.md](REAL_VS_SIMULATED.md).

## System diagram

```mermaid
flowchart LR
    owner["Restaurant owner<br/>ASI:One chat"]

    subgraph buyerSide["Restaurant side (agents/)"]
        buyer["Buyer agent<br/>usage, forecast, auction, payment"]
        advocate["Devil's advocate<br/>Claude"]
    end

    subgraph trust["Trust layer (shield/, pay/)"]
        shield["Shield API<br/>/screen /verify-agent /check-claim"]
        tap["Visa Trusted Agent Protocol<br/>sign and verify"]
        crs["CRS sandbox<br/>supplier stability"]
        payment["Payment Protocol<br/>Stripe test mode, Visa test card"]
        vic["Visa Intelligent Commerce<br/>adapter, sandbox access only"]
    end

    subgraph marketBox["Market (market/)"]
        stdb[("SpacetimeDB<br/>needs, bids, claims,<br/>verdicts, orders")]
    end

    subgraph supplierSide["Supplier side (agents/, sim/)"]
        gateway["Supplier gateway"]
        fleet["Supplier agents<br/>StorePolicy prices, Claude persona line"]
        tunnel["Wind tunnel<br/>simulated buyers, hostile agents"]
    end

    subgraph dataBox["Data and truth (data/)"]
        apify["Apify actors<br/>supplier catalog mirrors"]
        checkActor["Claim-check Actor"]
        bright["Bright Data<br/>wider web"]
        usda["USDA Market News<br/>wholesale baseline"]
    end

    subgraph screens["Screens (web/)"]
        floor["3D floor"]
        dash["Owner and supplier dashboards"]
    end

    owner <--> buyer
    buyer -- "sealed need" --> stdb
    stdb -- "items, specs, window<br/>no spend limit" --> gateway
    gateway --> fleet
    fleet -- "signed bids" --> shield
    shield -- "verdicts, claim checks" --> stdb
    shield --> tap
    shield --> checkActor
    checkActor --> bright
    fleet --> apify
    stdb -- "bids after deadline" --> advocate
    advocate --> usda
    advocate --> apify
    advocate --> crs
    advocate -- "card, max 3 warnings" --> buyer
    buyer -- "CommitPayment, signed mandate" --> payment
    payment -. "swap in if granted" .- vic
    payment -- "order, payment ref" --> stdb
    stdb --> floor
    stdb --> dash
    tunnel -- "training runs" --> fleet
    tunnel -- "hostile messages become tests" --> shield
```

## One order, step by step

```mermaid
sequenceDiagram
    autonumber
    participant O as Owner, in chat
    participant B as Buyer agent
    participant M as Market (SpacetimeDB)
    participant S as Supplier agents
    participant SH as Shield
    participant A as Devil's advocate
    participant P as Payment

    B->>B: Forecast next week from UsageRecords
    B->>M: post Need (items, specs, delivery window, auction window)
    M->>S: request for bids, spend limit withheld
    S->>SH: signed Bid with claims
    SH->>SH: verify TAP signature, screen text, check claims
    SH->>M: ShieldVerdict and Claim results
    M->>M: reject any bid below floor, keep bids sealed
    M->>A: all bids at the deadline
    A->>A: spec match, delivery, price vs baseline, CRS signal
    A->>B: AdvocateCard, at most 3 sourced warnings
    alt Best verified bid is inside the owner's limits
        B->>P: CommitPayment with signed single-use mandate
        B->>O: notify: what was ordered, from whom, why
    else Outside the limits
        B->>O: approval card
        O->>B: approve or reject
        B->>P: CommitPayment only after approval
    end
    P->>M: Order with payment reference
```

## Components

| Component | Folder | Lane | What it does |
|---|---|---|---|
| Buyer agent | `agents/` | A | uAgent with the Agent Chat Protocol, reachable in ASI:One. Reads `UsageRecord`s, writes a `Forecast` per item, posts a `Need`, collects bids, pays through the Payment Protocol within the owner's `spend_limit`. |
| Devil's advocate | `agents/` | A | Claude-based agent that builds an `AdvocateCard` per bid: spec equivalence (grade, pack size, case count), delivery claims, price against the baseline, CRS stability signal. Drops any warning its evidence does not support; caps warnings at three. |
| Supplier agents and gateway | `agents/` | A | Each supplier agent prices from policy code (floor, discount curve, perks) over Apify-mirrored prices. The language model only writes the persona's line. About six agents register on Agentverse; the rest run as a labelled fleet behind the gateway. |
| Market | `market/` | B | SpacetimeDB module holding needs, bids, claims, verdicts and orders. Reducers enforce the floor price, sealed bids and approval before payment. Convex is the fallback if SpacetimeDB blocks us. |
| Screens | `web/` | B | Next.js owner view and supplier dashboard, plus the three.js 3D floor. Every character and motion comes from a market row. |
| Data and truth | `data/` | C | Apify actors mirror supplier catalogs with a snapshot id and date. Our claim-check Actor returns verified, unverified or false with evidence. Bright Data covers the wider web. USDA Market News is the wholesale baseline. |
| Shield | `shield/` | D | FastAPI service. `/screen` checks agent messages for planted instructions, scam patterns and mandate mismatches (payee or amount differs from the approved need). `/verify-agent` consumes Trusted Agent Protocol signatures. `/check-claim` calls the claim checker. Also flags near-identical bids across suppliers. |
| Payments and identity | `pay/` | D | Trusted Agent Protocol signing on every agent request to a supplier. Stripe test-mode charge on a Visa test card through the Payment Protocol. Visa Intelligent Commerce adapter behind the same interface. CRS adapter that returns only a `SupplierSignal`. |
| Wind tunnel | `sim/` | D | Simulated buyers, honest and hostile, run against a supplier's agent. Reports conversion, margin kept and attacks that landed. Every hostile message becomes a Shield test case. |

## Contracts

All lanes talk through the JSON schemas in [`contracts/`](../contracts/). Changes need a line in [CHANGES.md](CHANGES.md).

| Contract | Carries |
|---|---|
| `UsageRecord` | Weekly quantity used per item spec, per buyer |
| `Forecast` | Predicted quantity, the reason, and last week's error |
| `Need` | Items, delivery window, spend limit, consent, auction window |
| `Bid` | Lines, total landed price, perks, claims, floor check result, mirror snapshot id, decision trace, expiry |
| `Claim` | One supplier claim and its check result with evidence |
| `ShieldVerdict` | Allow, quarantine or block, with reasons and attack type |
| `SupplierSignal` | `verified_stable`, `caution` or `not_verified`, with the check time |
| `AdvocateCard` | Warnings with sources and a recommendation |
| `Order` | Amount, approval, limit check, idempotency key, payment reference, status |
| `LedgerEntry` | Double-entry lines for the purchasing and payables seat (stretch) |
| `Persona` | A supplier character's name, archetype, voice and model |
| `FloorEvent` | What the 3D floor animates, always traced to a market row |

Every record that can be real or not carries a `source` field (`live`, `mirror`, `simulated`, `sandbox`, `recorded`). The UI turns it into the LIVE, MIRROR, SIM, SANDBOX or RECORDED badge.

## Trust boundaries

- **Restaurant to supplier.** Suppliers receive items, specs and the delivery window. The spend limit, the usage history and other bids never cross.
- **Supplier to restaurant.** Every supplier message passes Shield before any agent reads it. Claims are checked against a page, not taken on trust.
- **CRS.** Credit and loan data stay inside the CRS check. Only the `SupplierSignal` leaves it.
- **Money.** A payment needs a signed mandate with an amount cap, one supplier, an expiry and single use. Shield fails closed on payments: if screening times out, nothing is paid.

## Staying up during a live demo

The plan is for each external adapter (Apify, Bright Data, USDA, CRS, Claude, Visa, Stripe) to run in one of three modes: live, cached or replay. Calls time out after 4 to 6 seconds and fall back to a committed, dated snapshot, and the footer shows which mode each service is in, so a fallback is never silent. Each service exposes `/health`, and a labelled recorded run of the full path is the last resort.
