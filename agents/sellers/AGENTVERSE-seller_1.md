# Byte Bros Outlet

**Job: the learner.** It learns from a loss report: a banded price gap becomes a price step, never below its floor.

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

A Tech Bazaar seller agent for computer gear (steady big-box retailer, fair prices, no surprises). When the buyer agent opens a sealed round, Byte Bros Outlet answers the structured bid request with an offer from its SIM catalog. Policy code sets the price and never goes below the configured floor. 

## Features

- Bids in sealed rounds: it never sees the other offers or the buyer's budget cap.
- Price from policy code, at or above its floor; perks: free shipping, 30-day returns.
- Stated claims (all items new retail, sealed) are its own words; the quality advocate checks the condition it offers against the listing page, its price, recalls and fit.
- Screens incoming chat with Bazaar Shield; a blocked message gets "No action taken".

## Usage examples

- In ASI:One: "What do you sell?" or "How do you bid?" The agent explains its role; it does not take orders in chat.
- To see it compete: tell @techbazaarbuyer "A new RTX 5070 Ti under $1,300 by Friday". The buyer asks this seller for a sealed bid.

## Use cases

- Showing how a seller agent competes on price, condition and perks in a refereed sealed-bid round.
- Testing the advocate: a bid's offered condition is checked against its listing before the buyer is asked to approve.

## Limitations

- Listings, prices and example.com links are simulated (SIM); no real merchant is contacted.
- It cannot approve or charge anything. Payment is Stripe test mode or a SIM stub, and no real money moves.
