# Fish Market Buyer

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Your buying agent for computer gear. Tell it a goal; it remembers what you already own, makes seller agents bid against each other in a sealed round, has a Quality Advocate check every bid with a source, and never moves money without your approval.

## What to ask

- "A new GPU for 1440p that fits my case and PSU, under $800, by Friday. I already own a 750 W PSU and a mid-tower case with 330 mm GPU clearance."
- "Build me a new GPU, PSU and case under $1200 by Sunday."
- "A new 850 W PSU under $150 by Monday."

Then it phones you to approve the bid it recommends: say the spoken code on the call. There is no typed approval.

## What it does

1. Turns your message into a goal (budget cap, part by date, or build by date).
2. Skips parts you already own and cites your own words ("you already own it, your note at 21:58").
3. Runs a sealed round with five seller agents. Sellers never see your cap.
4. The Quality Advocate checks fit (socket, GPU length, PSU wattage, decided by code), the condition claim against the listing page, price history, CPSC recalls and the seller's record. It can veto the cheapest bid and cites a source for every warning.
5. You approve; payment uses the Fetch.ai Payment Protocol with a single-use mandate bound to that exact deal.

## Honest labels

Seller listings and prices in this demo are simulated (SIM). No real money moves: payments are Stripe test mode.

Built at Cal Hacks 13.0 by the Fish Market team.

## Summary

Fish Market's buying agent (The agentic marketplace where buyers and sellers thrive): one goal in, sealed seller bids, an advocate's review with sources, and a purchase only after the buyer approves (by phone call only).

## Features

- Skips parts the buyer already owns, and checks fit before asking for bids.
- Runs a sealed round: sellers never see each other's offers or the buyer's cap.
- Every bid goes to the quality advocate; a vetoed bid cannot win.

## Usage examples

- "A new RTX 5070 Ti that fits my case, under $1,300, by Friday, new or open-box."
- "A new 850 W PSU under $150 by Monday."

## Use cases

- Buying a GPU without paying for one that does not fit or is not what the listing claims.

## Limitations

- Seller catalogs are SIM or MIRROR (dated real listings); payment is Stripe test mode and no real money moves.
- Approval is by phone call only: the owner speaks a one-time code on the call, and no chat message approves an order. No real money moves.

