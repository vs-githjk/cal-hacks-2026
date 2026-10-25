# Red team audit (Anoop), Sun Oct 25 2026, 01:10 PDT

Reviewed: `origin/main` at c9cefa4 (after #425), the hosted site, the live Maincloud market (public tables only), the Apify account and Store, and Agentverse.

Nothing was paid, no agent was messaged, and no account was created on the hosted site. The one paid action was a $0.005 Apify run to confirm RT-3's Store fix.

Status of each finding:
- **VERIFIED**: reproduced. Either a local run shows the bad result, or a live service shows it.
- **SUSPECTED**: read from the code at the cited line, not run.

The tonight column says whether the finding affects tonight's real customer path: sign up, goal, sealed rounds, phone call, Stripe sandbox, receipt.

This repo is public. RT-1 and RT-2 are worded to be assignable without being a recipe. Details are available from Anoop directly.

## Top 5 risks

1. **RT-1:** anyone can sign up on the hosted site with any phone number and make our approval call ring it.
2. **RT-2:** the operator pairing code is generated from a seed that public data can narrow down, so it should be treated as guessable until reissued.
3. **RT-3:** the PC Build Compatibility Checker on the Apify Store crashed on every run. It is now fixed on the Store (build 0.1.8); the source fix is in #434, unmerged.
4. **RT-4:** one ASI:One user who is not the operator can lock the buyer agent for everyone until their goal's deadline. Every buyer shares one buyer agent, so web customers are locked out too.
5. **RT-5:** sealed rounds leak who bid, and knocked-out prices, while the round is still open. The fix is in #416, unmerged.

## Findings

| ID | Severity | Area | file:line | What goes wrong | Suggested fix | Tonight | Status |
|---|---|---|---|---|---|---|---|
| RT-1 | Critical | agents | `agents/buyer/buyer_agent.py:1066-1072`, `market/spacetimedb/src/market.ts:203-224` | Sign-up stores any well-formed phone number and never verifies it. A new buyer's allowance is $0, so any goal that reaches a winner needs a call. The approval call client is built with the allowed number replaced by that profile phone, so the `NumberNotAllowed` guard (`pay/voice_cartesia.py:303`) passes for any number. #425 extends the same rule to `demo/build.py` and `demo/bridge.py`. A stranger can make our Cartesia number call someone else, repeatedly. | Cap calls: one per number per N minutes plus a daily total. Better: verify the phone before storing it, or keep an operator allowlist during judging. | yes | SUSPECTED |
| RT-2 | Critical | market | `market/spacetimedb/src/market.ts:184`, `market/spacetimedb/src/demo.ts:61` | Pairing codes come from `ctx.random`. SpacetimeDB SDK 2.13.0 seeds it only from the transaction timestamp (`makeRandom(this.timestamp)` in the SDK's `dist/server/index.mjs`). `seed_demo` issues the code in a transaction that also writes a public, timestamped row. Pairing as `vidyut` shows his goal, allowance, deals and on-screen approval code, and lets the holder deny approvals. | Now: the owner runs `reissue_pair_code` for `vidyut`, and again after every fresh publish followed by `seed_demo`. Then: make secrets off-module and pass them in, or store only a hash. | no | SUSPECTED (mechanism confirmed in SDK source, not exploited) |
| RT-3 | High | data | `data/fit_checker/actor/bundle.sh:7` | The bundle never copied `part_specs.py` or `part_specs.json`, so Store build 0.1.7 failed on import for every run. A judge's "Try for free" would have failed. | Done: the bundle now copies both, with a bundle-alone test (#434). Store build 0.1.8 run `Nk4hrP3GhOa5ZcbNF` SUCCEEDED. Merge #434. | no | VERIFIED (test reproduced the ModuleNotFoundError; fixed run on the Store) |
| RT-4 | High | agents | `agents/buyer/buyer_agent.py:1383`, `:441-454`, `:486-492` | A non-owner sends a complete goal in ASI:One, and it runs a real round under the operator's market buyer id. At approval it stops with "Private purchase approval is not configured", leaving phase `decided`. `round_finished()` never treats that as finished. Every other sender, including the operator and web goals, gets "A buyer session is active" until that goal's deadline. | On that refusal, set phase `done` and release the round. Refuse non-owner chat goals before posting to the market. | yes | SUSPECTED |
| RT-5 | High | market | `market/spacetimedb/src/market.ts:436-437`, `:760-781`, `:1018` | While a round is open, public `floor_event` rows name the seller and bid id. Knockout stages publish knocked-out rows' landed price and rank mid-round. `seller_needs` shows anyone the buyer's cap as a $500 band. | Merge #416 before the next Maincloud publish. Hold knockout rows to round close. | yes | SUSPECTED (fix in #416) |
| RT-6 | High | agents | `agents/buyer/goal.py:100-110`, `agents/buyer/buyer_agent.py:531-535` | In ASI:One, "find me an RTX 5070 Ti under $1300" gets "What condition do you want: new or open-box?". Answering "new" gets "What is your maximum budget?". Each message is parsed alone, with no memory of the question just asked. | Keep the last partial goal per sender for a few minutes and merge each answer into it. | no | VERIFIED (ran `parse_goal` on all three messages) |
| RT-7 | High | market | Maincloud `tech-bazaar` (public tables) | The live market has 0 rounds, 0 round results and 0 agent events (1 `goal_posted` row). Every hosted page shows a SIM sample, never a real round. | After #416 merges and is published, run one real round on Maincloud before judging. | no | VERIFIED (anonymous SQL on the public tables) |
| RT-8 | High | agents | Agentverse profiles; `agents/buyer/AGENTVERSE.md` | The live profiles were last updated Oct 24 06:45 UTC. The buyer profile still says "reply `APPROVE <number>`", but chat APPROVE is refused. It also says "three seller agents" and that listings are SIM. Only the buyer has an avatar. All agents have 0 starter prompts and no tags. Agentverse search for "PC parts buyer agent", "RTX 5070 Ti" or "buy a graphics card" finds none of our agents. | Re-sync every profile from the repo files. Add starter prompts written as complete goals (see RT-6), keywords and avatars. | no | VERIFIED (Agentverse search API) |
| RT-9 | High | pay | `agents/buyer/buyer_agent.py:65-68`, `:1207-1241` | `MERCHANT_SIM`, `TAP_PRIVATE_KEY`, `SHIELD_RECEIPT_KEYS` and `SHIELD_PAYMENT_SCREEN` are None at runtime. So no web purchase runs TAP, the Shield payment receipt or `mark_used` at charge time. The Stripe charge happens before `record_payment`, and a failed market write is only logged. Separately, a chat `RequestPayment` is always rejected. | Record a "charging" row in the market before Stripe. Retry or alert on a failed `record_payment`. Wire the hardened path, or stop claiming it for the live path. | yes | SUSPECTED |
| RT-10 | Medium | pay | `demo/approval_flow.py:96-114`, `agents/buyer/buyer_agent.py:1216-1226` | A Stripe error or timeout falls back to a `ch_sim_` stub recorded as a sim payment, so a real test-mode charge can go untracked. | On a Stripe error, record "uncertain" and look the charge up by its idempotency key. Never fall back to the stub. | yes | SUSPECTED |
| RT-11 | Medium | market | `market/spacetimedb/src/market.ts:905`, `:1111`, `:947-961` | `record_approval` accepts any non-empty `voiceApprovalId` from the referee and never checks it against `approval_code`. The code is stored in plaintext. `record_payment` does not check mandate expiry. Several mandates per deal are allowed. | Check the code hash in `record_approval`, check expiry in `record_payment`, and allow one live mandate per deal. | yes | SUSPECTED |
| RT-12 | Medium | agents | `agents/market_bridge.py:552-557` | For the referee, `record_approval` returns a constructed result without reading the market back. The web path also skips the `approved_at` re-read, so its check always passes. | Read the approval row back before charging. | yes | SUSPECTED |
| RT-13 | Medium | agents | `agents/buyer/buyer_agent.py:1441` (web approval path) | The web purchase path skips `eligible_for_order` (the reviewed and advocate status) and the fresh quote, and runs no CRS check. The README says CRS checks the payee before every payment. | Run the same eligibility, quote and CRS checks as the chat path. | yes | SUSPECTED |
| RT-14 | Medium | market | `market/spacetimedb/src/market.ts:194-216` | The sign-up throttle is global, 30 per 10 minutes, and new identities are free. One person can block sign-ups for everyone, including judges. | Throttle per identity or connection, with a higher global ceiling. | yes | SUSPECTED |
| RT-15 | Medium | web | `web/src/lib/goalRequest.ts:115` | Typing "gpu" or "a graphics card for 1440p" silently orders an RTX 4070 Super. The file header says it never maps silently. | Ask which card instead of choosing one. | yes | VERIFIED (ran `catalogSku`) |
| RT-16 | Medium | web | `web/src/app/start/page.tsx:68`, `agents/buyer/buyer_agent.py:1066-1070` | The phone is labelled "optional". Without it, every deal above the $0 allowance is refused and expires, and the web buyer is never told. | Require the phone, or say on the goal card that no call can happen. | yes | SUSPECTED |
| RT-17 | Medium | web | `web/src/lib/memory.ts:126`, `web/src/lib/agentFeed.ts:37` | The `/buyer` memory panel fetches `127.0.0.1:8790` on the hosted site. There is no `reachableFrom` check, so it errors in every visitor's browser. | Use the same loopback check as the Seller Kit URL. | yes | SUSPECTED |
| RT-18 | Medium | web | `/market` and `/floor` on the hosted site | The `/market` sample labels Amazon, Best Buy, eBay and Micro Center as SIM, but they are MIRROR. It shows a `127.0.0.1:8765` source link and a $1,249.99 winner. `/floor` uses retired sellers (Sally, Bay Area). The README winner is $1,299.99. `/lot` labels a scripted goal "REAL". | Use one recorded run for every sample, with its true labels, and no loopback links. | no | VERIFIED (read on the hosted site) |
| RT-19 | Medium | data | `data/claim_check/__init__.py:338-399` | The Claim Checker ignores `priceCurrency`. A CAD page with price 1749.99 makes "price $1,749.99" verified, and it is charged. The Store's default input is a CAD page. | Read `priceCurrency`, and return unverified when it is not the claim's currency. | no | VERIFIED (ran `check_claim` on a CAD page) |
| RT-20 | Medium | data | `data/claim_check/__init__.py:199-223` | `page_facts` trusts a `<script id="listing">` JSON block on any host ahead of JSON-LD. Warranty falls back to free text. "Verified" means the seller's page agrees with the seller, while the Store says "Is the seller telling the truth?". | Limit the listing block to our demo hosts, and reword the Store headline. | no | SUSPECTED |
| RT-21 | Medium | shield | Main CI python-tests; `demo/tests/test_build.py:667`, `shield/tests/test_core.py` | Main is red on every push after 9a397eb. `test_build.py:667` counts `open_round`, but the dry run now opens knockout rounds, so it is likely a stale test. Two Shield timing tests are flaky on CI runners. The README badge says "tests passing", and no CI job runs the web tests. | Lane D confirms knockout is the dry-run default and updates the test. Loosen the timing bounds. Add a web test job. | no | VERIFIED (test failure reproduced locally) |
| RT-22 | Medium | agents | `agents/buyer/buyer_agent.py:270`, `:481`, `:527` | Chat shows only the winning bid ("1 sealed bids"), so the vetoed cheaper bid never reaches the user. Once-per-round flags mean repeat messages get an acknowledgement and no text. | Send the round summary with the veto. Reply to every message, even if only "still running". | no | SUSPECTED |
| RT-23 | Medium | market | `market/spacetimedb/src/market.ts:751`, `:811` | `close_stage` skips the hold sweep and sold-out check that `close_round` runs, so a knockout champion can be held past the stock. | Run the same stock checks in `close_stage`. | no (the buyer agent opens plain rounds) | SUSPECTED |
| RT-24 | Medium | agents | `agents/caller/relay.py:107-112` | If the Caller is offline, its mailbox queues the request. The buyer falls back to a direct call after 240 s, and the Caller later wakes and calls again. A lost reply also re-rings. | Put `expires_at` in the request and refuse stale requests. | no (off by default; web buyers never delegate) | SUSPECTED |
| RT-25 | Medium | agents | `agents/crs.py:242-249`, `:452` | With no profile file, every payee is SIM and passes CRS. On a transport failure, an unsigned cache file is trusted. | Treat "not configured" as hold everywhere, and sign or ignore the cache. | no | SUSPECTED |
| RT-26 | Low | agents | `agents/buyer/buyer_agent.py:424-432`, `shield/api.py:78-109` | The buyer's REST `/chat` has no authentication and binds 0.0.0.0, so anyone on the venue Wi-Fi can post goals. The Shield API has no authentication, and `screen-payment` signs receipts for anyone. The Shield client agent returns rule ids to any sender. | Bind to 127.0.0.1 and require a token on the Shield routes. | no | SUSPECTED |
| RT-27 | Low | agents | `agents/common.py:224-232` | Every agent except seller_6 has a public default seed. The registered addresses do not match the defaults, so production is fine, but a missing env var silently falls back to an address anyone can sign as. | Refuse to start without a private seed. | no | VERIFIED (derived the default addresses; none match the registered ones) |
| RT-28 | Low | data | Apify Store; `data/recall_checker_actor`, `data/injection_screen_actor/README.md:7,68` | Each public Actor has 2 users and only our own API runs. The Recall Store build predates #418. The Injection Screen README says public at $0.001, but it is private. Prices read "claim checkeds" and "listing reporteds". | Re-push Recall (with an OK), fix the Injection Screen README, and rename the event titles. | no | VERIFIED (Apify API) |
| RT-29 | Low | data | `data/readiness_actor/src/main.py:26,39` | More than 200 URLs are dropped silently. The 15-minute run budget is longer than the 300 s default timeout, so a big run dies before writing OUTPUT. | Say how many URLs were dropped, and set the budget under the timeout. | no | SUSPECTED |
| RT-30 | Low | data | `README.md:116,176`, `docs/ACTORS.md:11-17` | The README says the readiness source is "in review (#309)", but it is on main, and says "four Actor sources" when there are five. ACTORS.md has committed conflict markers (fixed in #421) and stale counts. | Merge #421 and update the README lines. | no | VERIFIED (git grep and the file text) |
| RT-31 | Low | market | `market/spacetimedb/src/market.ts:327` | A buyer using the SDK can label their own goal's public floor event LIVE, because origin is caller-supplied. | Set origin on the server. | yes | SUSPECTED |
| RT-32 | Low | market | `market.ts:943`, `agents/buyer/buyer_agent.py:1228` | A Stripe test charge is labelled LIVE in the market but SIM by the agent. | Use one label: SANDBOX. | yes | SUSPECTED |
| RT-33 | Low | web | `web/src/app/page.tsx` (home copy) | The home page says "Nothing is paid without your spoken approval", which contradicts the allowance path. It says every claim is "checked against the live listing", but a scan of 71 MIRROR listings found 0 false claims; the only catch is on a demo-hosted page. | Match the README wording. | no | VERIFIED (read on the hosted site) |

## What held up

- Private tables (bids, mandates, phones, approval codes) are not readable anonymously.
- A seller cannot bid as another seller.
- Reset and seed need the owner or referee.
- Payment needs a recorded approval (`market.ts:953`).
- Shield fails closed.
- No real secret is committed.
- `python3 -m shield.bench` reproduces 13 of 20 held-out attacks stopped, with 20% false blocks.
- `data.fit_checker.eval_builds` reproduces 39 of 39.
- Web unit tests pass, 283 of 283.

## Open PRs that cover a finding

| Finding | PR | Notes |
|---|---|---|
| RT-3 | #434 | |
| RT-5 | #416 | |
| RT-30 | #421 | |
| RT-1 | #425 (merged) | Widened RT-1 |
