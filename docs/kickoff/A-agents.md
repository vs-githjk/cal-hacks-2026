# Lane A: Agents and ASI:One (Fetch.ai, Claude, ownership memory, goals)

**Owner: Abhinav.** Paste 00-shared.md first, then this. You own `agents/`.

## SETUP (do this first)
1. Your branch is `lane-a-agents`. Clone and switch (if the branch does not exist yet, create it with `git checkout -b lane-a-agents`): `git clone https://github.com/vs-githjk/cal-hacks-2026 && cd cal-hacks-2026 && git checkout lane-a-agents && git pull origin main`
2. Copy `.env.example` to `.env` and fill only the keys this lane needs: ANTHROPIC_API_KEY, AGENTVERSE_API_KEY, ASI1_API_KEY, CRS_API_KEY, SPACETIMEDB_URI, STRIPE_SECRET_KEY (agent side of the Payment Protocol test). Ask Vidyut for values; never paste a key in chat, a doc or a commit, and never commit `.env`.
3. You own `agents/`. Touch other lanes' folders only through `contracts/` (log changes in `a new file in docs/changes/ (`<HHMM>-<lane>-<topic>.md`)`).
4. Read `docs/kickoff/00-shared.md`, then this file.
5. Open a PR to main per finished item, small and often. Never add Co-Authored-By.
6. Details live in `docs/`, `contracts/` and the hub page: https://claude.ai/artifact/Hjrg6QgJ8FgdmkoEAaLCeU

## Mission

The buyer's whole flow runs inside an ASI:One conversation: the agent takes a goal, remembers what the buyer owns, hunts through sealed bids, and an advocate argues for the buyer with a source on every warning. You carry beats 1 and 2 (set a goal; sellers bid and the advocate vetoes a trap) and the agent side of beats 4 and 5. Planned load: 10.25 h to Sat 10:00, 14.0 h to Sun 03:00 (24.25 h total, an equal share with the other lanes). There is no spare time on your critical path, so the slip ladder minimums below are mandatory. If you cannot finish an item, pass it back in the team chat and it moves to whoever is ahead.

## Fetch.ai hard requirements (you own these)

From Fetch.ai's Cal Hacks hackpack: register at least one agent on Agentverse; implement the Agent Chat Protocol; be discoverable and usable through ASI:One; meaningful tool use or multi-agent orchestration; the primary workflow completes inside ASI:One; public GitHub repo with run instructions; README lists every agent's name and address plus the two badges (innovationlab, hackathon); 3 to 5 minute demo video (Vidyut makes it). Bonus: multi-agent collaboration, Payment Protocol with a credible monetization model, ASI Interactive Cards (carousel, detail, review; MetadataContent with card_protocol_version "1"), recovery from failed tool calls, real-time data. Register about 6 agents (buyer, advocate, Shield client, seller gateway, two named sellers); run the rest as a labelled fleet. Host agents on Agentverse or a cloud VM, never a laptop.

## BUILD ORDER TO SAT 10:00 (10.25 h; start Fri 21:45)

Take the rest of Fri 21:30 to 21:45 to read the contracts and post OwnedPart and Goal proposals in a new file in docs/changes/ (`<HHMM>-<lane>-<topic>.md`) (frozen Fri 22:30).

1. **a1 Buyer uAgent, ASI:One door, web chat fallback, ownership memory. 3.0 h, done by Sat 00:45.** Chat Protocol (`uagents_core.contrib.protocols.chat`), registered on Agentverse. A message with a goal and specs becomes a Need and a Goal row on Vedant's screen. OwnedPart store: "I already own a 750 W PSU and a mid-tower with 330 mm GPU clearance" becomes entries; the Need drops or flags owned lines and the card says "you already own X (your note, time)". Rules: never re-buy unless asked; cite the entry; a stated rule only for "how long it will last", never a guess; conflicts (DDR4 kit, DDR5 board) go to Anoop's fit checker. The local web chat fallback is rehearsed too. Done-check: a teammate types the goal in ASI:One and the Goal row appears; a unit test and one ASI:One transcript show the PSU line skipped with the entry cited.
2. **a2 Advocate with closed schema, veto, cited reason. 2.0 h, done by Sat 02:45.** Claude with a closed output schema (never free text into the money path). AdvocateCard from: fit by Anoop's code (socket, length, PSU wattage; the model never decides fit), condition and price claims from the claim-check Actor against the live page, recalls via the CPSC API, seller record. At most 3 warnings, each with a `source_url`. It can veto the cheapest bid, holds its ground when pushed, and never sees the fee. Mock Anoop's checker and Actor until they land. Done-check: the AdvocateCard JSON for the vetoed bid has a `source_url` on every warning, and the same input returns the same fit verdict.
3. **a3 Three seller agents and the bid protocol. 2.0 h, done by Sat 04:45.** Every seller is a Fetch.ai uAgent on Agentverse (fully agentic). Three named seller agents bid in Vedant's sealed round from Anoop's mirrors, never below the floor (the reducer enforces it). Prices come from policy code; Claude only writes the persona's line. Every bid carries an origin badge (MIRROR with listing URL, SIM) and a `source`. Done-check: a round with 3 bids where all three carry origin and listing links, and a below-floor bid is rejected in a test.
4. **a4 Goal hunt loop and step events. 1.5 h, done by Sat 06:15.** Loop over Vedant's Goal state machine: hunt, bid in, veto, progress; emit one event per class to the feed, and the ASI:One message channel (0.5 h of this). Re-read the price just before a call (quote TTL 10 min; over 2 percent restarts the card). If no real seller bids, buy the best public listing and say so on the card (Ruling 12). Done-check: set a goal, see "bid in", "veto", "progress to goal" arrive in the feed and one ASI:One message, throttled.
5. **a5 Payment Protocol over Stripe, agent side. 1.0 h, done by Sat 07:15.** `uagents_core.contrib.protocols.payment`: seller sends RequestPayment, buyer sends CommitPayment only with an approval row for the same mandate hash, then Anoop's merchant simulator and Stripe test charge run, seller sends CompletePayment. Done-check: CommitPayment appears only with an approval (test), both on the happy path and with a replayed mandate that fails.
6. **a6 CRS gate with cache. 0.75 h, done by Sat 08:00.** Call the CRS sandbox for 3 seeded business sellers, take the band only, cache the response; show "cached from CRS sandbox at HH:MM" if the live call fails. Consent card text. One seller greyed out with the reason. Wording: business sellers, sandbox test identities, a verified signal only. Done-check: one seller shows greyed in Vedant's screen with its reason; a test proves no CRS field reaches a buyer or seller message.
7. **08:00 to 10:00 (slack):** register the 6 agents, fill the README table (names, addresses, badges), run once from a cloud-hosted agent, a recovery message when a tool call fails, rehearse beats 1 and 2 with Vidyut. Done-check: one run from a fresh ASI:One session, no laptop agent.

