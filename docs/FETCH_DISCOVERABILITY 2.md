# Fetch.ai discoverability checklist (#383 item 7)

Goal: the caller, seller 4 (Bay Area PC Shop), seller 5 (ReNew Refurb) and Market Pulse are registered on Agentverse, found in ASI:One, and each has 10 or more real ASI:One interactions. The code and READMEs are done; the steps below need your accounts, so you run them by hand. Never commit seeds, keys or addresses you want kept private.

READMEs the agents publish: `agents/caller/AGENTVERSE.md`, `agents/sellers/AGENTVERSE-seller_4.md`, `agents/sellers/AGENTVERSE-seller_5.md`, `agents/pulse/AGENTVERSE.md`.

## 1. Env vars (agents/.env, gitignored)

| Agent | Seed (private, 16+ characters, never ends in `-dev`) | Mailbox flag | Optional |
|---|---|---|---|
| Seller 4 | `SELLER_4_AGENT_SEED` | `SELLERS_MAILBOX=1` | |
| Seller 5 | `SELLER_5_AGENT_SEED` | `SELLERS_MAILBOX=1` | |
| Caller | `CALLER_AGENT_SEED` | `CALLER_MAILBOX=1` | `CALLER_AGENT_HANDLE` (default `techbazaarcaller`) |
| Market Pulse | `PULSE_AGENT_SEED` | `PULSE_MAILBOX=1` | `PULSE_AGENT_HANDLE` (default `techbazaarpulse`) |

`AGENTS_MAILBOX=1` turns on every agent at once. Also set `AGENTVERSE_API_KEY`. A seed fixes the agent's address: changing it later makes a new agent.

Market Pulse only: set `PULSE_ROUND_SENDERS` to a comma separated list of agent addresses allowed to send it a finished round: the referee agent's address and your own operator agent address (copy each from its Agentverse page). With it unset, Market Pulse accepts no round and only answers chat. `PULSE_SELLER_CHAT=open` lets anyone read any seller's record; leave it unset for the default (a record is answered only to that seller's own agent).

## 2. Register each agent (one terminal each, from `agents/`)

Start the agent, then register it once while it is running.

```bash
# seller 4 and seller 5 (together, with the other sellers)
SELLERS_MAILBOX=1 .venv/Scripts/python sellers/run_all.py
.venv/Scripts/python connect.py 8014
.venv/Scripts/python connect.py 8015

# caller
CALLER_MAILBOX=1 .venv/Scripts/python caller/caller_agent.py
.venv/Scripts/python connect.py 8006

# Market Pulse
PULSE_MAILBOX=1 PULSE_ROUND_SENDERS=<referee address>,<operator address> .venv/Scripts/python pulse/orchestrator.py --serve
.venv/Scripts/python connect.py 8018
```

(On Windows PowerShell set the variables with `$env:NAME = 'value'` or put them in `agents/.env`.) If run_all prints `seller_4 skipped: set SELLER_4_AGENT_SEED`, the seed is missing.

## 3. Check each profile

- [ ] Agentverse shows the agent Active, with the right name, handle and README (both badges, the new sections "What it accepts", "Example ASI:One prompts", "SIM, MIRROR and LIVE").
- [ ] Chat Protocol appears in its published protocols.
- [ ] You uploaded its avatar (`agents/avatars/`; the caller, seller 4 and seller 5 PNGs exist).
- [ ] You can find it by name in a fresh ASI:One chat.
- [ ] Add each address to the table in `agents/README.md` and replace "not registered yet".

## 4. Ten or more ASI:One interactions per agent

Use a fresh ASI:One conversation per agent, address it by handle, and keep each prompt a real message. Note the conversation link for each. Everything here is SIM unless stated; no money moves.

### Bay Area PC Shop (@techbazaarseller4)

Chat only explains its role. Replies are the same fixed description, so vary the questions.

1. What do you sell?
2. How do you bid?
3. Can I buy from you here?
4. Do you see the other sellers' prices?
5. Are your listings real?
6. Do you offer local pickup?
7. What is your return policy?
8. What does your shop specialize in?
9. Who should I talk to if I want to buy a GPU?
10. Can you approve a payment for me?
11. Do you know my budget?
12. Is the RTX 5070 Ti in stock?

Then to see it bid, ask @techbazaarbuyer: "A new RTX 5070 Ti under $1,300 by Friday." (its bid appears among the five sellers').

### ReNew Refurb (@techbazaarseller5)

1. What do you sell?
2. How do you bid?
3. Do you sell refurbished or open-box parts?
4. Can I buy from you here?
5. Do you see the other sellers' prices?
6. What warranty do you give?
7. Are your parts tested?
8. Are your listings real?
9. Can you approve a payment for me?
10. Do you know my budget?
11. What is your return window?
12. Which seller is cheapest?

Then ask @techbazaarbuyer: "A new RTX 5070 Ti under $1,300 by Friday." (the refurbished and open-box lines both appear, labelled SIM).

### Bazaar Caller (@techbazaarcaller)

Chat is discovery only; it never places a call from chat.

1. What do you do?
2. Do you call people?
3. Can you approve a purchase for me?
4. Who can ask you to place a call?
5. Where does the approval code go?
6. Will you charge my card?
7. How many calls do you make per purchase?
8. Can you call me right now?
9. What happens if I do not answer?
10. Is this a real phone call?
11. Which agent should I talk to for buying a GPU?
12. Can I skip the call?

### Market Pulse (@techbazaarpulse)

Trend questions work for the parts in the seller catalog.

1. How is the RTX 5070 Ti trending?
2. How is the RTX 4070 Super 12GB trending?
3. How is the RX 7800 XT trending?
4. How is the PSU 750W trending?
5. How is the PSU 850W trending?
6. Help
7. What can you tell me about the RTX 5070 Ti this month?
8. Why does seller_3 keep losing? (answered only to seller 3's own agent unless `PULSE_SELLER_CHAT=open`)
9. Why does seller_4 keep losing?
10. Why does seller_5 keep losing?
11. How many sellers of the RTX 5070 Ti are CRS verified?
12. Can you buy a GPU for me? (it says it cannot)

Lines say SIM until Tiger Data holds real rounds; that is correct.

## 5. Evidence

- [ ] A list of ASI:One conversation links per agent, 10 or more each.
- [ ] Tick off #383 item 7 and comment the links on the issue.
