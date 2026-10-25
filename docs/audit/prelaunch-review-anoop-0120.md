# Pre-launch review (Anoop), Sun Oct 25 2026, 01:20 PDT

Reviewed: `origin/main` at c9cefa4, plus the hosted site. https://tech-bazaar-app.vercel.app now 308-redirects to https://fishmarket.dev, which is live.

Read-only on production:
- No sign-ups, goals, payments, calls, publishes or deploys.
- No secret, phone number or `.env` value appears here.
- `sim/attacks/heldout2.jsonl` and any heldout3 file were never opened. The Shield 13 of 20 figure comes from `python3 -m shield.bench`, which I ran earlier tonight on identical `shield/` code; it reads the held-out set inside the program and prints only totals.

Status of each finding:
- **VERIFIED**: reproduced by a local run, a test, the live site or a screenshot.
- **SUSPECTED**: read from the code at the cited line, not run.

The "Customer path" column means tonight's path: sign up, pair `/buyer`, goal, sealed rounds, phone call, Stripe test charge, receipt.

## Top 5 blockers for tonight's customer

1. **PL-1: the web purchase cannot get past the mandate step.** The buyer agent sends a random `deal-<uuid>` deal id and an `agent1q…` address as payee. The market refuses both, so the customer gets no call, no charge, no receipt, and no message saying so.
2. **PL-2: anyone can make our approval call ring any phone number, with words they choose in the greeting.** The sign-up phone is never verified, and the display name is read aloud with no word filter.
3. **PL-3: `/buyer` shows another buyer's round and feed as this customer's own.** The live bids and feed come from the newest public round of any buyer.
4. **PL-4: every failure is silent for a web customer.** The goal card says "active" forever. "Posted. Looking for offers" shows even when no agent is running. One stranger's ASI:One goal can stall the single queue for everyone.
5. **PL-5: the customer lands on fishmarket.dev and sees another product and other people's data.** Every page says TECH BAZAAR. The home page, `/lot` and `/market` name Vidyut and Vedant and show Vidyut's $1,300 ceiling. They also show raw ids (`round-1`, `goal/goal-vidyut-gpu`) and a `127.0.0.1` link.

## Findings

