# Agent roster: depth over count (senior review, Sat Oct 24 21:35 PDT)

Base: origin/main 1d4970e (19:47). Rule: decisions.md:226 (Fetch: unique, relevant, "we don't need 6 sellers", look at 2FA) and :200 (reliability over features). Read-only review; no code changed. Paths below are repo-relative.

**Verdict.** Five non-seller agents are each a real, distinct job. The sellers are not: all six run one code path (`agents/sellers/seller_agent.py` `build`, bids from `policy.make_bid`) and four differ only by discount, shipping and persona text. Two more things matter more than the count. (1) The goal we film in ASI:One (storyboard A1, "RTX 5070 Ti") gets no bid from any of the three registered sellers: only seller_4 (sellers.json:285) and seller_5 (:373) list a 5070 Ti, and both are skipped in mailbox mode (run_all.py:22-24). (2) Nothing sends a `CallRequest` to Bazaar Caller (grep: only caller_agent.py:26,63). The buyer runs the approval call in its own process (buyer_agent.py:958-1006), so today the Caller duplicates work the buyer already does.

## 1. Inventory: what each agent really does today

Fetch tech key: Chat = Chat Protocol, Pay = Payment Protocol, MB = mailbox and Agentverse registration (Almanac entries come with registration; I did not check them separately), ASI = reached in ASI:One.

| Agent | What the code does today | Fetch tech | Unique? Relevant? |
|---|---|---|---|
| Tech Bazaar Buyer | Parses the goal with regex; only 2 GPUs are supported (buyer/goal.py:14). Runs the sealed round and picks the winner (buyer/hunt.py:37; MAX_ATTEMPTS 3, QUOTE_DRIFT 0.02 at :19-21). Runs the phone approval in its own process and shows the code in the owner's private chat (buyer_agent.py:979-1006). Buyer side of Pay (:1200-1438) | Chat (:395), Pay, MB, ASI (ISSUE14_EVIDENCE.md) | Unique, relevant. KEEP |
| Bazaar Advocate | Handles AdviceRequest (advocate_agent.py:29-40). Fit comes from Lane C's checker. Vetoes on condition, fit, recall, same_seller or mirror_not_orderable (advocate/checks.py:19), with a cited source. Recall uses CPSC. Price history and seller records are SIM fixtures | Custom messages, Chat profile, MB, ASI | Unique, relevant. KEEP |
| Bazaar Shield (client) | The public chat front door: it posts text to SHIELD_URL and returns the verdict (shield_client.py:20-36). The real screening is `common.screen` inside every handler (e.g. seller_agent.py:301, 338, 373) | Chat, MB, ASI (ISSUE14 23:58) | Unique job, but the agent itself is thin. KEEP. Say "Shield's public face; the screen runs inside every agent" |
| Bazaar Caller | Handles CallRequest and returns CallResult (caller_agent.py:63-98). Puts the code on /buyer through the referee (:39-50). One call through relay.handle (relay.py:46-75). No sender exists, and it is not registered | Custom protocol (:102). No Chat, not MB | Unique on paper; today a duplicate of the buyer's in-process call. Wire it in or stop claiming it (section 3) |
| Market Pulse | Takes PulseRound and returns PulseNotes, with a Chat front (pulse/orchestrator.py:699-751). Writes a coach note per losing seller from Tiger demand and loss counts (pulse/market_pulse.py:5-12). Not registered | Chat, custom messages | Unique, relevant. KEEP. Numbers stay SIM until Tiger has rows |
| seller_1 Byte Bros Outlet | Takes 3% off list (sellers.json:14-17). Learns a price step from loss reports, but only when its Market token file is set (seller_agent.py:52-88). Has a Market identity, seller-a (:30). No 5070 Ti line | Pay seller role (:328-404), Chat profile (:295), MB | Same job as seller_2 and seller_3 except for the numbers |
| seller_2 Silicon Sally's Surplus | 6% off, refurb persona (sellers.json:100-115). Same code path and the same learning as seller_1 | Same as seller_1 | Clone: the persona and the price numbers are the only differences |
| seller_3 FlashDeal Frankie | 2% off. Its planted lie: the bid says `condition: new` but the listing page says `open-box` (sellers.json:212-213), and the Advocate vetoes it | Same as seller_1 | Unique only because of the trap. The job is real |
| seller_4 Bay Area PC Shop | Cost plus a 14% fixed margin (sellers.json:270-273; policy.py:224). Not registered, and skipped in mailbox mode | Pay, Chat profile; no MB | Different math, same job. Clone |
| seller_5 ReNew Refurb | Puts refurbished and open-box lines of one part in one bid (sellers.json:388-395; policy.py:137-148), with condition stated on every line. No Market identity, so its bids reach the buyer only (seller_agent.py:94) | Pay, Chat profile; no MB | Unique behaviour. Not registered |
| seller_6 Central Comp MIRROR | Bids a real SF store's dated listings at the listed price. Never orderable: it ignores orders and payments (seller_agent.py:31-49, 280, 332, 367). Will not start without a private seed (:258-260) | Chat profile; no MB | Unique, relevant: the only uAgent seller tied to real prices. Not registered |
| Seller Kit custom | A factory, not an agent. It builds a seller from a SellerConfig (seller_agent.py:272-277), refuses a bad config (factory.py), and gives the seller no Agentverse profile (:277) | uAgents, UCP (seller_kit/ucp.py) | Relevant as "how a business plugs in". Not a standing agent |
| Demo floor (Shady Sam, Gadget Grove, snapshot MIRRORs) | Python objects in demo/sellers.py (Shady Sam :245), not uAgents. Shield catches Shady Sam in beat 2 | None | Say they are the demo floor, never Agentverse agents |

