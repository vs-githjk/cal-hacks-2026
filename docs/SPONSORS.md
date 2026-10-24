# Sponsor map: every sponsor is a main sponsor (Sat Oct 24, 03:00 PDT; each entry says what is built, with proof, and what is planned, not built)

Product: Tech Bazaar. Security API: Bazaar Shield. Each sponsor carries a Proof line that names the file, test or results file; a sponsor with no code says planned, not built. Hard requirements come from plan/submission.md and the hacker portal; re-read the Live Site at kickoff for any track text marked not yet read.

Every sponsor below is a main sponsor and gets the same depth: each carries something in the loop, has a demo moment, a lane that owns it, and hard requirements we must meet. Where a sponsor's track text is not yet read, the entry says so; Vidyut or the owner re-reads the Live Site at kickoff and posts the exact text on the board.

**Fetch.ai** (Lane A)
- Carries: the buyer, advocate, three sellers and a Shield client are uAgents on Agentverse; ASI:One is the buyer's front door; the open seller protocol (an outside agent registers and bids) and Payment Protocol checkout are planned, not built end to end; Interactive Cards are planned, not built (a plain-text fallback is what runs).
- Proof: `agents/README.md`, `agents/ISSUE14_EVIDENCE.md` (replies seen in ASI:One; checkout not exercised).
- Breaks without it: no seller can join, the round opens with zero bidders, and the outside-agent proof is gone.
- Demo moment: beat 1 (the goal typed in ASI:One) and beat 2 (an outside agent's LIVE bid).
- Hard requirements: register at least one agent on Agentverse; Agent Chat Protocol; discoverable and usable in ASI:One; tool use or multi-agent orchestration; the primary workflow completes inside an ASI:One chat; public GitHub repo with run instructions; README lists every agent's name and address plus the innovationlab and hackathon badges; ASI:One Submission Agent registration; 3 to 5 minute demo video (required).

**Visa** (Lane D signing, Lane C merchant simulator)
- Carries: TAP-style signing on buyer-agent requests, verified by our own merchant simulator, carrying the mandate hash; payment is a Stripe test-mode charge on a Visa test card (SIM stub by default, one real test charge with `--stripe`); a Visa Intelligent Commerce adapter is planned, not built, and swaps in only if Visa grants sandbox access.
- Proof: `pay/tap.py`, `pay/merchant_sim.py`, `pay/tests/test_tap.py`, `demo/approval_flow.py`.
- Breaks without it: our merchant simulator rejects the unsigned request, and the replay has nothing to fail.
- Demo moment: beat 4, a replayed or altered mandate fails on screen.
- Hard requirements: Reimagining Shopping judging criteria are Innovation 25, UX 25, Technical Execution 20, Commerce Impact 15, Trust and Responsibility 15 (no Visa API requirement found; the Visa API is not required). Never say "Visa settles". The README states exactly what is live and what is an adapter.

**Apify** (Lane C build, Lane A Store publish; credits in hand)
- Carries: seller listings mirrored from real stores, and our own claim-check Actor that the advocate cites in every veto.
- Proof: `data/mirror/snapshots/`, `data/claim_check/actor/README.md` (Store link), `data/RESULTS.md`.
- Breaks without it: the veto has no source link ("seems risky" is not the beat).
- Demo moment: beat 2, the veto shows the live page link.
- Hard requirements: Apify used in a meaningful way (Best Use of Apify); Best Actor asks for an Actor built for this event, so the claim-check Actor is published to the Apify Store (a14) with cost per run documented.

**Bright Data** (Lane C, built, env-gated, not run live)
- Carries (built, env-gated, not run live: no key in the run): a dated second price source through the Scraper API, live only when `BRIGHT_DATA_API_KEY` is set, plus beat 4's price re-check of the winner and a Google Shopping lead finder (`data/baselines/brightdata_discover.py`). One raw smoke call passed Sat 02:55 (agent-board); the code has not made a live call. Any spend needs Vidyut's OK first.
- Proof: `data/baselines/brightdata.py`, its tests in `data/tests/test_brightdata.py`, and [docs/changes/0330-D-brightdata.md](changes/0330-D-brightdata.md); no live result recorded.
- Breaks without it: the savings tile loses its second source and reads "unverified".
- Demo moment: the savings tile with two dated sources (shown with the beat 4 receipt).
- Hard requirements (Bright Data is in progress): track text not yet read (prize text is in the guide or "coming soon"); owner posts it at kickoff. Meanwhile: Bright Data used for a real, named step (the second baseline and one blocked page), recorded in data/README.md.

**CRS** (built, env-gated, not run live; Lane A adapter, Lane D payee gate; credits in hand; Lane C supplies sandbox test identities)
- Carries (built, env-gated, not run live: no key in the run): identity and fraud check on business sellers. Sandbox test identities only, band output, consent card; individual used-part sellers are not credit-checked (FCRA caution). The adapter is main's `agents/crs.py`; `pay/crs_gate.py` refuses a business payee without a fresh verified check, and nothing calls it before the charge yet.
- Proof: `pay/crs_gate.py`, `pay/tests/test_crs_gate.py`, [docs/changes/0400-D-crs-payee.md](changes/0400-D-crs-payee.md); no live check recorded.
- Breaks without it: unverified sellers bid, and the greyed-out seller beat disappears.
- Demo moment: one business seller's bid is greyed out with the reason, inside beat 2.
- Hard requirements (CRS is planned, not built): the CRS sandbox shown live (calhacks.crscreditapi.com or the CRS MCP server), provided test identities only; Best Identity and Fraud Innovation asks for protecting people or businesses from fraud; Best Financial AI Agent asks for an agent doing real work with CRS data through the API or MCP.

**Armadin** (Lane D core, Lane C product layer, Lane A `/verify-agent`)
- Carries: Bazaar Shield: `/v1/shield/screen`, `/verify-agent`, `/verify-mandate`, `/v1/check-claim`, rules as data, the attack corpus, a key and a `shield-bench` for any attack file. Signed verdict receipts are planned, not built.
- Proof: `shield/api.py`, `shield/product.py`, `shield/bench.py`, `shield/corpus/RESULTS.md` (6 of 12 on the post-freeze check, 2026-10-23).
- Breaks without it: the injected listing reaches the advocate, a payee swap goes through, and the block-rate tile reads zero.
- Demo moment: beat 3, Shield blocks an injected listing live. The "Hack the market" console is planned, not built; judges can send attacks to the API or the bench.
- Hard requirements: Best Security Hack, sponsored by Armadin (posted prize: headphones, possibly hacking tools; not cash). Report "blocked X of Y on this corpus" per set (dev, held-out; the adaptive set is planned, not built), never "secure"; hand them a key and the bench.

**Cartesia** (Lane D core, Lane B screens, Lane C Photon spike)
- Carries: the two-way call: the buyer asks "why not the cheaper one?", the advocate answers aloud, the buyer speaks the word-pair code, the amount is read back. Built as a Cartesia managed agent that places a phone call; our code judges the transcript. An in-browser Cartesia call and Photon SIP are planned, not built; the typed card is the fallback.
- Proof: `pay/voice_cartesia.py`, `pay/approval.py`, `pay/VOICE_ATTACKS.md`; features used, setup and known limits are in the Cartesia section below.
- Breaks without it: nothing above the allowance can be approved, so the first buy stalls.
- Demo moment: beat 4.
- Hard requirements: voice must be core to the product, not a feature added for the demo; make clear what Cartesia contributes; submit a working demo, a 2-minute demo-first presentation and a short README with setup, the Cartesia features used and known limitations.

**Hyphenate** (Lane B pages, Lane C `three_way_match`)
- Carries: the IT buyer's procurement seats as an autonomous system: PO number, the requester cannot approve, three-way match (PO, listing claim and page, delivery check), credit memo on a failed receiving check, an audit page where every call traces to its data, rule or person.
- Breaks without it: the IT buyer view loses its PO and audit page; the core loop is unaffected.
- Demo moment: a seeded IT order showing the PO, a failed match writing a credit memo, and the audit trail (with the simulated company around it labelled SIM).
- Hard requirements (Finance track): an autonomous system for a few seats in one corner of a finance team plus the simulated company around it; a live demo running for real; a video that opens with the moment; one line on the seats it fills; proof of what is real, what is simulated and how you know. Nobody who requests a payment can approve it.

**Anthropic** (Lane A)
- Carries: optional Claude calls: a seller agent's one-line persona voice (falls back to a template without a key) and Shield's ambiguous-case classifier (off by default). The advocate is code, not a model. Claude writing sellers' "what to change" lines and generating attack variants is planned, not built.
- Proof: `agents/sellers/seller_agent.py`, `shield/classifier.py`.
- Breaks without it: nothing in the demo path; persona lines fall back to a template and the classifier stays off.
- Demo moment: none today; the veto reason comes from code and the "what to change" line is a SIM template.
- Hard requirements: track text not yet read; owner posts it at kickoff. The portal asks that you know where it could go wrong: our scoreboard and Honest limits section show where.

**Spacetime** (Lane B)
- Carries: the arena itself: sealed rounds, reducers that enforce the floor, ledger, goal states and approval-before-payment; the buyer and market screens subscribe to it. The 3D floor is planned, not built.
- Proof: `market/spacetimedb/`, `market/rules/`.
- Breaks without it: bids cannot be sealed or refereed, and the screens drift apart.
- Demo moment: two laptops show the same round at once (beats 1, 2 and 5).
- Hard requirements: Spacetime is the core real-time backend (live shared state, instant sync between agents and users, "AI systems coordinating in a persistent world state"), meaningfully used and not added on the side. README names the Python bridge as the single point of failure.

**Tiger Data** (MLH track, Lane C): built, env-gated, not run live (no key in the run). Connection checked Sat 02:53 (agent-board); schema, loader and store are `data/tiger/store.py`, `data/tiger/schema.sql` and `data/tiger/load.py` ([docs/changes/0500-D-tiger.md](changes/0500-D-tiger.md)), with no live load recorded. Time series behind dated savings and the learning curve; plain Postgres could do this, say so. Do not opt in on Devpost until a live load has run.

**Capital One (Nessie):** maybe, only if Capital One is present at the event. Not planned; no lane has time for it.

Hyphenate proof: `hyphenate/RESULTS-blind.md` (26 of 27 planted errors caught on the first blind run, 2026-10-24).

## Cartesia: the approval call

Voice is the trust step: above the allowance, a call asks for a one-time word-pair code that appears only on the buyer's screen.

**Features used.** A Cartesia managed agent that only talks; outbound calls (`POST /agents/calls`); dynamic variables (`buyer_name`, `deal_script`, `why_answer`); the call transcript (`GET /agents/calls/{id}`). Code: `pay/voice_cartesia.py`.

**What the voice does and does not decide.** The agent reads a script that code fills from the mandate (amount and payee), answers "why not the cheaper one?" from the advocate's closed-schema reason, asks for the code and repeats what it heard. It never decides. Our code reads the transcript and feeds every buyer utterance to the approval judge in `pay/approval.py`: it approves only on the exact word pair plus the word "approve", and silence, a hang-up, voicemail, a failed dial, a timeout or a missing transcript all deny. The judge, not the call, is what the tests cover (`pay/tests/test_approval.py`). Attack cases (`pay/VOICE_ATTACKS.md`, 2026-10-24): 9 of 10 denied on the first run; 10 of 10 after one fix (v04 no longer blind).

**Setup.** Env names (values never printed): `CARTESIA_API_KEY`, `CARTESIA_AGENT_ID`, `APPROVAL_CALL_TO` (the only number ever dialed). Then `python3 -m pay.voice_cartesia --dry-run --env-file /abs/path/.env` prints the variables with no network, `--check` is a read-only look at the agent, and `--demo` places one real call. Details: `pay/README.md`.

**Known limits.**
- A noisy room can make the speech-to-text miss the code. We have not measured a noise level; the answer to a miss is the typed fallback, which goes through the same judge and is labelled typed.
- 3 tries per mandate, shared by voice and typed, then the mandate is denied and needs a new one. A failed try starts a 30 second cooldown.
- A spoken different amount ("approve nine hundred dollars") is caught; not every phrasing is ("approve nine fifty" still passes). The real money control is the signed mandate hash, which a call cannot change.
- Cartesia does not document how long after a call ends the transcript is complete, or a call-cancel endpoint, so a wait timeout denies and the call may still be ringing.
- The call is a phone call to one registered number. An in-browser Cartesia call is planned, not built; the typed card is the fallback today. A rehearsed live call is not recorded in this repo.

**Phone for the call:** Photon SIP first (the team used it at LA Hacks and won its voice prize), with Cartesia over SIP. Anoop spikes it (decision Sat 09:00); the phone call (pay/voice_cartesia.py) is what runs today, the typed card is the fallback, and an in-browser Cartesia call is planned, not built. Do not buy Twilio before Photon is proven.

**Credits in hand: Apify and CRS.** CRS is planned, not built. Anything else that costs money (Twilio, more Bright Data credits beyond the in progress smoke calls; Stripe is test mode and free) needs Vidyut's OK first.

## MLH tracks and extras
| Track | Status | Owner |
|---|---|---|
| Snowflake | Deferred until after Sat 14:00, not dropped | C |
| Gemini | Deferred until after Sat 14:00; one honest model step only if it beats Claude (planned, not built) | C or A |
| GoDaddy Registry domain | Free add (MLH code, TO VERIFY for 2026) | Vidyut |
| MLH Commit Fellowship | Opt in on Devpost | Vidyut |