## THEN TO SUN 03:00 (14.0 h; clock times are targets)

Sat 10:00 to 11:30: fold in sponsor and judge feedback (inside a13 hours). Deferred items start only after the Sat 14:00 gate is green.

1. **a10 Advocate answer endpoint for the call. 1.0 h, Sat 10:00 to 11:00.** Vidyut's call asks "why not the cheaper one?"; the endpoint answers from the advocate's closed-schema reason plus its source label, never from seller text. (For the Sat 10:00 talk, the call reads the cited reason from the AdvocateCard by code.) Done-check: the call returns the cited reason in under 2 s; a test with injected seller text proves it is not echoed.
2. **a14 Publish the claim-check Actor to the Apify Store. 1.0 h, by Sat 12:00.** Anoop builds it (c3), you publish. Done-check: the Store URL, a dry-run log.
3. **a7 Seller learning. 2.0 h, by Sat 14:00 (gate Sat 22:00).** From a LossReport, update a small strategy record (price step, bundle, delivery promise, condition disclosure; never the listing's condition field; never below the floor), and Claude writes the owner a one-line "what to change". Bounds are stated in code. Done-check: a seller that lost on price bids differently in round 2, the diff is deterministic and replayable from one loss report, and it cites the report.
4. **a8 Open seller protocol, one outside agent, second caller of Shield. 2.0 h, by Sat 16:00 (gate Sat 18:00).** The protocol so any Agentverse agent can register and bid (verified by `/verify-agent`). One outside agent bids (another team or the Fetch booth; Vidyut asks), tagged LIVE. One tiny external script or that agent calls Shield, so the demo shows an app that is not ours being protected. Done-check: an agent not run by us shows a LIVE bid, or a registered stub tagged MIRROR.
5. **a9 Shield `/verify-agent`. 2.0 h, by Sat 18:00.** Checks an Agentverse address, a TAP signature on the request and the registered seller record; returns a trust band. Without this it is a regex endpoint. Plug into Vidyut's Shield core. Done-check: a forged agent address returns a low band; a valid one a high band, both in tests.
6. **a11 Build goal composite. 2.0 h, by Sat 20:00 (gate Sat 20:00).** A build goal is a composite of part goals solved greedily with the fit checker, never above the sum of the caps. Demo on 3 parts (GPU, PSU, case). Done-check: a scripted 3-part build resolves within the cap and a part that does not fit is refused with the reason.
7. **a15 Sim clock for the time machine. 1.5 h, by Sat 21:30.** Fast-forward Anoop's recorded price feed, labelled SIM with the recorded date range. Done-check: a 3-day hunt replays in under 60 seconds with every step event.
8. **a13 Bug fixing and rehearsal. 2.5 h, Sat 21:30 to Sun 03:00 rolling.** Beats 1, 2, 4 and 5 agent paths, edge cases, README agent table kept honest.

## Slip ladder minimum forms (your items)

- Open seller protocol (Sat 18:00): the protocol and a registered stub agent tagged MIRROR; an outside bid only if one arrives.
- Seller learning trend (Sat 22:00): one deterministic strategy diff from one loss report, no trend claim.
- Build goal (Sat 20:00): scripted 3-part build solved by the fit checker, labelled.
- Shield `/verify-agent` stays real; only the registered-record check may shrink to a seeded table.

## What you get and hand over

- **From B (Vedant):** rounds, bids, Goal state machine and reservation ledger, LossReport (banded), the feed that carries your events, the screen that shows your cards and the CRS greyed-out seller.
- **From C (Anoop):** SpecCards with attrs, the fit checker (pure function, mock the same I/O now), mirrored offers with snapshot ids, the claim-check Actor, the recorded price feed, the merchant simulator.
- **From D (Vidyut):** Mandate and approval rows (your CommitPayment waits on them), Shield `/screen`, the call that consumes your a10 endpoint.
- **To B:** Need and Goal rows, bids with origin, AdvocateCard JSON, strategy diffs and "what to change" lines.
- **To C:** your a7 strategy for the wind tunnel runner (needed by Sat 14:00); `/verify-agent` for the Shield docs.
- **To D:** the advocate answer endpoint (a10), the outside agent address, CommitPayment.

## Sponsor hard requirements you own

Fetch.ai (list above, plus the agent table and two badges in the README). Apify Store publish of the claim-check Actor (a14, with Anoop). CRS gate (a6). Anthropic: Claude is the advocate with a closed schema; the README says where it could go wrong (our scoreboard shows it).

## Sun 03:00 to 09:00

Two hours on call for fixes, then sleep in shift (one lane at a time). Anoop runs integration; take his merge order.
