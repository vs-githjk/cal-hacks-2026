# Silicon Sally's Surplus

**Not run in the live roster: same job as ReNew Refurb (seller_5). Its code and data stay for the web arena and tests.**

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

A Fish Market seller agent for computer gear (chatty refurb specialist who loves a deal). When the buyer agent opens a sealed round, Silicon Sally's Surplus answers the structured bid request with an offer from its SIM catalog. Policy code sets the price and never goes below the configured floor. 

## Features

- Bids in sealed rounds: it never sees the other offers or the buyer's budget cap.
- Price from policy code, at or above its floor; perks: 1-year shop warranty on refurbs, free thermal paste.
- Stated claims (refurbished units bench-tested 24h) are its own words; the quality advocate checks the condition it offers against the listing page, its price, recalls and fit.
- Screens incoming chat with Smell Test; a blocked message gets "No action taken".

## Usage examples

- In ASI:One: "What do you sell?" or "How do you bid?" The agent explains its role; it does not take orders in chat.
- Retired: Silicon Sally's Surplus is not run and the buyer does not ask it for bids (`RETIRED_SELLERS` in `agents/common.py`). To see a round, tell @techbazaarbuyer "A new RTX 5070 Ti under $1,300 by Friday"; it asks the four running sellers.

## Use cases

- Showing how a seller agent competes on price, condition and perks in a refereed sealed-bid round.
- Testing the advocate: a bid's offered condition is checked against its listing before the buyer is asked to approve.

## Limitations

- The seller is SIM (our agent). Its catalog lines, prices and example.com links are simulated, and no real merchant is contacted. Among the Fish Market seller agents, only Central Comp MIRROR bids a real store's dated listing (MIRROR), and it cannot be bought from.
- It cannot approve or charge anything. Payment is Stripe test mode or a SIM stub, and no real money moves.
