# Tech Bazaar Buyer

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Your buying agent for computer gear. Tell it a goal; it remembers what you already own, makes seller agents bid against each other in a sealed round, has a Quality Advocate check every bid with a source, and never moves money without your approval.

## What to ask

- "A new GPU for 1440p that fits my case and PSU, under $800, by Friday. I already own a 750 W PSU and a mid-tower case with 330 mm GPU clearance."
- "Build me a new GPU, PSU and case under $1200 by Sunday."
- "A new 850 W PSU under $150 by Monday."

Then reply `APPROVE <number>` to order the bid it recommends.

## What it does

1. Turns your message into a goal (budget cap, part by date, or build by date).
2. Skips parts you already own and cites your own words ("you already own it, your note at 21:58").
3. Runs a sealed round with three seller agents. Sellers never see your cap.
4. The Quality Advocate checks fit (socket, GPU length, PSU wattage, decided by code), the condition claim against the listing page, price history, CPSC recalls and the seller's record. It can veto the cheapest bid and cites a source for every warning.
5. You approve; payment uses the Fetch.ai Payment Protocol with a single-use mandate bound to that exact deal.

## Honest labels

Seller listings and prices in this demo are simulated (SIM). No real money moves: payments are Stripe test mode.

Built at Cal Hacks 13.0 by the Tech Bazaar team.
