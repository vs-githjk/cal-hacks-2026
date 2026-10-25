# Fish Market Quality Advocate

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

Fish Market's quality advocate for computer gear. It argues for the buyer: for each seller bid it checks hardware fit with code, compares the claimed condition with the listing, and looks at price history, recalls and the seller's record. It returns at most three warnings, each with a source, and can veto a bid that is a trap.

## Features

- Fit by code: GPU length against the case, and PSU wattage and connectors (Lane C's fit checker).
- Condition claims checked against the listing page; a mismatch is a veto with the page as its source.
- Every warning names a rule id and a source URL; at most three per bid.
- Total cost of ownership: ranks the bids that were not vetoed by landed price plus condition, warranty, return window and the seller's receiving record, with the numbers. Advisory: the referee's ranking by landed price stays the rule.
- Asks before it vetoes: when a listing page leaves the condition open, it sends the seller ONE chat question, waits a few seconds, and decides in code with the answer cited. No answer is an unverified veto.
- One plain sentence and a source link for every veto, caution and approval.
- Answers "is this card worth it?" and "will it fit my case?" in chat with the same checks it runs on a bid.
- Never sees marketplace fees or the buyer's budget; cannot approve or execute a purchase. A model may reword the explanation sentence; it never decides a veto.

## Usage examples

- In ASI:One: "Is an RTX 4070 Super at $590 new, 36 month warranty, 30 day returns worth it? My case clearance is 330 mm, the card is 267 mm long, it needs 1x 8-pin and my 750W PSU has 2x 8-pin." The advocate answers with fit, total cost and a source.
- In ASI:One: "What do you check?" or "Why would you veto a bid?" The advocate explains its checks.
- To see it work: tell @techbazaarbuyer "A new RTX 5070 Ti that fits my case, under $1,300". The buyer sends every bid to the advocate before deciding.

## Use cases

- Stopping a "new" GPU whose listing says open box before the buyer pays for it.
- Catching a card that is longer than the buyer's case allows.

## Limitations

- Condition fields, price history, recall and seller-record checks use SIM fixtures in this demo; listing pages are fixture copies.
- Warranty, return window and the seller track record are used only when the bid or a local track file states them; a missing term earns no credit and is listed as missing. The cost weights are our own assumptions, written in agents/advocate/tco.py.
- A seller can answer the clarifying question only if its own chat handler replies in plain words (new, open-box, refurbished or used); a seller that only sends its profile text counts as silent.
- It cannot approve or pay; it only advises the buyer agent, and its only contact with a seller is the one question above.
