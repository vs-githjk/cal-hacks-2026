# README corrections for the main session

Written by night run 2, task T2, fix round 1 (Sat Oct 24, about 03:10 PDT). README.md is not edited on this branch (plan T2: the main session is rewriting it on main). Apply each block below to the new README, then check it against the Guidance section at the end. Every number is copied from the results file its row names; every state is checked against the code on `lane-d-night2`.

Rulings the main session should confirm: (1) the Bright Data label is "in progress" and Tiger is "planned, not built" until night tasks T6 and T13 land (flip to LIVE only then); (2) the honesty sentence below stays in the top 24 lines.

## 1. Top of the README

Keep this exact sentence in the first 24 lines:

> Store prices are real dated mirrors; the bidding agents are ours (SIM) until a shop runs the Seller Kit.

Replace "Seller agents learn from every loss, and Bazaar Shield, our security API, blocks agents that try to cheat." with:

> A refereed arena for agent commerce. Seller agents adjust after a loss (a SIM stand-in today), and Bazaar Shield, our security API, is scored in the open: blocked X of Y on a named corpus, never "secure" (see Numbers).

Replace the stale "Status, Fri Oct 23, about 21:45 PDT" note with the current date and: "This README says what is built and labels the rest. A piece counts as working only when the Status table says built and names its code."

Add the demo order after it:

> **The demo order:** an RTX 5070 Ti that fits a 305 mm case, under $1,300. The winner is the ASUS Prime RTX 5070 Ti OC Edition (304 mm, maker spec) at Best Buy, $1,299.99 before sales tax, shipping: not captured (a MIRROR listing, bid by a SIM seller; proof: [demo/tests/test_demo_winner.py](demo/tests/test_demo_winner.py)). Cards that do not fit, or whose fit we cannot confirm, are vetoed or lose, with a source.

Remove every "$800" goal; the goal is under $1,300 everywhere.

## 2. Sponsor technology rows (wording)

| Row | Replace with |
|---|---|
| Fetch.ai, uAgents (README sponsor table, the whole-request claim) | "Every agent is a uAgent registered on Agentverse with a mailbox. The buyer's goal is typed in ASI:One and replies are seen there; the rest of the request (bids, veto, approval, payment) does not complete inside an ASI:One chat today and checkout is not exercised ([evidence](agents/ISSUE14_EVIDENCE.md))." Depth: Core, built, checkout not exercised. These are the overclaims in the original rows, for Abhinav's #95. |
| Fetch.ai, Payment Protocol, Interactive Cards | "Payment Protocol checkout is planned, not built end to end. Interactive Cards are planned, not built; a plain-text fallback (numbered bids, reply `APPROVE <id>`) is what runs." Drop "appear as cards" and "Core". |
| Bright Data | "A second, dated price source. In progress: key set, one smoke call passed Sat 02:55 (agent-board); the integration code is night task T6 and not on this branch, where [data/baselines/brightdata.py](data/baselines/brightdata.py) is still a stub that raises not configured. Nothing in the demo uses it." State: In progress. |
| CRS | "Identity and fraud check on business sellers. Planned, not built: there is no CRS code on this branch; it goes through Abhinav's client (#121, #128)." State: Planned. |
| Tiger Data (MLH) | "Time series behind dated savings and the learning curve. Planned, not built: key set and a connection checked Sat 02:53, no code until night task T13." State: Planned. Do not call it live. |
| Armadin | Add "The 'Hack the market' console is planned, not built." |
| Spacetime | Add "The 3D floor is planned, not built (no three.js in web/package.json)." |
| Anthropic | "The advocate is code ([agents/advocate/checks.py](agents/advocate/checks.py)), not a model. Claude is optional: a seller's one-line persona and Shield's ambiguous-case classifier (off by default)." Also remove "Claude-based" for the advocate in docs/ARCHITECTURE.md line 112. |

Also: the Lot Wall, persona voices, the receiving-check photos and the seller demand dashboard are planned, not built; say so wherever they appear (Team and lanes, Roadmap, Repo layout, Invariants 4 and 7).

## 3. Status (replace the whole section)

## Status

Updated with every merge. States: **planned**, **in progress**, **built** (the Code column names the files).

