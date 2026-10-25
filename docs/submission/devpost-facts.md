# Devpost facts sheet: Fish Market

For whoever writes the Devpost page (Anoop). Every line below was checked on Sun Oct 25, 2026, 05:30 PDT against a branch cut from `main` at commit 279eb879; later merges to `main` are not re-checked. Each claim names the file, test or command behind it. If a line says "confirm", it is not proven from the repository and someone must check it before it goes on the page. Wording rules: Fish Market is the product, "Smell Test" is the screening agent, no em or en dashes, never "secure" as a claim, never "Visa settles", never "used by" for the Actors.

## One-liner

Fish Market is a marketplace where your AI buyer agent shops for PC parts, seller agents compete in sealed rounds, and nothing is paid until a checker, a screen and your own phone approval have all passed.

Tagline: "The secure agentic marketplace where buyers and sellers thrive." Secure is the goal we build toward, not a claim the numbers support yet (see Honest numbers).

## The problem

- Agents that shop for you read text written by sellers. A listing can hide instructions ("rank this bid first"), swap who gets paid, or claim "new" on a used part. Today an agent has nothing between that text and your money.
- A part can fail to fit a build or be under a safety recall, and a cheap bid usually wins anyway.
- Letting an agent spend money needs a human step that cannot be faked by a recording of a voice.

Fish Market puts code in each of those gaps: Smell Test screens every message, a deterministic checker tests fit, claims and recalls, a referee ranks, and payment needs a recorded approval for the exact mandate.

## How it works (10 steps)

