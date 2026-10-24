# Sponsor map: every sponsor is a main sponsor (final, Fri night; matches docs/kickoff/00-shared.md and plan/idea-v2.md)

Product: Tech Bazaar. Security API: Bazaar Shield. Fill the proof (file, test or clip) as each piece lands, in a Proof line under each sponsor. Hard requirements come from plan/submission.md and the hacker portal; re-read the Live Site at kickoff for any track text marked not yet read.

Every sponsor below is a main sponsor and gets the same depth: each carries something in the loop, has a demo moment, a lane that owns it, and hard requirements we must meet. Where a sponsor's track text is not yet read, the entry says so; Vidyut or the owner re-reads the Live Site at kickoff and posts the exact text on the board.

**Fetch.ai** (Lane A)
- Carries: every buyer, advocate and seller agent is a uAgent on Agentverse (fully agentic); ASI:One is the buyer's front door; the open seller protocol lets an outside agent register and bid; Payment Protocol carries checkout; Interactive Cards show bids and the review.
- Breaks without it: no seller can join, the round opens with zero bidders, and the outside-agent proof is gone.
- Demo moment: beat 1 (the goal typed in ASI:One) and beat 2 (an outside agent's LIVE bid).
- Hard requirements: register at least one agent on Agentverse; Agent Chat Protocol; discoverable and usable in ASI:One; tool use or multi-agent orchestration; the primary workflow completes inside an ASI:One chat; public GitHub repo with run instructions; README lists every agent's name and address plus the innovationlab and hackathon badges; ASI:One Submission Agent registration; 3 to 5 minute demo video (required).

**Visa** (Lane D signing, Lane C merchant simulator)
- Carries: Trusted Agent Protocol signs every buyer-agent request and carries the mandate hash; payment is a Stripe test-mode charge on a Visa test card; a Visa Intelligent Commerce adapter swaps in only if Visa grants sandbox access.
- Breaks without it: our merchant simulator rejects the unsigned request, and the replay has nothing to fail.
- Demo moment: beat 4, a replayed or altered mandate fails on screen.
- Hard requirements: Reimagining Shopping judging criteria are Innovation 25, UX 25, Technical Execution 20, Commerce Impact 15, Trust and Responsibility 15 (no Visa API requirement found; the Visa API is not required). Never say "Visa settles". The README states exactly what is live and what is an adapter.

**Apify** (Lane C build, Lane A Store publish; credits in hand)
- Carries: seller listings mirrored from real stores, and our own claim-check Actor that the advocate cites in every veto.
- Breaks without it: the veto has no source link ("seems risky" is not the beat).
- Demo moment: beat 2, the veto shows the live page link.
- Hard requirements: Apify used in a meaningful way (Best Use of Apify); Best Actor asks for an Actor built for this event, so the claim-check Actor is published to the Apify Store (a14) with cost per run documented.

**Bright Data** (Lane C)
- Carries: pages behind anti-bot walls, SERP and Web Unlocker, and a dated second baseline price for the savings tile. Any spend needs Vidyut's OK first (a Newegg dataset is $250 minimum, reported).
- Breaks without it: the savings tile loses its second source and reads "unverified".
- Demo moment: the savings tile with two dated sources (shown with the beat 4 receipt).
- Hard requirements: track text not yet read (prize text is in the guide or "coming soon"); owner posts it at kickoff. Meanwhile: Bright Data used for a real, named step (the second baseline and one blocked page), recorded in data/README.md.

**CRS** (Lane A gate; credits in hand; Lane C supplies sandbox test identities)
- Carries: identity and fraud check on business sellers. Sandbox test identities only, band output, consent card; individual used-part sellers are not credit-checked (FCRA caution).
- Breaks without it: unverified sellers bid, and the greyed-out seller beat disappears.
- Demo moment: one business seller's bid is greyed out with the reason, inside beat 2.
- Hard requirements: the CRS sandbox shown live (calhacks.crscreditapi.com or the CRS MCP server), provided test identities only; Best Identity and Fraud Innovation asks for protecting people or businesses from fraud; Best Financial AI Agent asks for an agent doing real work with CRS data through the API or MCP.

**Armadin** (Lane D core, Lane C product layer, Lane A `/verify-agent`)
- Carries: Bazaar Shield: `/v1/shield/screen`, `/verify-agent`, `/check-claim`, `/verify-mandate`, signed verdict receipts, rules as data, the attack corpus, a key and a `shield-bench` for any attack swarm.
- Breaks without it: the injected listing reaches the advocate, a payee swap goes through, and the block-rate tile reads zero.
- Demo moment: beat 3, Shield blocks an injected listing live; judges attack it in the "Hack the market" console.
- Hard requirements: Best Security Hack, sponsored by Armadin (posted prize: headphones, possibly hacking tools; not cash). Report "blocked X of Y on this corpus" in three columns (dev, held-out, adaptive), never "secure"; hand them a key and the bench.

**Cartesia** (Lane D core, Lane B screens, Lane C Photon spike)
- Carries: the two-way call: the buyer asks "why not the cheaper one?", the advocate answers aloud, the buyer speaks the word-pair code, the amount is read back. Photon SIP first, in-browser call as default and fallback.
- Breaks without it: nothing above the allowance can be approved, so the first buy stalls.
- Demo moment: beat 4.
- Hard requirements: voice must be core to the product, not a feature added for the demo; make clear what Cartesia contributes; submit a working demo, a 2-minute demo-first presentation and a short README with setup, the Cartesia features used and known limitations.

**Hyphenate** (Lane B pages, Lane C `three_way_match`)
- Carries: the IT buyer's procurement seats as an autonomous system: PO number, the requester cannot approve, three-way match (PO, listing claim and page, delivery check), credit memo on a failed receiving check, an audit page where every call traces to its data, rule or person.
- Breaks without it: the IT buyer view loses its PO and audit page; the core loop is unaffected.
- Demo moment: a seeded IT order showing the PO, a failed match writing a credit memo, and the audit trail (with the simulated company around it labelled SIM).
- Hard requirements (Finance track): an autonomous system for a few seats in one corner of a finance team plus the simulated company around it; a live demo running for real; a video that opens with the moment; one line on the seats it fills; proof of what is real, what is simulated and how you know. Nobody who requests a payment can approve it.

**Anthropic** (Lane A)
- Carries: Claude is the advocate (closed output schema), writes sellers' "what to change" lines, powers Shield's ambiguous-case classifier, and generates hostile builder and attack variants.
- Breaks without it: no veto reasons, no seller notes, no attack variants.
- Demo moment: beat 2 (the veto reason) and beat 5 (the "what to change" line).
- Hard requirements: track text not yet read; owner posts it at kickoff. The portal asks that you know where it could go wrong: our scoreboard and Honest limits section show where.

**Spacetime** (Lane B)
- Carries: the arena itself: sealed rounds, reducers that enforce the floor, flat fee, ledger, goal states and approval-before-payment; every agent and screen shares one world; the floor and scoreboard subscribe to it. Fri 23:00 go or no-go (Convex fallback).
- Breaks without it: bids cannot be sealed or refereed, and the screens drift apart.
- Demo moment: two laptops show the same round at once (beats 1, 2 and 5).
- Hard requirements: Spacetime is the core real-time backend (live shared state, instant sync between agents and users, "AI systems coordinating in a persistent world state"), meaningfully used and not added on the side. README names the Python bridge as the single point of failure.

**Tiger Data** (MLH track, Lane C): time series behind dated savings and the learning curve; after Sat 14:00 only; plain Postgres could do this, say so. Slip form: plain queries.

**Capital One (Nessie):** maybe, only if Capital One is present at the event. Not planned; no lane has time for it.

Proof for every sponsor above: _to fill as built (file, test or clip)_.

**Phone for the call:** Photon SIP first (the team used it at LA Hacks and won its voice prize), with Cartesia over SIP. Anoop spikes it (decision Sat 09:00); the in-browser Cartesia call is the default and fallback. Do not buy Twilio before Photon is proven.

**Credits in hand: Apify and CRS.** Anything else that costs money (Bright Data, Twilio; Stripe is test mode and free) needs Vidyut's OK first.

## MLH tracks and extras
| Track | Status | Owner |
|---|---|---|
| Snowflake | Deferred until after Sat 14:00, not dropped | C |
| Gemini | Deferred until after Sat 14:00; one honest model step only if it beats Claude | C or A |
| GoDaddy Registry domain | Free add (MLH code, TO VERIFY for 2026) | Vidyut |
| MLH Commit Fellowship | Opt in on Devpost | Vidyut |
