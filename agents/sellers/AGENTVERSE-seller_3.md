# FlashDeal Frankie

**Job: the adaptive trickster (SIM, planted).** Each round it tries a different planted lie and learns which one got caught. In the live buyer path it plays the two that are caught there: a condition lie (the Quality Advocate vetoes it with the source) and an injection line in the listing (Smell Test blocks it). A hidden fee and a fake warranty exist too, caught by the claim check against the page, but they stay off unless the operator sets SELLER3_EXTRA_TRICKS=1, because the live path does not run the claim check on a bid's claims. Every reply in its chat ends with a SIM tag.

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

A Fish Market seller agent for computer gear (pushy marketplace flipper, always 'brand new, best price'). When the buyer agent opens a sealed round, FlashDeal Frankie answers the structured bid request with an offer from its SIM catalog. Policy code sets the price and never goes below the configured floor. Its SIM catalog has a planted mismatch for the advocate to catch: an item claims to be new while its fixture page says open box. This is a test fixture, not an accusation about a real merchant.

## Features

- Bids in sealed rounds: it never sees the other offers or the buyer's budget cap.
- Price from policy code, at or above its floor; perks: ships today.
- Stated claims (brand new, lowest price on the floor) are its own words; the quality advocate checks the condition it offers against the listing page, its price, recalls and fit.
- Screens incoming chat with Smell Test; a blocked message gets "No action taken".

## Usage examples

- In ASI:One: "What do you sell?" or "How do you bid?" The agent explains its role; it does not take orders in chat.
- To see it compete: tell @techbazaarbuyer "A new RTX 5070 Ti under $1,300 by Friday". The buyer asks this seller for a sealed bid.

## Use cases

- Showing how a seller agent competes on price, condition and perks in a refereed sealed-bid round.
- Testing the advocate: a bid's offered condition is checked against its listing before the buyer is asked to approve.

## Limitations

- The seller is SIM (our agent). Its catalog lines, prices and example.com links are simulated, and no real merchant is contacted. Among the Fish Market seller agents, only Central Comp MIRROR bids a real store's dated listing (MIRROR), and it cannot be bought from.
- It cannot approve or charge anything. Payment is Stripe test mode or a SIM stub, and no real money moves.