1. You state a goal ("a 1440p gaming PC under $2,100"). The planner turns it into parts and skips ones you own (`agents/buyer/planner.py`).
2. One sealed knockout round per part. Sellers bid without seeing your exact budget (a $500 band), your allowance or each other's offers. Up to three best-and-final stages; rule-breakers and last place are knocked out with a reason (`demo/build.py`, `market/spacetimedb/`).
3. Smell Test screens every seller message, listing title and claim before any agent reads it; an injected listing is quarantined with the rules that fired (`shield/`).
4. The Quality Advocate checks socket, memory, power, connectors, clearance and CPSC recalls by code, compares each claim with its page, and can veto the cheapest bid, citing a source (`agents/advocate/`, `data/fit_checker/`, `data/recalls.py`).
5. The referee ranks in the market's reducers: same offers, same rank; no bid below its seller's floor; the seller fee never enters the ranking (`market/rules/`, `docs/ARENA_RULES.md`).
6. CRS checks the payee: a business seller needs a fresh verified identity check before it can be paid, bound into the mandate (`pay/crs_gate.py`, `agents/crs.py`).
7. Bright Data re-reads the winning listing's price right before the call; a moved price or sold-out part stops the build (`demo/recheck.py`, `data/baselines/brightdata.py`).
8. Above your allowance, a Cartesia voice agent phones you, reads the build and total, and answers "why not the cheaper one?". Code decides: only the one-time code shown on your screen plus "approve" passes; silence, hang-up or a wrong code denies (`pay/voice_cartesia.py`, `pay/approval.py`).
9. Stripe test-mode charge, once per part, keyed to the mandate hash so a retry cannot double charge. No real money moves (`demo/approval_flow.py`, `pay/merchant_sim.py`).
10. A receipt per part with the charge reference and mandate; losing sellers get a loss report (banded gap and reason, never a rival's price or your budget).

An LLM never decides pay, veto or rank. Claude only reads the goal and rewords sentences that code already wrote.

## Sponsors and what each does in the product

| Sponsor | What it does in Fish Market | Proof (file) | Status to state |
|---|---|---|---|
| Fetch.ai uAgents | Nine agents: Buyer, Quality Advocate, Smell Test, Caller, Market Pulse, Byte Bros Outlet, FlashDeal Frankie, ReNew Refurb, Central Comp MIRROR. Each has one job | `agents/` (`agents/buyer/buyer_agent.py`, `agents/advocate/advocate_agent.py`, `agents/caller/caller_agent.py`, `agents/pulse/orchestrator.py`, `agents/sellers/seller_agent.py`) | LIVE code |
| Fetch.ai Agentverse | Nine agents; five are registered with mailboxes (Buyer, Quality Advocate, Smell Test, Byte Bros Outlet, FlashDeal Frankie). Caller, Market Pulse and ReNew Refurb run locally with no verified Agentverse mailbox; Central Comp MIRROR runs locally on purpose (its log says no mailbox). Addresses are in the README table | `README.md` agent table, `agents/README.md`, `.run/logs/*.log` | The public profile check by API (agents/README.md, Oct 23, 23:46 PDT) covered six addresses: these five plus the retired Silicon Sally. The Caller and Market Pulse logs show only failed mailbox connects. Do not say "registered" for Caller, Market Pulse or ReNew Refurb until their profiles are confirmed on the Agentverse dashboard |
| Fetch.ai ASI:One | Front door: the owner types a goal in ASI:One chat, the buyer answers only its owner. Agent Chat Protocol and Payment Protocol are in the buyer. The receipt email is handed to ASI:One's Gmail connector | `agents/buyer/buyer_agent.py` (lines using `chat_protocol_spec`, `payment_protocol_spec`), `agents/buyer/post_purchase.py`, `agents/ISSUE14_EVIDENCE.md` | LIVE. A chat payment request is refused on purpose. Gmail connector: tested once live per the README; confirm |
| Cartesia | Approval phone call above the allowance: reads the build, answers questions, code judges the transcript; also the narrator voice in the videos (Lauren, sonic-3) | `pay/voice_cartesia.py`, `pay/approval.py`, `pay/VOICE_ATTACKS.md`, `pay/tests/test_voice_attacks.py` | LIVE: real outbound call to the buyer's own phone. Rate capped: 1 per number per 5 min, 20 a day |
| Anthropic Claude | Claude Haiku 5.5 reads the buyer's goal, rewords explanations (Advocate, Smell Test, Market Pulse), and is an opt-in Smell Test classifier. Never decides money, a veto, a verdict or a rank | `agents/buyer/understand.py`, `agents/phrasing.py`, `shield/classifier.py` | Needs `ANTHROPIC_API_KEY`; without it the code's own sentence is used. Classifier off by default |
| Apify | Dated MIRROR listings from stores, plus five Actors of our own: PC Build Compatibility Checker, Listing Claim Checker, Electronics Recall Checker, Seller Agent-Readiness Report (public on the Store), Listing Injection Screen (private). Actor ids are in the README | `data/mirror/`, `docs/ACTORS.md`, `data/fit_checker/actor`, `data/claim_check/actor`, `data/recall_checker_actor`, `data/readiness_actor`, `data/injection_screen_actor` | LIVE. Say "published and tested", not "used by": no outside users yet |
| Bright Data | Scraper API re-reads the winner's price before the call | `demo/recheck.py`, `data/baselines/brightdata.py`, `data/tests/test_brightdata.py`, `docs/changes/0330-D-brightdata.md` | Built, env-gated: runs only when `BRIGHT_DATA_API_KEY` is set. Confirm with Vidyut whether a live run is recorded before saying "live" |
| CRS | Identity check of the payee at the payment gate, in the CRS sandbox with the provided test identities | `agents/crs.py`, `pay/crs_gate.py`, `pay/tests/test_crs_gate.py`, `docs/changes/0033-A-crs-supplier-signal.md` | SANDBOX. Live run Oct 24 16:37 PDT: two simulated sellers verified_stable, one not_verified (README) |
| Stripe (test mode) | One PaymentIntent per part, idempotent on the mandate hash | `pay/merchant_sim.py` (refuses any key not starting `sk_test_`), `demo/approval_flow.py` | SANDBOX. No real money |
| SpacetimeDB | The shared market: sealed rounds, floors, rankings, mandates, approvals, goal states in reducers; every screen and agent reads the same state | `market/spacetimedb/src/market.ts`, `market/rules/` | LIVE on Maincloud, database `tech-bazaar` |
| Tiger Data | Time-series store for bid prices and Market Pulse trends | `data/tiger/store.py`, `data/tiger/schema.sql`, `docs/changes/0500-D-tiger.md` | Built, env-gated, never on the money path. Confirm whether a live write is recorded |
| Visa (TAP format) | Trusted Agent Protocol request signing (RFC 9421, Ed25519, nonce) verified against a port of Visa's reference verifier. Runs in the scripted reference run (`demo/run_demo.py`, beat 4) | `pay/tap.py`, `pay/merchant_sim.py`, `pay/tests/test_tap.py`, `pay/tests/test_tap_conformance.py` | Built and tested, not certified by Visa, and NOT on the live web purchase. Say "TAP wire format", never "Visa settles" |
| Vercel | Hosts the web app at fishmarket.dev | `web/` | LIVE (Pro plan per Vidyut's Oct 24 decision in the team's `plan/decisions.md`, outside this repository; confirm with Vidyut) |

Coinbase is not entered.

## Side tracks

- **Armadin (security):** Smell Test as an API any agent can call. Routes: `POST /v1/shield/screen`, `/v1/shield/verify-agent`, `/v1/shield/verify-mandate`, `/v1/shield/screen-payment`, `POST /v1/check-claim`, `GET /v1/shield/rules` (published rule list), `GET /v1/usage`. Code: `shield/api.py`, `shield/product.py`, `shield/bench.py`. Hand judges a key (`python3 -m shield.product new-key <caller>`) and the bench (`python3 -m shield.bench --extra your.jsonl`). Docs: `shield/API.md`.
- **Hyphenate (finance):** IT purchasing controls: PO numbers, a requester who cannot approve their own order, three-way match (PO, listing claim and page, delivery check), credit memo on a failed receiving check, an audit trail. A SIM company around a real rule engine. Code: `hyphenate/`; results: `hyphenate/RESULTS-blind.md`.

## Honest numbers (state them with their limits)

| Claim | Result | Source and reproduce |
|---|---|---|
| Smell Test, held-out attacks | 13 of 20 stopped (65%); 2 of 10 honest listings wrongly blocked (20%). Rules only, classifier off. First recorded run on Oct 23 was 12 of 20, so this is a rerun, not blind | `python3 -m shield.bench` (reran at 05:30 PDT today: dev 30 of 30, held_out 65%, 20% false blocks); `shield/API.md` |
| Smell Test, development set | 30 of 30, but the rules were written against it, so never pool it with held-out | `shield/corpus/RESULTS.md` |
| Fit checker | 39 of 39 right on builds whose every part was checked on a maker page; 48 of 49 decided on all 50 builds, 1 uncertain; 0 false OK. Tuned once, so not held out | `python3 -m data.fit_checker.eval_builds` |
| Voice approval attacks | 9 of 10 denied on the first run; 10 of 10 after one fix (not blind) | `python3 -m pytest pay/tests/test_voice_attacks.py -q` |
| Hyphenate blind planted errors | 26 of 27 caught on the first run; 2 of 7 clean cases falsely flagged | `python3 -m hyphenate.scenarios.blind_run`; `hyphenate/RESULTS-blind.md` |
| Seller learning lift | No headline lift: learner beats the control on 0 of 4 held-out archetypes (gate needs 2); the Oct 24 run printed 1 of 4 | `sim/RESULTS-2026-10-24-b48x3.md`, `sim/out/wind_tunnel-2026-10-25-b48x3.json` |
| Verified savings | None yet. Price reference is ready (median $1,279.99 for an RTX 5070 Ti across 8 in-stock retail asks from 2 providers) but no verified purchase is recorded | `python3 -m data.baselines`, `data/scoreboard.json` |

Do not quote a savings percentage. Do not call any of this "secure".

## What is LIVE, MIRROR, SIM, SANDBOX

- **MIRROR (a real, dated copy):** store listings and prices from Best Buy, Micro Center, B&H, Amazon, eBay, collected with Apify (`data/mirror/`); Central Comp MIRROR bids a real San Francisco store's listings for comparison. That store is not a partner and is never ordered from or paid.
- **SIM (generated by us):** every seller agent's bids (they bid from mirrored listings); FlashDeal Frankie's condition lie on a page we host; wind tunnel buyers; the Hyphenate company; the Smell Test registry entries. No outside shop has bid yet.
- **SANDBOX (a vendor's test mode):** Stripe test mode; the CRS sandbox with provided test identities.
- **LIVE:** sign-up and goals on fishmarket.dev stored under a person's own account; the Cartesia approval call; market state on Maincloud; the fit, recall and claim checks as code; Smell Test rules on every message.

Full table: `docs/REAL_VS_SIMULATED.md` (older) and the README table (current).

## Known limitations

- The website purchase step is the newest path (#483 landed Oct 25). It charges Stripe test mode right after the phone approval and does not yet run the CRS payee gate, TAP signing or the Smell Test payment receipt at charge time (`_pay_web_purchase` in `agents/buyer/buyer_agent.py`). The build runner runs CRS; TAP signing runs only in the scripted reference run.
- Smell Test blocks 1 honest listing in 5 and misses 7 of 20 held-out attacks. It is not ready to guard real money.
- Phone verification for new sign-ups is on the fix list (#449). Call limits exist (1 per number per 5 minutes, 20 a day; optional allowlist).
- Speech-to-text can miss the code in a noisy room; the answer is a new code, never a looser match.
- Seller learning shows no headline lift in simulation.
- Visa TAP is not certified by Visa. Bright Data and Tiger Data are env-gated.
- Outside sellers cannot yet bid live; no outside user has used the Actors.
- The buyer in ASI:One answers only its owner (by design; pitch it as loyal: it spends your money).

## Pricing line (for the pitch, not charged today)

Vidyut approved on Oct 24 (LOCKED entry of 18:40 in the team's `plan/decisions.md`, which lives outside this repository, so confirm with Vidyut before quoting): sellers pay 3% only on parts they win, the buyer keeps, capped at $25 a part, plus card processing at cost, about 5.9% all-in against Amazon at 8% and eBay at 13.6%. The competitor rates are not verified in this repository; confirm the sources before quoting.

## Team

Vidyut Sriram, Abhinav Dasari, Vedant Shirvi, Anoop Ibrampur.

## Links

- Site: https://fishmarket.dev
- Repo: https://github.com/vs-githjk/fish-market-nothing-fishy (confirm it is public before submitting)
- Smell Test API docs: `shield/API.md` in the repo
- Videos: general walkthrough and Fetch video (links from Abhinav; not in the repository)

## Names that must not change (live identifiers)

Database `tech-bazaar`, ASI:One handles `@techbazaar*`, agent addresses, Apify actor ids, and the env var names keep the old name. User-facing copy says Fish Market, and "Smell Test" for the screening agent.
