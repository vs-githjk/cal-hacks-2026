# Market Pulse

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

## Summary

Fish Market's price-discovery agent. Before each round it publishes a fair-price band for every part (low, median, high, how many prices it rests on, the date, and the source), so a buyer knows what a part really costs before sellers bid. After each round it gives every seller that lost a coaching note with concrete numbers ("you lost by less than 5 percent; the 7-day median is $1,279") and its own 7-day and 30-day record. Ask it in chat what the going price of a part is, or how it is trending.

## Features

- Fair-price band per part: the 25th, 50th and 75th percentile of in-stock retail asks over the last 7 days, or the last 30 days when the week is thin. From Tiger Data price history, then dated MIRROR snapshots, then (clearly labelled) the SIM catalog. It never pads: where a window has fewer days of data, it says "only N days of data".
- A public pulse before each round: one sourced JSON file, and an open request any agent can send (PulseBandRequest, a list of parts), answered with the bands. No seller, buyer or budget appears in it.
- Coaching notes for losing sellers: how far the seller lost (as a band), what the market's median and typical range for the part are, its own record, and what to change inside its own floor. A note never contains a rival's price, the winning price or the buyer's cap.
- Going price and demand in chat: the band with its sources, when the pulse was published, and how many rounds ran for the part in the last day.
- Every sentence is a fixed phrase filled with numbers it read from a source. No model text and no question text reaches a seller or a buyer.
- Every number names its source in brackets (a Tiger Data table, the snapshot date, the CRS signals cache or a round id) and its origin (LIVE, MIRROR, SIM or SANDBOX).
- Screens incoming chat with Smell Test; a blocked message gets "No action taken".
- Ask about its own data and get cited answers: it searches (BM25 keyword retrieval, no model needed) its finished rounds, dated MIRROR listings, CRS checks and Tiger Data prices, and every claim ends with the number of the source it rests on and a label (LIVE, MIRROR or SIM). A source line gives what it is, its date and its URL or round id. With no source, it says it has no data and makes no claim. Optionally Claude (claude-haiku-5-5) rewords the lines, but a reworded line is used only if it keeps the same source numbers and adds no figure. It describes; it never ranks sellers, recommends a purchase or decides anything, and a round is kept without any bid or price, so no seller's price reaches another seller.

## What it accepts

- Agent Chat Protocol: a question about a part's going price or price trend, or a seller's record. It screens the message with Smell Test, acknowledges it, and answers with fixed phrases. Your words only pick which known part or seller to talk about; they are never repeated back. Anything else gets a short help message.
- PulseBandRequest (skus_json, for example ["rtx 5070 ti", "psu 750w"], at most 20 parts), from any agent. It replies with PulseBands, the public pulse, or a fixed error (shield_blocked, bad_request, rate_limited). Each sender may ask 6 times a minute, and it never changes the pulse file the round refresh writes.
- A PulseRound message (a finished sealed round as JSON), only from the addresses in PULSE_ROUND_SENDERS (the referee and the operator). It replies with PulseNotes, one note per seller that lost, then refreshes the public pulse for the parts that round priced. From anyone else, or with PULSE_ROUND_SENDERS unset, the round is ignored.

## Example ASI:One prompts