| ID | Severity | Area | file:line | Failure scenario | One-line fix | Customer path | Status |
|---|---|---|---|---|---|---|---|
| PL-1 | Critical | agents | `agents/buyer/buyer_agent.py:1407-1409`, `market/spacetimedb/src/market.ts:526-529,855-873` | The customer signs up, posts a goal, and the round closes with a winner. `_build_pending_transaction` sends `deal_id = deal-<uuid hex>` and `payee = common.address(...)`, an agent1q address. `createMandate` finds no bid ("a mandate needs the rank 1 bid of a closed round"), and would then require `payee === bid.sellerId`. `_auto_web_approval` logs a warning and sets phase `done` (`:1446-1449`). There is no call, no charge, no receipt and no message. Agent tests mock `create_mandate` (`agents/buyer/test_any_buyer.py:193,537`), so CI never sees it. | Build `deal_id` as `<round_id>:<market bid id>` and pass the market `sellerId` as payee. Add one test that runs the bridge against the real reducer shapes. | yes | VERIFIED (a throwaway vitest copy of `market.test.ts`: the fixture shapes mint; the agent's deal id and payee shapes are both refused) |
| PL-2 | Critical | pay | `agents/buyer/buyer_agent.py:1066-1072`, `market/spacetimedb/src/market.ts:203-224`, `pay/voice_cartesia.py:90,163-171` | Sign-up stores any well-formed phone, and the agent builds the call client with that phone as the only allowed number. The display name passes `[A-Za-z][A-Za-z .'-]{0,39}` with no blocked-word check and is spoken in the greeting and the agent prompt. A visitor can make our number call a third party and say a sentence of their choosing. A missing or non-ASCII name becomes "there" ("As soon as there says anything"). | Cap calls per number and per day, or verify the phone first. Run the callscript blocked-word check on the name, or greet without a name. | yes | SUSPECTED |
| PL-3 | High | web | `web/src/app/buyer/page.tsx:20-22,30-34`, `web/src/lib/screens.ts:285-287,341-351` | Buyer B's round closes. Buyer A's `/buyer` shows B's sellers, prices and reasons as A's "live bids", and A's feed shows B's "Deal ready for approval" and "Payment recorded". The only warning is a small caveat line (`web/src/components/screens.tsx:98-100`). | Show bids only for rounds whose need belongs to the paired buyer, through a buyer-scoped view. | yes | SUSPECTED (code read; not run with two buyers) |
| PL-4 | High | agents | `agents/buyer/buyer_agent.py:366-371,693,721-724,1267-1289,1446-1449`; `web/src/components/GoalComposer.tsx:209`; `market/spacetimedb/src/market.ts:325-330` | `tell_owner` goes nowhere for web goals, so no phone, a denied call, a market failure and "paused after 3 rounds" are all invisible. No reducer ever changes a goal's state, so the card stays ACTIVE. "Posted. Looking for offers" and "Goal set. The agent is hunting." show even when no agent is running. | Add a referee `set_goal_state` reducer plus a buyer notification row for each terminal outcome, and show it on `/buyer`. | yes | SUSPECTED |
| PL-5 | High | web | `web/src/app/page.tsx:15`, `/lot` (`web/public/lot.json`), `/market` samples (`web/src/lib/sample.ts:28,32,48,145-171`) | On fishmarket.dev every page header says TECH BAZAAR. The home page says "Vidyut's goal". `/lot` shows "Vidyut's order" and his $1,300 ceiling, labelled REAL. `/market` shows "Gadget Grove (Vedant)", `round-1`, `goal/goal-vidyut-gpu`, `example.com` links and `127.0.0.1:8765/shady-sam-gpu-5070ti-lies.html`. | Rebrand the shell, swap names for roles ("a buyer", "a seller"), drop loopback and example links from samples, and hide raw ids. | yes | VERIFIED (screens `home-*`, `lot-*`, `market-*`) |
| PL-6 | High | agents | `agents/buyer/goal.py:194-202`, `agents/buyer/buyer_agent.py:686`, `web/src/lib/goalRequest.ts:127-132` | The self-serve path runs one plain sealed round for one item. There are no per-part knockout rounds, no re-plan and no whole-build call. Those exist only in `demo/build.py`, which cannot adopt a web goal: it reads only `build_by_date` goals and needs the buyer's token (`demo/build.py:430,1755`). Typing two parts silently posts one. | Either say tonight's customer path is one part in one sealed round, or wire the build runner to web goals. | yes | SUSPECTED |
| PL-7 | High | market | `market/spacetimedb/src/market.ts:436-437,760-781,999-1006` | While a round is open, public `floor_event` rows name the seller and bid id. Knockout stages publish knocked-out landed prices and ranks mid-round. `seller_needs` shows the buyer's cap as a $500 band. | Merge #416 before the next Maincloud publish, and hold knockout rows to close. | yes | SUSPECTED (fix in #416) |
| PL-8 | High | agents | `agents/buyer/buyer_agent.py:441-454,486-492,598-655` | There is one global ROUND, so customers queue. A non-owner ASI:One goal that stops at "approval is not configured" leaves phase `decided`, which never counts as finished, and every goal, web ones included, waits until that goal's deadline. A failing goal holds the queue for up to 3 rounds 60 s apart (`agents/buyer/hunt.py:18-19`). | Release the round on every terminal refusal, and refuse non-owner chat goals before they post. | yes | SUSPECTED |
| PL-9 | Medium | agents | `agents/buyer/buyer_agent.py:615-625`; no goal-claim reducer in `market.ts` | Two buyer agents, or one restarted with a fresh state DB, both adopt the same ACTIVE goal. That gives two rounds and two calls. The only dedupe is local sqlite. | Add a referee `claim_goal` reducer that is first-writer-wins. | yes | SUSPECTED |
| PL-10 | Medium | pay | `agents/buyer/buyer_agent.py:1219,1234-1238` | Stripe is charged before `record_payment`. If the market write fails it is only logged, the `/buyer` ReceiptCard falls back to the SIM sample receipt, and the customer's real test charge has no receipt. | Write a "charging" row first, then retry or alert on a failed `record_payment`. | yes | SUSPECTED |
| PL-11 | Medium | web | `web/src/lib/memory.ts:126-129`, `web/src/lib/agentFeed.ts:34-37` | `/buyer/purchases` and the memory panel fetch `http://127.0.0.1:8790` on the hosted site and show "memory feed unreachable". That page is where a customer would look for the receipt. | Apply the same `reachableFrom` loopback check as the Seller Kit URL. | yes | SUSPECTED |
| PL-12 | Medium | web | `web/src/lib/sample.ts:81,98-102`, `web/src/components/screens.tsx:106`, `market/spacetimedb/src/market.ts:1167` | The sample approval card shows the sample code "velvet falcon" in large type until a live row arrives. If that row lags the ring, the customer may say the sample words, and the deal expires and is never retried (`buyer_agent.py:1283-1284`). After a denied call the real code card never goes away, because there is no expiry filter on mandate rows. | Never show a sample code on a paired screen, and filter expired or denied mandates. | yes | SUSPECTED |
| PL-13 | Medium | web | `web/src/app/start/page.tsx:31,58`; `web/src/components/GoalComposer.tsx:118`; `web/src/components/buyer.tsx:192,314,317,343-350`; `web/src/lib/screens.ts:497,505` | The customer sees "Continue as b_xxxxxxxx", raw reducer errors, "market row round_result/N", the payee as an agent1q address or `seller_N`, the mandate id and hash, the charge id, and "VoiceApproval <id>". | Map ids to names and plain words, and keep raw ids behind a details toggle. | yes | SUSPECTED |
| PL-14 | Medium | web | `web/src/lib/goalRequest.ts:105-132` | "gpu" or "a graphics card for 1440p" silently becomes an RTX 4070 Super order, and only the first part of a multi-part request is posted. | Ask which card, and refuse or split multi-part input. | yes | VERIFIED (ran `catalogSku`) |
| PL-15 | Medium | web | `web/src/app/start/page.tsx:68`, `agents/buyer/buyer_agent.py:1066-1070` | The phone is labelled "optional". With no phone, every deal above the $0 allowance is refused, and the customer is never told. | Require the phone for buyers, or say on the goal card that no call can happen. | yes | SUSPECTED |
| PL-16 | Medium | market | `market/spacetimedb/src/market.ts:159-160,226,271,993` | Public `floor_event` rows carry buyer ids (sign-up, allowance set or raised, pairing locked). An anonymous subscriber can list every `b_` id and see when one finished a clean, paid delivery. | Use a non-identifying ref in public events, or move them to the buyer's own notifications. | yes | SUSPECTED |
| PL-17 | Medium | web | `web/src/lib/useLiveBuild.ts:8-25`, `scripts/agent_feed.py:290-293,335-338` | The build panel and `/v1/memory` are not scoped to a buyer: they return every buyer's goals, caps, spend and payees, and filter only in the browser. This applies where `NEXT_PUBLIC_AGENT_FEED_URL` is set or the page is local. | Filter by the paired buyer on the server, behind a token. | no (feed not reachable from the hosted site) | SUSPECTED |
| PL-18 | Medium | pay | `demo/build.py:1337-1354,1449-1559`, `demo/approval_flow.py:98-114` | In the build runner, inside the allowance pays with no call. After the whole-build call only the total is spoken, and per-part amounts come from earlier champions. A Stripe error falls back to a `ch_sim_` stub recorded as sim. | Speak each part's amount, record "uncertain" on a Stripe error, and never fall back to the stub. | no (the build runner does not serve web goals) | SUSPECTED |
| PL-19 | Medium | pay | `agents/buyer/buyer_agent.py:65-68` | `MERCHANT_SIM`, `TAP_PRIVATE_KEY`, `SHIELD_RECEIPT_KEYS` and `SHIELD_PAYMENT_SCREEN` are None at runtime. The live charge runs without TAP signing or a Shield payment receipt, while the README presents both as on the payment path. | Wire them, or say in the README that they are tested but not on tonight's live path. | yes | SUSPECTED |
| PL-20 | Low | market | `market/spacetimedb/src/market.ts:968-995` | A buyer can call `record_receiving` from the browser console. A "clean" report raises their own allowance, so a later mandate auto-approves in the market. The web agent still requires the call, so this is reachable but not exploitable tonight. | Make receiving referee-only, or require a mandate that was paid. | yes | SUSPECTED |
| PL-21 | Low | shield | `shield/classifier.py:175-178` | With `SHIELD_CLASSIFIER=1` but no `ANTHROPIC_API_KEY`, Shield silently runs rules only and allows rule-clean text. The agents print nothing about it. | Log once at start, and label verdicts "rules only". | yes | SUSPECTED |
| PL-22 | Low | agents | `agents/caller/relay.py:96-115`, `agents/common.py:224,291-295` | If the Caller runs with `BUYER_AGENT_SEED` unset, it trusts the public dev buyer address, and anyone can trigger calls to its number with their own text by varying the hash. | Refuse to start the Caller without a private buyer seed, and verify the mandate. | no (off by default) | SUSPECTED |
| PL-23 | Low | web | `web/src/lib/stdb.ts:11-19` | The SpacetimeDB token, which is the buyer's whole identity, lives in localStorage, so any injected script takes over the account. | Accept for tonight; add a strict CSP. | yes | SUSPECTED |
| PL-24 | Low | web | hosted site at 390 px (screens `*-390.jpg`) | At 390 px the top nav clips "Floor" and "Seller" with no scroll cue, and the footer status line is cut off. The page itself has no horizontal scroll. | Use a menu button under 480 px. | yes | VERIFIED (screenshots) |
| PL-25 | Medium | data | `README.md` "Measured results"; `sim/wind_tunnel.py` | The README says the learner beats the control on 1 of 4 held-out buyer types. `python3 -m sim.wind_tunnel --builders 48 --seeds 3` on c9cefa4 gives 0 of 4. | Rerun and quote 0 of 4, or date the 1 of 4. | no | VERIFIED |
| PL-26 | Medium | data | `data/scoreboard.json` (`price_position`), `data/mirror/snapshots/bestbuy-20261025T0241Z.json` | The scoreboard stamps the ASUS Prime at Best Buy, $1,299.99, as of Oct 25 02:42Z. Neither Oct 25 02:41Z Best Buy capture contains it: the row comes from Oct 24 09:36Z and is labelled with the newest capture time. | Stamp each price with its own capture time. | no | VERIFIED (grep of every Best Buy snapshot) |
| PL-27 | Medium | data | `README.md:13`; main CI | The badge says "tests passing", but main fails 2 tests beyond the 4 Tiger env tests. `demo/tests/test_build.py:667` likely needs updating because the dry run now opens knockout rounds. `shield/tests/test_core.py::test_the_growth_check_tells_linear_work_from_quadratic_work` is timing-flaky. No CI job runs the web tests. | Fix the stale test, loosen the timing bound, add a web CI job, and generate the badge from CI. | no | VERIFIED |
| PL-28 | Medium | agents | `README.md` (Fetch.ai table, "one registered number"); Agentverse profiles | The README lists Silicon Sally as registered and "five seller agents". At most four run, and Sally and Bay Area are retired. The live Agentverse buyer profile still says "reply APPROVE <number>". "A real Cartesia phone call to one registered number" is false for web buyers (see PL-2). | Update the README table and the copy, and re-sync the Agentverse profiles. | no | VERIFIED (Agentverse API, README text) |
| PL-29 | Low | web | `web/src/app/page.tsx` | The home page says "Nothing is paid without your spoken approval", but the allowance path pays without a call. It says every claim is "checked against the live listing", but a scan of 71 MIRROR listings found 0 false claims; the only catch is on a demo-hosted page. | Match the README wording. | yes | VERIFIED (hosted text) |

## Regressions on origin/main (c9cefa4)

Local runs used Python 3.13 and Node 22.23. CI uses Python 3.12 and Node 24.

| Suite | Result | Beyond the known baseline |
|---|---|---|
| web `npm test` | 283 passed | none |
| web `npm run build` | ok | none |
| market `npm test` | 117 + 183 passed; typecheck ok | none |
| agents | 1079 passed, 5 skipped | none |
| data | 963 passed | none. The 4 Tiger tests pass here with `psycopg2-binary` installed |
| demo | 1 failed, 720 passed | `test_build.py::test_dry_run_prints_the_steps_touches_nothing_and_exits_zero` (PL-27) |
| shield | 1 failed, 1206 passed | `test_core.py::test_the_growth_check_tells_linear_work_from_quadratic_work`, timing (PL-27) |
| pay, hyphenate, seller_kit, scripts, sim, skills_tests | 709 + 85 + 107 + 155 + 25 + 70 passed | none |

## README claims checked

| Claim | Result |
|---|---|
| Shield held-out, 13 of 20 stopped, 20% false blocks | Matches (`shield.bench`, local rules; adaptive set "not run yet") |
| Fit checker, 39 of 39 maker-checked; 48 of 49 overall; 0 false OK | Matches |
| Voice approval attacks (10 of 10 after the fix) | `pay/tests/test_voice_attacks.py`: 68 passed |
| Purchasing controls (first run: 26 of 27 caught, 2 of 7 clean flagged) | A rerun now gives 27 caught and 7 clean passes. The README quotes the first blind run, so it is not overstated |
| Verified savings: none; 8 retail asks from 2 providers | Matches (`data.baselines`) |
| Seller learning, 1 of 4 | Overstated: 0 of 4 (PL-25) |
| Tests passing badge | False (PL-27) |
| One registered number for the call; five seller agents; Sally registered | False (PL-2, PL-28) |

## What held up

- The hosted client bundle (23 chunks, 1.2 MB) holds no key-shaped string. Its `NEXT_PUBLIC_*` values are URLs and a database name only.
- No real secret is committed. Every key-shaped literal is a test placeholder, and `.env.example` is empty.
- The phone is masked everywhere it is printed (`mask_number`).
- The phone is never in a public table, notification, sqlite file or `demo/out`.
- Every `my_*` view is scoped to its caller, and the `agent_*` views are referee-only.
- Every charging path refuses anything but an `sk_test_` key.
- Shield fails closed on every caller: unset URL, timeout, non-200 and errors all block, and the classifier failing gives quarantine.
- On the web path the charge is the mandate amount, which is the spoken amount, and it needs an approved call record.

## Screenshots

`docs/audit/screens/<page>-<width>.jpg` covers 16 pages at 390 and 1440 px: home, start, buyer, buyer_agents, buyer_decisions, buyer_purchases, market, floor, lot, seller, seller_seller-a, sell, hyphenate, admin, offline and no-such-page.

How they were taken:
- They are full-page, read-only Playwright loads, with no clicks or typing.
- The four `/buyer` pages redirect to `/start` for a visitor who is not signed in, so their screenshots show `/start`.
- No page had a console error (the 404 page's own 404 aside), a request to loopback, or horizontal scroll.