## 2. Proposed roster: 9 agents, one job each (was 11 plus a kit)

| Keep as | Job it proves on camera | Change | Label |
|---|---|---|---|
| Buyer | One message in ASI:One becomes a goal; it skips what you own; it ranks by landed price and never pays alone | none | LIVE, SIM sellers |
| Advocate | Vetoes Frankie's "new" card with the cited page condition | none | LIVE, SIM listing |
| Shield | Allow and block in ASI:One, with the rule ids (storyboard C2) | none | LIVE |
| Caller, "the second-factor agent" | The buyer cannot approve its own spend; the code is spoken on a separate channel | Section 3 | LIVE once wired, else don't claim it |
| Market Pulse | A losing seller's note with 7-day and 30-day records, every number sourced | Register it (S) | SIM numbers until Tiger has rows |
| **Learner**: Byte Bros (seller_1) | Loses round 1 within 5%, steps its price 3% while staying above its floor, bids again | Add a 5070 Ti line (S). Optional: limit learning to seller_1 so it is the only learner | SIM |
| **Trickster**: FlashDeal Frankie (seller_3) | Claims new while its page says open-box; the Advocate vetoes it with a source. Never ranked, never paid | Add a 5070 Ti trap line (S) | SIM, planted |
| **Honest refurb**: ReNew Refurb (seller_5) | One bid with refurbished and open-box lines, each labelled; the buyer gets the cheapest line its goal allows | Register it (S, manual seed and `connect.py 8015`) | SIM |
| **Real-store MIRROR**: Central Comp (seller_6) | Bids a dated real listing (URL plus snapshot) as a price anchor; the Advocate's mirror_not_orderable veto shows the buyer cannot pay it | Register it (S, private seed and `connect.py 8016`) | MIRROR |

CUT from the live roster, not from the code. seller_2 Sally does ReNew's job and still has a Market identity. seller_4 is cost-plus with the same job as the others. The code, tests and web arena still reference them (web/src/lib/arenaAgents.ts, test_profiles.py), so deleting them is M work with no payoff tonight. Stop running and filming them; the README agent table gets a "Job" column and marks them "Seller Kit examples, not running". Seller Kit is shown as the factory (storyboard E1), never as a ninth seller. Tradeoff: ReNew and MIRROR have no Market identity, so on the hosted floor only Byte Bros and Frankie publish bids (seller_agent.py:91-94). The Fetch video uses ASI:One and the terminal, so that is fine; the 4:00 walkthrough must not claim four sellers on the hosted board.

## 3. Two-factor and password-style verification

**Already built.** An agent's spend needs one-time step-up approval from the human on a second channel, and the approval is bound to that exact transaction.

- The code is HMAC(secret, mandate_hash:nonce) (pay/approval.py:134-136). The mandate hash covers amount and payee, and the seller rechecks both (seller_agent.py:163-177), so the code works only for that amount and that payee.
- Channel 1 is a screen only the owner sees: the private ASI:One chat in the buyer runtime (buyer_agent.py:979-990), or /buyer through the referee (caller_agent.py:39-50).
- Channel 2 is the phone at APPROVAL_CALL_TO. Only the human's speech counts (voice_cartesia.py:285-287), and the code is never sent to Cartesia (:234-239).
- Limits: 300 s TTL, 3 attempts, 30 s cooldown (approval.py:41-44), replay refusal through NonceStore, and a typed code never approves (relay.py:33-35).

