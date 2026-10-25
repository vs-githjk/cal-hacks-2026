# Fish Market Buyer

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Your buying agent for computer gear. Tell it a goal; it remembers what you already own, makes seller agents bid against each other in a sealed round, has a Quality Advocate check every bid with a source, and never moves money without your approval.

## What to ask

- "A new GPU for 1440p that fits my case and PSU, under $800, by Friday. I already own a 750 W PSU and a mid-tower case with 330 mm GPU clearance."
- "Build me a new GPU, PSU and case under $1200 by Sunday."
- "A new 850 W PSU under $150 by Monday."

Then it phones you to approve the bid it recommends: say the spoken code on the call. There is no typed approval; typing a reply never approves anything. The call rings the phone number on your own Fish Market profile, only if the operator's call allowlist (when one is set) includes it, and at most once per number every 5 minutes.

## What it does

1. Turns your message into a goal (budget cap, part by date, or build by date).
2. Skips parts you already own and cites your own words ("you already own it, your note at 21:58").
3. Runs a sealed round with up to four seller agents (Byte Bros Outlet, FlashDeal Frankie, ReNew Refurb and Central Comp MIRROR). Sellers never see your cap.
4. The Quality Advocate checks fit (socket, GPU length, PSU wattage, decided by code), the condition claim against the listing page, price history, and CPSC recalls (it makes no seller-record warning yet: we hold no real seller records). It can veto the cheapest bid and cites a source for every warning.
5. You approve by phone call only. Payment is Stripe test mode, bound to a mandate for that exact deal. A payment request sent in chat is refused on purpose.

## Starter prompts

- "I need a new RTX 5070 Ti that fits my mid-tower case with 330 mm GPU clearance and my existing 750 W PSU, for under $1,300, delivered by Friday. New or open-box is fine, but tell me which condition each seller is offering."
- "Build me a gaming PC with an RTX 5070 Ti, a 750 W PSU and a case, under $1,800 in total by Sunday. I already own an NVMe drive and a CPU cooler, so skip those."
- "Find a new 850 W PSU under $150 by Monday, make the sellers compete, and show me the Quality Advocate's warnings with sources before I approve anything."

## Keywords

buying agent, computer parts, GPU, RTX 5070 Ti, PC build, sealed-bid auction, compatibility check, price comparison, purchase approval, shopping agent, Fish Market

## Honest labels

Store listings are MIRROR: real, dated copies of public store listings. The seller agents are SIM: ours, not the stores. Central Comp MIRROR bids a real store's listing for comparison and can never be ordered or paid. No real money moves: payments are Stripe test mode.

Built at Cal Hacks 13.0 by the Fish Market team.

## Summary

Fish Market's buying agent (The secure agentic marketplace where buyers and sellers thrive): one goal in, sealed seller bids, an advocate's review with sources, and a purchase only after the buyer approves (by phone call only).

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

