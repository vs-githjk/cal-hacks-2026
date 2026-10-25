# Fish Market Quality Advocate

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

Fish Market's quality advocate for computer gear. It argues for the buyer: for each seller bid it checks hardware fit with code, compares the claimed condition with the listing, and checks the price against dated baselines and the CPSC recall database. It returns at most three warnings, each with a source, and can veto a bid that is a trap.

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

- Price baselines are MIRROR (dated retail asks from two data owners) and recalls come from the CPSC public API, cached per brand for 24 hours. A lookup that fails or has no data gets a note saying it is unverified, never a silent pass. We hold no real seller records yet, so it makes no seller-record warning. Listing pages for the SIM sellers are pages we host (SIM); MIRROR listings are dated copies of real store pages.
- It cannot approve, pay or contact sellers; it only advises the buyer agent.
