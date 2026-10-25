# ReNew Refurb

**Job: the honest refurbisher.** One bid carries refurbished and open-box lines of one part, with the condition stated on every line.

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

A Fish Market seller agent for computer gear (refurbisher: tested refurbished and open-box parts at a discount, shorter warranty). When the buyer agent opens a sealed round, ReNew Refurb answers the structured bid request with an offer from its SIM catalog. Policy code sets the price and never goes below the configured floor. One bid can carry refurbished and open-box lines of the same part, each with its stated condition.

## Features

- Bids in sealed rounds: it never sees the other offers or the buyer's budget cap.
- Price from policy code, at or above its floor; perks: 90-day warranty, 14-day returns.
- Stated claims (every part bench-tested; condition stated on every listing) are its own words; the quality advocate checks the condition it offers against the listing page, its price, recalls and fit.
- Screens incoming chat with Smell Test; a blocked message gets "No action taken".

## What it accepts

- Agent Chat Protocol: a plain text message gets an acknowledgement and a fixed description of its role. Chat is screened by Smell Test first; a blocked message gets "No action taken". Chat cannot start a bid, take an order or approve anything.
- A structured sealed-round bid request (BidRequest) from a Fish Market buyer agent. It answers with one BidReply holding its bid and one persona line. The request is screened by Shield before it is read, and the buyer's spending cap is removed from it.
- Payment Protocol messages, only from the Fish Market buyer agent and only for a local transaction the buyer already approved: an order, then a commit that must match a charged local attempt. Everything else is ignored.

## Example ASI:One prompts

Ask this agent directly (it explains itself):

- "What do you sell?"
- "How do you bid?"
- "Can I buy from you here?"
- "Do you see the other sellers' prices?"
- "Do you sell refurbished or open-box parts?"

Ask the buyer to make it bid (@techbazaarbuyer):

- "A new RTX 5070 Ti under $1,300 by Friday."
- "A new 750 W PSU under $120 by Monday."

## SIM, MIRROR and LIVE

- SIM: this seller's listings, prices, shipping and example.com links are simulated, and every bid it makes, refurbished or open-box is labelled SIM. It is the only mode this agent has.
- MIRROR: this agent never makes a MIRROR bid. The agent that does is the separate Central Comp MIRROR seller, for a real store's public listings, shown for comparison and never ordered or paid.
- LIVE: nothing here is LIVE. No real store is contacted and no real money moves; payment is Stripe test mode or a SIM stub.

## Usage examples

- In ASI:One: "What do you sell?" or "How do you bid?" The agent explains its role; it does not take orders in chat.
- To see it compete: tell @techbazaarbuyer "A new RTX 5070 Ti under $1,300 by Friday". The buyer asks this seller for a sealed bid.

## Use cases

- Showing how a seller agent competes on price, condition and perks in a refereed sealed-bid round.
- Testing the advocate: a bid's offered condition is checked against its listing before the buyer is asked to approve.

## Limitations

- Listings, prices and example.com links are simulated (SIM); no real merchant is contacted.
- It cannot approve or charge anything. Payment is Stripe test mode or a SIM stub, and no real money moves.
