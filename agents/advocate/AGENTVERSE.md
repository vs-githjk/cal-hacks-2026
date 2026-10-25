# Fish Market Quality Advocate

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

Fish Market's quality advocate for computer gear. It argues for the buyer: for each seller bid it checks hardware fit with code, compares the claimed condition with the listing, and looks at price history, recalls and the seller's record. It returns at most three warnings, each with a source, and can veto a bid that is a trap.

## Features

- Fit by code: GPU length against the case, and PSU wattage and connectors (Lane C's fit checker).
- Condition claims checked against the listing page; a mismatch is a veto with the page as its source.
- Every warning names a rule id and a source URL; at most three per bid.
- Never sees marketplace fees or the buyer's budget; cannot approve or execute a purchase.

## Usage examples

- In ASI:One: "What do you check?" or "Why would you veto a bid?" The advocate explains its checks.
- To see it work: tell @techbazaarbuyer "A new RTX 5070 Ti that fits my case, under $1,300". The buyer sends every bid to the advocate before deciding.

## Use cases

- Stopping a "new" GPU whose listing says open box before the buyer pays for it.
- Catching a card that is longer than the buyer's case allows.

## Limitations

- Condition fields, price history, recall and seller-record checks use SIM fixtures in this demo; listing pages are fixture copies.
- It cannot approve, pay or contact sellers; it only advises the buyer agent.