| Piece | State | Code |
|---|---|---|
| Contracts (JSON schemas) | built, v1 | `contracts/` |
| Market rules (sealing, scoring, split optimizer, outcomes) and the SpacetimeDB module | built | `market/rules`, `market/spacetimedb` |
| Buyer, advocate, seller and Shield-client agents on Agentverse | built: registered with a mailbox; replies seen in ASI:One; checkout not exercised ([evidence](agents/ISSUE14_EVIDENCE.md)) | `agents/buyer`, `agents/advocate`, `agents/sellers` |
| Ownership memory | built for the demo goal (a scripted SIM rig) | `demo/goal.py` |
| Seller bids from Apify mirrors | built in the demo runner (MIRROR listings, SIM bidders); the Agentverse sellers use SIM listings | `demo/sellers.py`, `data/mirror` |
| Fit checker | built | `data/fit_checker` |
| Quality advocate with cited warnings | built as code, not a model; recalls and seller records are SIM fixtures | `agents/advocate/checks.py` |
| Claim-check Actor | built | `data/claim_check` |
| Shield screen, verify-agent, verify-mandate, check-claim | built | `shield/api.py`, `shield/product.py` |
| Shield signed verdict receipts and adaptive attack set | planned | none yet |
| TAP-style signing and our merchant simulator | built | `pay/tap.py`, `pay/merchant_sim.py` |
| Allowance and the approval judge | built | `pay/approval.py` |
| Cartesia approval call client | built; a rehearsed live call is not recorded in this repo | `pay/voice_cartesia.py` |
| Stripe test-mode charge | built in the runner (SIM stub by default, one real test charge with `--stripe`); through the Payment Protocol: not exercised | `demo/approval_flow.py` |
| Hyphenate IT buyer purchasing | built | `hyphenate/` |
| Wind tunnel | built, SIM, no headline lift yet | `sim/wind_tunnel.py` |
| Bright Data price source | in progress: key set, one smoke call passed Sat 02:55 (agent-board); integration code is night task T6 and not on this branch, where the file is still a stub; LIVE only when T6 lands | `data/baselines/brightdata.py` |
| CRS seller stability check | planned | none yet |
| Tiger Data time series | planned: key set, connection checked Sat 02:53 (agent-board); no code until night task T13 | none yet |
| Seller demand and trend dashboard | planned | none yet |
| "Hack the market" console | planned | none yet |
| 3D floor | planned | none yet |
| Lot Wall (many orders pooled) | planned | none yet |
| Visa Intelligent Commerce adapter | planned, needs sandbox access | none yet |

## 4. Numbers (replace "Numbers we will report")

## Numbers we report

Every number here is copied from a results file named in its row, with the date the file gives. Sets the rules were written against are marked in-sample. We do not report research time, incompatibility rate or return rate: no source was found. Results that show no effect are reported too.

| Number | Set and honest reading | Result | Source | Date |
|---|---|---|---|---|
| Shield, attacks stopped | dev and dev2, in-sample (rules were written looking at them) | 30 of 30 and 30 of 30 | `shield/corpus/RESULTS.md` | 2026-10-23 |
| Shield, attacks stopped | frozen probe, an upper bound (the author had read it) | 6 of 10 (60.0%) | `shield/corpus/RESULTS.md` | 2026-10-23 |
| Shield, attacks stopped | post-freeze check, run once, not tuned: our best guess of real recall | 6 of 12 (50.0%) | `shield/corpus/RESULTS.md` | 2026-10-23 |
| Shield, clean controls wrongly stopped | dev and dev2 controls | 0 of 10 and 0 of 15 | `shield/corpus/RESULTS.md` | 2026-10-23 |
| Shield, held-out set in the wind tunnel run | 20 attacks, 12 stopped (60%); 2 false blocks on clean rows | 60% | `sim/RESULTS-2026-10-24-b48x3.md` | 2026-10-24 |
| Fit checker, decided builds correct | full frozen set of 44 builds, specs partly unconfirmed, tuned on once: not held out | 42 of 43 | `data/RESULTS.md` | 2026-10-23 |
| Fit checker, decided builds correct | the 12 builds whose specs we confirmed on maker pages | 12 of 12 | `data/RESULTS.md` | 2026-10-23 |
| Hyphenate, planted errors caught | blind run before any fix; 5 of 7 clean cases passed, 2 false flags | 26 of 27 | `hyphenate/RESULTS-blind.md` | 2026-10-24 |
| Wind tunnel lift | SIM. The learner beats the field-median control on 1 of 4 held-out archetypes and the gate needs 2: no headline lift | 1 of 4 | `sim/RESULTS-2026-10-24-b48x3.md` | 2026-10-24 |
| Real store asks for an RTX 5070 Ti | MIRROR, 11 in stock or stock unknown, lowest $1,199.99, median $1,299.99, highest $1,489.00; median is +48% over a 5-sale mixed-condition eBay median (one day, not a markup, never quote it as one) | $1,299.99 | `data/RESULTS.md` | 2026-10-24 |

