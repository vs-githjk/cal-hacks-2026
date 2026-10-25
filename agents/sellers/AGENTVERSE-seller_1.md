# Byte Bros Outlet

**Job: the learner.** It learns its margin across rounds from its own losses and wins, never below its floor, and keeps a visible strategy note (for example "Lost 2 of 3, last by under 5%, stepping to 9.5% off list").

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

A Fish Market seller agent for computer gear (steady big-box retailer, fair prices, no surprises). When the buyer agent opens a sealed round, Byte Bros Outlet answers the structured bid request with an offer from its SIM catalog. Policy code sets the price and never goes below the configured floor. 

## Features

- Bids in sealed rounds: it never sees the other offers or the buyer's budget cap.
- Price from policy code, at or above its floor; perks: free shipping, 30-day returns.
- Stated claims (all items new retail, sealed) are its own words; the quality advocate checks the condition it offers against the listing page, its price, recalls and fit.
- Learns in code: a price loss adds the banded gap as a step (plus a little momentum on a streak), a loss on fit or condition leaves price alone, and a win probes margin back. It has an input for Market Pulse's banded coaching note, which no agent delivers to it yet. It sees only its own loss reports, its own orders and its own bids, never a rival's bid or the buyer's budget.
- Answers chat in character: who it is, its strategy note, and its current offer for a part. The words are built from code; a model may only rephrase them, and never sets a price.
- Screens incoming chat with Smell Test; a blocked message gets "No action taken".

## Usage examples

- In ASI:One: "What do you sell?" or "How do you bid?" The agent explains its role; it does not take orders in chat.
- To see it compete: tell @techbazaarbuyer "A new RTX 5070 Ti under $1,300 by Friday". The buyer asks this seller for a sealed bid.

## Use cases

- Showing how a seller agent competes on price, condition and perks in a refereed sealed-bid round.
- Testing the advocate: a bid's offered condition is checked against its listing before the buyer is asked to approve.

## Limitations

- Listings, prices and example.com links are simulated (SIM); no real merchant is contacted.
- It cannot approve or charge anything. Payment is Stripe test mode or a SIM stub, and no real money moves.
