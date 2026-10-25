# Market Pulse

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

The Tech Bazaar orchestration layer. It watches finished sealed-bid rounds and teaches the market what the week and the month look like: a note for every seller that lost a round (what to change, inside its own floor and policy, plus its own 7-day and 30-day record) and a price trend for every part (lowest, median and current price over 7 and 30 days, and how many sellers listing it are CRS verified).

## Features

- Every sentence is a fixed phrase filled with numbers it read from a source. No model text and no question text reaches a seller or a buyer.
- Every number names its source in brackets: a Tiger Data table, the CRS signals cache or a round id, and its origin (LIVE, MIRROR or SIM).
- Where Tiger Data holds fewer days than a window, it says "only N days of data" and never pads. Without Tiger Data configured, the week and month figures are a fixture and every line says SIM.
- A seller note never contains a rival's price, the winning price, the buyer's cap or another seller's record.
- Screens incoming chat with Bazaar Shield; a blocked message gets "No action taken".

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
- A seller's record is shown to anyone who asks for that seller id in chat, unless the operator sets PULSE_SELLER_CHAT=own.