**Honest label.** Say "two-channel, transaction-bound approval", the same pattern as a bank's dynamic-linking step-up (REPORTED: PSD2 SCA, from memory, not fetched). It is strict 2FA only if /buyer sits behind the account sign-in (decision 205): something you know (the sign-in) plus something you have (the phone). Verify that before saying "2FA" on camera. It is not voice biometrics. Someone who holds both the open screen and the phone can approve, and SIM swap remains a risk.

**Line for camera and judges.** "Our agents never hold your passwords or one-time codes. When an agent wants to spend, the Caller is the second factor: a code shown only to you, spoken back on a call to your phone, valid for this amount and this seller only."

**Never build an agent that handles users' real passwords or OTPs for other sites.**
- Relaying OTPs is exactly how real-time phishing and account-takeover fraud works.
- It hands the factor to software, which defeats the point of 2FA.
- It turns us into a credential store and a breach target.
- It breaks sites' terms of service.
- An agent that holds a code can be prompt-injected into sending it out; that is why Shield has an exfil rule.
- Card data never touches us (decision 205).

**The one deepening (M, Lane A, Lane D reviews pay/).** Make the buyer delegate the call to the Caller over uAgents, behind a flag `BUYER_APPROVAL_VIA_CALLER=1` that is off by default.
- The buyer sends CallRequest and accepts CallResult only from the Caller's address. It does not trust `approved`; it re-reads the approval record from the shared store through `approved_voice_record_matches` (approval.py:181) before checkout.
- Result: separation of duties. The agent that wants to spend cannot approve itself.
- Already built: caller_agent.py, relay.py, test_relay.py and the screen sink. New: the buyer-side send and wait, the address check, the flag, Caller registration, and one test.
- If it misses the gate (section 4), film the in-process call and describe the Caller as "the same approval call, packaged as its own agent", not as a step in the filmed loop.

Rejected for tonight: a seller-side signed challenge. agents/seller_admission.py:71-161 already verifies TAP-signed admission requests, but no agent calls it (grep: only its own module and docs). Wiring it changes who may bid (L) and is a post-hackathon step. Mention it only as "built, not wired".

## 4. Effort, risk, storyboard impact and cut line

| # | Change | Size, owner | Risk | Storyboard-fetch scenes |
|---|---|---|---|---|
| 1 | Add 5070 Ti lines to seller_1 (honest) and seller_3 (trap); run `pytest agents/sellers agents/test_profiles.py` | S, Lane A (Abhinav) | Low: config only; tests may pin seller listings | A1 and A3 then get real bids |
| 2 | Register ReNew (seller_5) and MIRROR (seller_6): private seeds, `connect.py 8015/8016`; stop running seller_2 and seller_4 | S, Lane A, manual | Low; needs Abhinav's machine | F0 count; B1 |
| 3 | README agent table: "Job" column, retired sellers marked | S, Lane A or writer | None | E2 |
| 4 | Storyboard edit: B1 becomes "four sellers, four jobs"; new B5 (12 s: Frankie veto, ReNew two lines, MIRROR "cannot be bought here"); new A4b Caller (10 s). Pay for the 22 s with C3 -5, E2 -4, D3 -3, A3 -3 (cut shot c), B3 -4, A2 -3. B4 stays "a simulated shop" (demo/learning.py), never Byte Bros, unless the agent path is run | S, Lane D, creator | Low | F0, A2, A3, A4b, B1, B3, B5, C3, D3, E2 |
| 5 | Register Market Pulse | S, Lane D | Low | D2 shot c becomes LIVE |
| 6 | Buyer delegates to Caller (section 3) | M, Lane A plus a Lane D review | Medium: on the money path | A4b: say "LIVE" only if green |
| 7 | Limit learning to seller_1 | S, Lane A | Low; touches test_seller_learning_caller.py | B2, B3 |
| 8 | Frankie also carries a Shield-catchable injection | M, Lane A | Medium: can blank the round | none (C2 already covers it) |

**Cut line** (decisions.md:200; submission Sun 08:30 PDT):
- Items 1 to 5 by **23:00** Sat. They are config, registration and docs only, and must be green before Fetch capture.
- Item 6 only if it is green in 3 rehearsals by **01:00** (the sprint-final.md cut line). Otherwise keep it out.
- Items 7 and 8 are below the line; skip them.

## 5. Top 3 recommendations

1. Before filming, give Byte Bros and Frankie a 5070 Ti line. The filmed ASI:One goal gets zero bids from today's registered sellers.
2. Run four sellers with four jobs (learner, trickster, honest refurb, real-store MIRROR) by registering ReNew and the MIRROR and retiring Sally and Bay Area. This is config and registration only, no seller code.
3. Present the phone approval as a transaction-bound second factor in a new 10 s Caller scene, and claim the Caller is a separate agent in the loop only if the buyer-to-Caller wiring is green by 01:00.
