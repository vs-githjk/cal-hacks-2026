# Lane D: Trust, voice, Shield core, pitch (Visa TAP, Cartesia call, Armadin, evidence)

**Owner: Vidyut.** Paste 00-shared.md first, then this. You own the mandate and TAP signing (`pay/`), the hardened call core, Shield's core (`shield/`), the pitch and video, the interviews and real quotes, and the PR review gates.

## SETUP (do this first)
1. Your branch is `lane-d-pay-trust`. Clone and switch (if the branch does not exist yet, create it with `git checkout -b lane-d-pay-trust`): `git clone https://github.com/vs-githjk/cal-hacks-2026 && cd cal-hacks-2026 && git checkout lane-d-pay-trust && git pull origin main`
2. Copy `.env.example` to `.env` and fill only the keys this lane needs: ANTHROPIC_API_KEY (Shield classifier), CARTESIA_API_KEY, CARTESIA_AGENT_ID, VISA_TAP_PRIVATE_KEY_PATH, STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY; VISA_VIC_API_KEY only if Visa grants sandbox access; TWILIO_* only if Photon fails. Ask Vidyut for values; never paste a key in chat, a doc or a commit, and never commit `.env`.
3. You own `pay/` (mandate, TAP, call core) and `shield/` (core). Touch other lanes' folders only through `contracts/` (log changes in `a new file in docs/changes/ (`<HHMM>-<lane>-<topic>.md`)`).
4. Read `docs/kickoff/00-shared.md`, then this file.
5. Open a PR to main per finished item, small and often. Never add Co-Authored-By.
6. Details live in `docs/`, `contracts/` and the hub page: https://claude.ai/artifact/Hjrg6QgJ8FgdmkoEAaLCeU

## Mission

Money moves only after the buyer says yes on a call about one exact deal, and agents stay honest. You carry beat 4 (the two-way call approves above the allowance) and beat 3 (Shield blocks an injected listing live), and you earn the evidence that lifts the score: interviews, real quotes, the real purchase, the feedback round. Planned load: 11.0 h to Sat 10:00, 14.0 h to Sun 03:00 (25.0 h total, an equal share; watching the repo and the hub page is counted inside it, see d10). If you cannot finish an item, pass it back in the team chat and it moves to whoever is ahead. Lighter than before: the allowance reducer went to Vedant; the merchant simulator, Photon spike, hosted pages, held-out attacks and Shield's OpenAPI, keys and bench went to Anoop; `/verify-agent` and the advocate answer endpoint went to Abhinav.

## Hardened call design (build exactly this)

