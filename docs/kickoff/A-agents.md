# Lane A: Agents and ASI:One (Fetch.ai, Claude, CRS and Nessie reads)
Paste 00-shared.md first, then this.

You own agents/. Goal: the shopper's whole flow runs inside an ASI:One conversation.

Fetch.ai hard requirements (from their Cal Hacks hackpack): register at least one agent on Agentverse; implement the Agent Chat Protocol; be discoverable and usable through ASI:One; meaningful tool use or multi-agent orchestration; the primary workflow completes inside ASI:One; public GitHub repo with run instructions; README lists every agent's name and address plus the two badges (innovationlab, hackathon); 3 to 5 minute demo video. Bonus: multi-agent collaboration, Payment Protocol with a credible monetization model, ASI Interactive Cards, recovery from failed tool calls, real-time data.

Tasks in order:
1. Shopper agent (uAgents, Python) with the Chat Protocol (uagents_core.contrib.protocols.chat), registered on Agentverse, reachable from ASI:One. It turns a message into a Need and posts it to the market (Lane B contract).
2. Store agent template: reads a store's rules (floor price, allowed perks) and the mirrored catalog from Lane C, bids within rules, answers counter-offers. Spawn 10 to 20 with personas.
3. Devil's advocate agent (Claude via the Anthropic API): for each bid, builds an AdvocateCard from Lane C data (price history, reviews, fees), Shield claim checks, CRS affordability (via Lane D adapter) and Nessie accounts (via Lane C). It must cite a source for every warning and hold its ground when the shopper pushes back.
4. Interactive Cards: a carousel of verified bids, a detail card per bid with the advocate's warnings, a review card for approval (card_kind carousel, detail, review; MetadataContent with card_protocol_version "1").
5. Payment Protocol (uagents_core.contrib.protocols.payment): store agent sends RequestPayment, shopper agent sends CommitPayment only after the approval card; then Lane D charges the Visa card through Stripe test mode (or Link) and the store sends CompletePayment.
6. Recovery: retries and a clear message when a tool call fails.
Done when: a judge completes need, bids, advocate card, approval and payment inside ASI:One, and every agent message passed through Shield first.

## Latest direction additions
- The buyer is a restaurant agent: it reads the usage forecast from Lane C, turns it into a weekly Need (items with grade, pack size, quantity, delivery window), and asks the owner to approve or auto-approves within limits, always notifying the owner.
- The devil's advocate checks spec equivalence across suppliers, delivery promises, price against the market baseline, and the CRS stability signal from Lane D.

## Visa and quality update (Fri 20:20)
- The buyer agent runs the weekly cycle on its own schedule (forecast, request, auction, order) and only pings the owner for approvals or exceptions. Chat is not the product.
- The devil's advocate is now the Quality Advocate: need check (forecast and stock versus quantity, waste risk), quality check (spec match, shelf life versus delivery date, recalls, supplier quality record), price check (USDA baseline), stability (CRS signal). It can veto the cheapest bid when quality is worse, and must say why with sources.