- "What's the going price for an RTX 5070 Ti?"
- "How is the RTX 5070 Ti trending?"
- "How is the RTX 4070 Super 12GB trending?"
- "What is a fair price for a PSU 750W?"
- "How is the RX 7800 XT trending?"
- "Why does seller_3 keep losing?" (answered only to that seller's own agent, unless the operator set PULSE_SELLER_CHAT=open)
- "How did RTX 5070 Ti prices move this week?"
- "Which seller won most GPU rounds?"
- "Is Byte Bros CRS verified?"
- "Help"

## Starter prompts

- "I am about to buy an RTX 5070 Ti. What is the fair price band for it this week, how many prices is it based on, and is the number real, dated MIRROR data or a simulation?"
- "Before my buyer agent opens a round for a 750 W PSU, tell me the going price and the demand for it in the last day, and name where each number comes from."
- "I run a seller agent that keeps losing rounds on the RTX 5070 Ti. Show me my 7-day and 30-day record and how my last loss compares with the market median."
- "Is the RTX 5070 Ti getting cheaper or more expensive over the last month, and how many days of data does that rest on?"
- "How did RTX 5070 Ti prices move this week? Give me the median for each day from the dated listings you hold, and the source and URL behind every number."
- "Which seller won the most GPU rounds on record, how many rounds is that out of, and which round does each win come from?"
- "Is Byte Bros CRS verified? Tell me what the check said, when it was made, whether it is still current, and whether it was a real CRS sandbox call or a simulation."

## Keywords

price discovery, fair price, going price, price band, price history, price trend, market data, demand signals, seller coaching, GPU prices, RTX 5070 Ti, PC parts, sealed-bid auction, Fish Market

## SIM, MIRROR and LIVE

- Every line ends with a bracket naming its source and its origin: LIVE, MIRROR, SIM or SANDBOX.
- With Tiger Data price rows, a line carries the origins of the rows it was built from. Prices from a real store's public listings are labelled MIRROR; they are comparison prices, not offers you can buy here.
- Without Tiger Data rows, the band falls back to dated MIRROR snapshots (and says Tiger Data has no rows), then to the SIM seller listings, labelled SIM with "no price history yet". A SIM band is shown only when enough sellers list the part (4 besides the asker, or 5 when the asker is unknown); with fewer it says "no data", because a band of two or three prices would give one seller's price away. The week and month trend figures come from a built-in fixture and every line says SIM until Tiger Data holds real rounds and prices.
- A CRS check is labelled SANDBOX (a vendor's test mode, with a synthetic representative identity), or SIM when it is a simulated check. Nothing in Pulse's answers is labelled LIVE unless a real outside party was read now.
- Market Pulse never bids, buys or moves money in any mode.

## Usage examples

- "What's the going price for an RTX 5070 Ti?" answers with the typical price, the range, how many prices it rests on, the date and the source, then the demand line.
- "How is the RTX 5070 Ti trending?" answers with the last 7 and 30 days of price and the CRS verified seller count.
- "Why does seller_3 keep losing?" answers with that seller's 7-day and 30-day record and its note from the latest round.
- A loss note, for example: "You lost by less than 5 percent. The 7-day median for RTX 5070 TI is $1,279.00 (typical range $1,250.00 to $1,300.00, 12 prices). [Tiger Data price_obs, last 7 days; MIRROR]"

## Use cases

- Buyers see what a part really costs before sellers bid, and whether now is a good time to buy it.
- Sellers learn within policy why they lose, by how much, against what the market says, and whether it is a streak or a bad day.

## Limitations

- Setup: run `python3 -m data.tiger.load` once per Tiger service (it creates the tables and loads the price history). `python3 -m agents.pulse.fair_band --tiger-check` says whether Tiger Data holds price rows.
- It cannot place bids, approve purchases or move money.
- Part listings (CPU, motherboard, memory, storage, cooler) come from dated MIRROR snapshots of real stores. There are no PSU or case rows in the snapshots yet, so a PSU or case question gets "I have no dated listings for that part" until they are captured.
- Answers about "this week" rest on the dated listings it actually holds; with one day of data it says so instead of reporting a move. "Which seller won most rounds" counts only finished rounds it has kept (the Pulse agent saves each referee round; the repo's sample round is SIM). A CRS check older than 24 hours is shown with its age and is not called current.
- A note shows how far a seller lost only as a band (less than 5, 10 or 20 percent, or more than 20), never an exact figure, so a seller cannot work out the winner's price from it. The only dollar figures in a note are the market's public fair band.
- A seller's record is shown only to that seller's own agent. The operator can open it to anyone with PULSE_SELLER_CHAT=open.
- A finished round is accepted only from the addresses in PULSE_ROUND_SENDERS (the referee and the operator, comma separated); with none set, none is accepted.
