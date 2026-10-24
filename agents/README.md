# agents/ (Lane A): buyer, Quality Advocate and seller agents

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Fetch.ai uAgents for Tech Bazaar. The buyer takes a goal in ASI:One ("a GPU for 1440p that fits my case and PSU, under $800, by Friday"), remembers what the buyer already owns, runs a sealed round with three seller agents, has the Quality Advocate check every bid, and asks for approval before any payment.

## Agents

| Agent | Role | Agentverse address | Status |
|---|---|---|---|
| Tech Bazaar Buyer (@techbazaarbuyer) | Goal in ASI:One (Chat Protocol), ownership memory, sealed round, approval, Payment Protocol (buyer side) | `agent1qwxhy93uzmw5prlqldm8a2mz9gsmc2563um6th2l6z0pudw63juej97nmj8` | Registered on Agentverse (mailbox) |
| Tech Bazaar Quality Advocate (@techbazaaradvocate) | Checks each bid: fit (Lane C fit checker), condition claim vs listing page, price history, CPSC recall, seller record. At most 3 warnings, each with a source; can veto the cheapest bid; never sees the fee | `agent1qvxvlletez0ywdcq7da76ufzz4lvh5xvtd4fxam22g6phqzr07kvjcmhv05` | Registered on Agentverse (mailbox) |
| Byte Bros Outlet (@techbazaarseller1) | Seller agent: bids from its listings, price from policy code, never below floor | `agent1qd3gvg54tsaezed0wzpgg34rza4y6kvvfd778nj6h27j20k99d38zd3et9m` | Registered on Agentverse (mailbox) |
| Silicon Sally's Surplus (@techbazaarseller2) | Seller agent | `agent1qw9dvuwgnh570wyk8uukp0w48a03tdpmtuv8csm3qxy6t3udl3ahs2264np` | Registered on Agentverse (mailbox) |
| FlashDeal Frankie (@techbazaarseller3) | Seller agent; the planted trap (listed as new, the page says open box) | `agent1qdcrmqy2ra2tvshq2qhc8q5rvqzpr7du77st32qynwazy48gtuvyspdm26l` | Registered on Agentverse (mailbox) |

Addresses come from private seeds in `agents/.env` (never committed). Seller listings, prices and records are SIM (simulated, example.com links).

## Run

From `agents/`, with Python 3.12:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -q
```

Put the keys and agent seeds in `agents/.env` (see the repo's `.env.example`; values never go in git). Then, each in its own terminal:

```bash
.venv/Scripts/python sellers/run_all.py
.venv/Scripts/python -m advocate.advocate_agent
.venv/Scripts/python buyer/buyer_agent.py
```

For Agentverse and ASI:One, set `AGENTS_MAILBOX=1`, run each agent in its own process (sellers: `python sellers/seller_agent.py seller_1`, ports 8011 to 8013), and register each once with `python connect.py <port>` (8001 buyer, 8003 advocate, 8011 to 8013 sellers). Local web chat fallback: `python buyer/web_chat.py`, then open http://localhost:8080.

## Safety rules in code

- No `CommitPayment` without an approval row for the same mandate hash (`pay.mandate.mandate_hash`); a replayed, altered, expired or wrong-payee mandate is rejected (`payment.py`, tested).
- Every incoming agent message is screened by Shield first; anything but `allow` is dropped (fails closed if Shield is unreachable).
- Prices come from policy code, never from a model. Fit is decided by Lane C's checker, never by a model.
- The voice call gets only `{rule_id, summary, source_url}`; the summary is a fixed template per rule_id (`advocate/checks.py` CALL_SUMMARIES).

Where it could go wrong: the goal parser is regex-based and maps a "1440p GPU" to one SKU (SIM table until Lane C's SpecCards land); a buyer who does not state PSU connector counts gets "fit not confirmed"; Stripe charges wait on Lane D.