**Voice is never the credential.** The credential is a one-time code on the buyer's authenticated screen, spoken inside a call about one exact mandate. The model never decides "approve"; code does.
- **Code:** a two-word phrase from a list of phonetically distinct words (for example "amber falcon"), not digits. Single use, expires in 2 minutes, derived from the mandate hash plus a nonce. A replay against a new deal fails, shown on screen.
- **Flow:** the call opens with "I will only ask for the code on your screen, never a card number". It reads amount and payee from a code-filled template. The buyer can ask "why not the cheaper one?" (answered from the advocate's closed-schema reason and source label, never seller text). The buyer says the code; the system reads "Approving 1,119 dollars to Seller X. Say approve." Only the token "approve" within 10 seconds counts. Anything else, including silence, denies. Approval needs two tokens (code, then "approve"); denial needs any other sound. Two failed code tries: deny and notify. Low STT confidence counts as a mismatch.
- **Mandate** binds deal id, amount, payee, expiry and nonce (and the tier price reached for a lot). Stripe charge and TAP verification both check the hash. Idempotency key on the hash.
- **Phone path** calls only the number registered in a prior in-app step; the phone alone cannot approve because the code is only on the screen. Phone stays Tier 1 until Photon is proven.
- **Typed fallback:** the same code can be typed into the review card as a labelled fallback bound to the same mandate. Record the call as a backup clip.
- **Never** read seller text aloud; never parse the amount from speech.

## BUILD ORDER TO SAT 10:00 (11.0 h; start Fri 21:45)

1. **d1 Eight interviews tonight. 1.0 h, Fri 21:45 to 22:45 (finish by 23:00).** Hackers who built or upgraded a PC or bought a laptop or monitor in the last 12 months, and anyone who buys computers for a club, lab or team. Questions in 00-shared evidence plan. Write first name, school or role and the exact words, with permission, into docs/INTERVIEWS.md. Done-check: 8 entries (target 8), each with a quote and permission.
2. **d2 Mandate hash, TAP signing, replay failure. 3.0 h, done by Sat 01:45.** Mandate schema (log in a new file in docs/changes/ (`<HHMM>-<lane>-<topic>.md`) before Fri 22:30), hash over deal id, amount, payee, expiry, nonce; sign every buyer-agent request under Visa's Trusted Agent Protocol (HTTP Message Signatures, Visa and Cloudflare open spec); Anoop's merchant simulator verifies. A split order is several mandates, one per seller. Never "Visa settles". A Visa Intelligent Commerce adapter swaps in only if Visa grants sandbox access (README says what is live). Done-check: a signed request verifies at Anoop's simulator, a replayed one fails with the reason, tests first.
3. **d3 Hardened call core. 3.5 h, done by Sat 05:15.** The design above: word-pair code, echo, code-only intent, TTL, default deny, typed fallback, Cartesia in the browser. Test first: wrong code denies; "yes" without code denies; a code for deal A cannot approve deal B. Vedant's review card shows the code; Abhinav's a10 endpoint (Sat 10:00) answers "why"; until then the call reads the AdvocateCard's cited reason by code. Cartesia README: setup, features used, known limitations (carrier, latency, noisy rooms, in-browser fallback); demo-first, 2-minute presentation. Done-check: a recorded in-browser call where the buyer asks "why not the cheaper one?", says the code, hears the amount, says "approve", and a VoiceApproval row is stored; the test file passes.
4. **d4 Shield core. 3.5 h, done by Sat 08:45.** `POST /v1/shield/screen` and `/v1/shield/verify-mandate`, a stable verdict `{verdict: allow|quarantine|block, rule_ids[], severity, evidence_spans[], latency_ms, request_id, version}` (no free text from a model, so Shield cannot be prompt-injected into "allow"), signed verdict receipts (no payment without a receipt), 30 dev attack cases. Layered: cheap deterministic rules first (payee change, identity mismatch, known injection structure, encoded payloads), a Claude classifier only for ambiguous cases with a closed schema, timeout means fail closed (quarantine). Rules are files with ids. Logging stores hashes and rule ids, not bodies. Done-check: Anoop's injected page is quarantined with the rule shown; a payee swap is quarantined as "mandate mismatch"; no free-text field in the verdict.
5. **08:45 to 10:00 (slack):** Photon decision at 09:00 with Anoop; rehearse the five beats end to end; plan the 10:00 talk for each sponsor (what each sees, what breaks without it). Done-check: Vidyut runs the five beats once, labelled, without help.

## THEN TO SUN 03:00 (14.0 h; clock times are targets)

1. **d8 Sat 10:00 sponsor and judge feedback round. 2.0 h, Sat 10:00 to 12:00.** Fold feedback into the lane files by posting on the board; ask the Fetch booth to point an agent at the open seller protocol, and Armadin for any attack file for `shield-bench`.
2. **d5 Real quotes. 2.0 h, Sat 12:00 to 14:00.** One real seller quote (2 local PC shops or 3 used-part sellers: a quote, and "would you pay 3 percent, capped at $25, only on a verified sale?") and one IT buyer quote or written pilot interest ("would you try Team for your next refresh?"; ask how they would want to pay per refresh). Outward contact is your call. Done-check: one written answer from each, in INTERVIEWS.md with permission.
3. **d6 Real teammate purchase, approval, receiving check. 1.5 h, Sat 14:00 to 15:30 (gate Sat 18:00; needs your OK on the spend).** The arena picks a real low-cost part or peripheral for a teammate's real rig; the teammate approves on the call; they buy at the real seller (Stripe stays test mode: "the agent chose and you approved; the payment was by the teammate"); the receiving check runs on the real box and fills the real savings column even if the saving is $0. Slip form: the receiving check on a teammate photo of a part already owned, labelled demo.
4. **d9 Voice attack run. 1.0 h, Sat 15:30 to 16:30.** Run Anoop's 10 voice attack cases against d3 and fix what fails. Counted in the scoreboard as "voice". Done-check: 10 of 10 handled, results saved with date.
5. **d11 Photon wire-in. 1.0 h, Sat 16:30 to 17:30 (gate Sat 18:00), only if Anoop's spike is green.** Slip form: in-browser call.
6. **d7 Pitch, multiverse script, Armadin pitch, video. 3.5 h, Sat 17:30 to 21:00.** Storyboard approved by Sat 19:00; footage 21:00 to 23:00; rough cut by Sun 03:00. The pitch has one thesis and the five beats; the one-liner leads with the veto and the call. The multiverse stage line exactly as in 00-shared. Armadin: Shield is a product, a key and the `shield-bench` we hand them, numbers as "blocked X of Y on this corpus", never "secure". Name incumbents (Amazon Business, CDW, Dell); say IT buyer priced per refresh (proposed); never "Windows 10 now". Done-check: a timed run under the cap; every clause is built or labelled.
7. **d10 PR review gates, repo and hub page monitoring. 3.0 h total, rolling.** Review each PR before main; review Vedant's no-payment-without-approval invariant and Abhinav's CommitPayment gate; watch the repo and the hub page (https://claude.ai/artifact/Hjrg6QgJ8FgdmkoEAaLCeU) so it matches what is built; flag any lane more than 90 minutes behind a gate.

## Slip ladder minimum forms (your items)

- Phone call path (Sat 09:00, then Sat 18:00): in-browser Cartesia call; typed fallback code.
- Real purchase (Sat 18:00): receiving check on a teammate photo of a part already owned, labelled demo.
- Shield API extras (Sat 22:00): keys and schema stay (Anoop's layer); the core never shrinks: no model text in the verdict, fail closed.

## What you get and hand over

- **From A (Abhinav):** the a10 answer endpoint, the outside agent address, `/verify-agent`, CommitPayment.
- **From B (Vedant):** the allowance reducer and no-payment-without-approval invariant, the review card, the code display, the call screen.
- **From C (Anoop):** the merchant simulator, the hosted injected page, the 20 held-out attacks and 10 voice cases, Shield's OpenAPI, keys, meter, client and bench, the Photon decision.
- **To A:** Mandate and approval rows; Shield `/screen` for every agent message.
- **To B:** the Mandate shape, code words and VoiceApproval rows; Shield verdicts.
- **To C:** Shield core and the 30 dev attack cases for the bench; the mandate shape.
- **Sun 03:00 to 09:00:** you rehearse the pitch three times with the team, finish the video, write Devpost by 06:00 (Anoop's claims list is the fact source), T-60 health check, submit by 08:30. Anoop runs integration; you approve any deploy.

## Sponsor hard requirements you own

Visa: Trusted Agent Protocol signing and the mandate hash; never "Visa settles"; README states what is live and what is an adapter. Cartesia: voice is core to the product; README lists setup, the Cartesia features used and known limitations; 2-minute demo-first presentation; a deal above the allowance triggers the call. Armadin: Bazaar Shield as a product (versioned schema, signed receipts, rules as data, the live injection block, the attack corpus, the key and bench) and the Best Security Hack pitch. Devpost fields in plan/submission.md.
