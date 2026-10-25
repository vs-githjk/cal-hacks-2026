# Market Pulse

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

The Fish Market orchestration layer. It watches finished sealed-bid rounds and teaches the market what the week and the month look like: a note for every seller that lost a round (what to change, inside its own floor and policy, plus its own 7-day and 30-day record) and a price trend for every part (lowest, median and current price over 7 and 30 days, and how many sellers listing it are CRS verified).

## Features

- Every sentence is a fixed phrase filled with numbers it read from a source. No model text and no question text reaches a seller or a buyer.
- Every number names its source in brackets: a Tiger Data table, the CRS signals cache or a round id, and its origin (LIVE, MIRROR or SIM).
- Where Tiger Data holds fewer days than a window, it says "only N days of data" and never pads. Without Tiger Data configured, the week and month figures are a fixture and every line says SIM.
- A seller note never contains a rival's price, the winning price, the buyer's cap or another seller's record.
- Screens incoming chat with Smell Test; a blocked message gets "No action taken".

## What it accepts

- Agent Chat Protocol: a question about a part's price trend or a seller's record. It screens the message with Smell Test, acknowledges it, and answers with fixed phrases. Your words only pick which known part or seller to talk about; they are never repeated back. Anything else gets a short help message.
- A PulseRound message (a finished sealed round as JSON), only from the addresses in PULSE_ROUND_SENDERS (the referee and the operator). It replies with PulseNotes, one note per seller that lost. From anyone else, or with PULSE_ROUND_SENDERS unset, the round is ignored.

## Example ASI:One prompts

- "How is the RTX 5070 Ti trending?"
- "How is the RTX 4070 Super 12GB trending?"
- "How is the RX 7800 XT trending?"
- "How is the PSU 750W trending?"
- "How is the PSU 850W trending?"
- "Why does seller_3 keep losing?" (answered only to that seller's own agent, unless the operator set PULSE_SELLER_CHAT=open)
- "Why does seller_4 keep losing?"
- "Help"

## SIM, MIRROR and LIVE

- Every line ends with a bracket naming its source and its origin: LIVE, MIRROR or SIM.
- Without Tiger Data configured, the week and month figures come from a built-in fixture and every line says SIM.
- With Tiger Data, a line carries the origins of the rows it was built from. Prices from a real store's public listings are labelled MIRROR; they are comparison prices, not offers you can buy here.
- Market Pulse never bids, buys or moves money in any mode.

## Usage examples

- "How is the RTX 5070 Ti trending?" answers with the last 7 and 30 days of price and the CRS verified seller count.
- "Why does seller_3 keep losing?" answers with that seller's 7-day and 30-day record and its note from the latest round.

## Use cases

- Sellers learn within policy why they lose, and whether it is a streak or a bad day.
- Buyers see whether now is a good time to buy a part and how many of its sellers have passed an identity check.

## Limitations

- Setup: run `python3 -m data.tiger.load` once per Tiger service (it creates the tables and loads the price history).
- It cannot place bids, approve purchases or move money.
- Week and month figures are real only once Tiger Data holds real rounds and prices; until then they are labelled SIM.
- A seller's record is shown only to that seller's own agent. The operator can open it to anyone with PULSE_SELLER_CHAT=open.
- A finished round is accepted only from the addresses in PULSE_ROUND_SENDERS (the referee and the operator, comma separated); with none set, none is accepted.