After the Hyphenate fixes the same file reports 27/27 planted and 7/7 clean, but three of those cases are no longer blind; quote the first-run line. Advocate precision and recall, Shield latency on the keyed API and the Seller Kit are not measured yet.

The +48% clause carries the caveat from `data/RESULTS.md`: the baseline is 5 eBay sales from one day in mixed condition; it is not a markup and must not be quoted as one.

## 5. Cartesia section (new, also in docs/SPONSORS.md)

## Cartesia: the approval call

Voice is the trust step: above the allowance, a call asks for a one-time word-pair code that appears only on the buyer's screen.

**Features used.** A Cartesia managed agent that only talks; outbound calls (`POST /agents/calls`); dynamic variables (`buyer_name`, `deal_script`, `why_answer`); the call transcript (`GET /agents/calls/{id}`). Code: [pay/voice_cartesia.py](pay/voice_cartesia.py).

**What the voice does and does not decide.** The agent reads a script that code fills from the mandate (amount and payee), answers "why not the cheaper one?" from the advocate's closed-schema reason, asks for the code and repeats what it heard. It never decides. Our code reads the transcript and feeds every buyer utterance to the approval judge in [pay/approval.py](pay/approval.py): it approves only on the exact word pair plus the word "approve", and silence, a hang-up, voicemail, a failed dial, a timeout or a missing transcript all deny. The judge, not the call, is what the tests cover ([pay/tests/test_approval.py](pay/tests/test_approval.py), [pay/VOICE_ATTACKS.md](pay/VOICE_ATTACKS.md), 2026-10-24: 9 of 10 attack cases denied on the first run; 10 of 10 after one fix, v04 no longer blind).

**Setup.** Env names (values never printed): `CARTESIA_API_KEY`, `CARTESIA_AGENT_ID`, `APPROVAL_CALL_TO` (the only number ever dialed). Then `python3 -m pay.voice_cartesia --dry-run --env-file /abs/path/.env` prints the variables with no network, `--check` is a read-only look at the agent, and `--demo` places one real call. Details: [pay/README.md](pay/README.md).

**Known limits.**
- A noisy room can make the speech-to-text miss the code. We have not measured a noise level; the answer to a miss is the typed fallback, which goes through the same judge and is labelled typed.
- 3 tries per mandate, shared by voice and typed, then the mandate is denied and needs a new one. A failed try starts a 30 second cooldown.
- A spoken different amount ("approve nine hundred dollars") is caught; not every phrasing is ("approve nine fifty" still passes). The real money control is the signed mandate hash, which a call cannot change.
- Cartesia does not document how long after a call ends the transcript is complete, or a call-cancel endpoint, so a wait timeout denies and the call may still be ringing.
- The call is a phone call to one registered number. An in-browser Cartesia call is planned, not built; the typed card is the fallback today.

## 6. Real vs simulated (changes to the table)

The two rows that change in the README table are below; the full working copy is docs/REAL_VS_SIMULATED.md.

- Price history and baseline: "MIRROR or SIM. Dated sources where they work; a labelled seeded series where they do not. Bright Data is in progress (key set, one smoke call passed Sat 02:55; integration code is night task T6, not on this branch)."
- CRS seller stability: "planned, not built. No CRS code on this branch; it goes through Abhinav's client (#121, #128)."

## 7. Guidance: checks the README should keep passing

The old `scripts/tests/test_readme_honesty.py` pinned these on README.md; it was renamed to `scripts/tests/test_docs_honesty.py` and now covers only the three docs. If the main session wants them on the README, keep them as a test on main:

- every line naming Bright Data, CRS, Tiger, the 3D floor, "Hack the market", Interactive Cards or Claude links an existing repo file or says planned, not built, in progress or not configured;
- the Numbers section quotes only numbers found in the results file named in the row, each row dated, and includes the "no headline lift" result;
- the Status table header is exactly Piece, State, Code; a planned row names no existing file; a built row names only existing files;
- one goal price: "under $1,300", "$1,299.99", "before sales tax", "shipping: not captured", no "$800";
- the honesty sentence from block 1 in the top 24 lines, and a Cartesia section with Features used, Setup, Known limits, noisy room, 3 tries, `pay/approval.py` and `pay/voice_cartesia.py`.
