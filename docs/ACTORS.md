# Our Apify Actors: what each one is for, and how useful it really is

Written Sat Oct 24 2026 (Lane C). Purpose: say honestly which Actors earn their place, so we never count one that is only there to raise the number. Every figure below comes from the repo, the Apify account API on Oct 24 or a dated test run; nothing is rounded up.

## The five, at a glance

| # | Actor | What it does | On Apify | Our product uses it | Evidence it works | Real value (1 to 5) |
|---|---|---|---|---|---|---|
| 1 | **PC Build Compatibility Checker** (`pc-build-compatibility-checker`) | 12 fit rules over a PC build (CPU socket, RAM type and form, RAM slots, PSU watts, GPU connectors, GPU length vs case, cooler height, board vs case, drive slots). Pass, fail or uncertain per rule, with the maker page behind each number | Public, pay per event $0.005 | **Yes, in the demo's decision path**: the same code (`data/fit_checker`, `check_fit`) runs inside the advocate, the buyer's build check and the Build Story. The product calls the library, not the Actor | Maker-checked subset 39 of 39 correct, false OK 0; all 50 builds 48 of 49 (docs/board/C.md, Oct 24 06:35). Real catches on real parts: Thermalright Peerless Assassin 120 SE (155 mm) in a Fractal North (145 mm); DDR4 kit on a DDR5 board (found again on the Oct 24 captured prices, PR #377) | **5** |
| 2 | **Listing Claim Checker** (`tech-bazaar-claim-check`) | Reads a live product page's schema.org data and says verified, false or unverified for price, condition, stock, warranty, returns. Evidence is the URL, the time and a sha256 of the page | Public, pay per event $0.01 (only verified or false are charged) | **Yes**: `check_claim` is what Shield's `/v1/check-claim` and the demo's claim beat run. The Actor wrapper has a fail-safe client (`actor_client.py`) that no demo path calls yet | The scanner is proven on labelled fixtures. On 41 real saved listings it found **0 false claims** (it judged only 4 claims, all verified): honest, but it means we have no real catch to show | **4** |
| 3 | **Electronics Recall Checker** (`electronics-recall-checker`) | Brand plus product name (plus model or UPC) against the US CPSC recall database: recalled, possible, none, unverified. Each hit links the cpsc.gov page with hazard, remedy and units | Public, pay per event | **Yes, in the advocate's decision path (#398)**: every recall lookup the advocate makes calls the Actor's own matcher, `data.recall_checker.check_product` (`agents/advocate/real_data.py:213`, reached from `agents/advocate/advocate_agent.py:39`). Its recalled vetoes and its unverified is a note. Its possible is a lead: a GPU name like "rtx 4070 super" has no model code, so `data/recalls.py`'s exact model phrase rule, on the same cache, decides veto or caution (`real_data.py:217`) | Two real recalls reproduced on the Oct 24 sample: Anker PowerCore 10000 A1263 (about 1.16 million units) and Samsung Galaxy Note7. It never reports a failed lookup as "none" | **3** |
| 4 | **Listing Injection Screen** (`listing-injection-screen`, code on main) | Runs Bazaar Shield's deterministic rules over listing text and says block, flag or pass with the matched text. Rules only, no LLM, no key | Private on Apify since Oct 24 (`pzSsctJHHdNzrLJH8`); not on the public Store, so its README's Store link does not open for others | **Yes, in seller onboarding (#398)**: the Seller Kit screens every new shop's text (name, kind of shop, perks, claims, parts, pages, attrs) with the Actor's own `screen_text` before anything is written (`seller_kit/api.py:137`, called at `:239`). Block or flag is refused (422); a screen that raises or does not read the text is refused too (503), fail closed. The buyer's round still uses Shield directly (`demo/round.py`) | Shield's own numbers, as dated in `shield/corpus/RESULTS.md`: dev 30 of 30 and dev2 30 of 30 (in-sample, tuned on), held-out 7 of 10, post-freeze check 6 of 12. The Actor adds a wrapper and billing, no new detection | **3** |
| 5 | **Seller Agent-Readiness Report** (`seller-agent-readiness-report`, code on main since #309) | For any listing URL, says what an AI shopper sees: blocks, warns, ready or unreadable, with a fix per finding. $0.02 per listing read, unreadable is free | Public, pay per event | **Yes, on the /sell result (#398)**: after a shop is written, the Seller Kit runs the Actor's own `check_listing` on each listing page, in parallel within 8 s (`seller_kit/api.py:169`, added to the answer at `:246`), and `/sell` shows what an AI shopper sees with a fix per finding (`web/src/app/sell/page.tsx:252`). A page not read in time is unreadable, never a block on the shop | 4 runs, all ours. Tested against a real Canada Computers page (warns on returns and shipping only), SSRF guards, deadlines, a real local-server test for the fetcher | **3** |

Rating key: 5 = the product's decisions depend on this logic and it is checked against maker or government data; 4 = the logic is in the product and sound, but we have no real-world catch yet; 3 = real but thin (a wrapper on logic that lives elsewhere, or not on the demo path); 2 = mostly there for the count; 1 = for the count only.

## Actor IDs (for Apify)

| Actor | Actor ID | `username/actor-name` | URL | Pricing (pay per event) | Last successful run |
|---|---|---|---|---|---|
| Listing Claim Checker | `U4g8XPRpuGhDa97cM` | `anoopibrampur/tech-bazaar-claim-check` | https://apify.com/anoopibrampur/tech-bazaar-claim-check | $0.01 per `claim-checked` (only verified or false claims), $0.00005 per `apify-actor-start` | `T0ASSKGvCUf8DclZ5` (Oct 24 19:53 UTC) |
| PC Build Compatibility Checker | `djo1yhWs81xud1DkO` | `anoopibrampur/pc-build-compatibility-checker` | https://apify.com/anoopibrampur/pc-build-compatibility-checker | $0.005 per `build-checked`, $0.00005 per `apify-actor-start` | `oNgFAznvcXn3RCO7H` (Oct 24 20:04 UTC) |
| Electronics Recall Checker | `uMK7F4tqYnnbBkknU` | `anoopibrampur/electronics-recall-checker` | https://apify.com/anoopibrampur/electronics-recall-checker | $0.002 per `product-checked`, $0.00005 per `apify-actor-start` | `ItvSaUKtsjwhXd5jg` (Oct 24 22:48 UTC) |
| Seller Agent-Readiness Report | `whYB0iBdGanGPVv05` | `anoopibrampur/seller-agent-readiness-report` | https://apify.com/anoopibrampur/seller-agent-readiness-report | $0.02 per `listing-reported` (unreadable pages are free); default run 1 GB and 300 s | `Ug5TASTEbVcwSeCnV` (Oct 24 22:47 UTC) |
| Listing Injection Screen | `pzSsctJHHdNzrLJH8` | `anoopibrampur/listing-injection-screen` | https://console.apify.com/actors/pzSsctJHHdNzrLJH8 (private) | not set (private, free to run) | `CyjW4NhXhXlD9JFBL` (Oct 24, about 19:20 PDT: the honest SIM listing passed, the injected one was blocked) |

The Listing Injection Screen was published as a private Actor on Oct 24 at Anoop's go-ahead, with one successful run on its example input.

## Reading the table honestly

- **Two Actors are substantial (1 and 2).** They package the logic the product itself runs. If the Actors vanished tomorrow, the product would lose its compatibility checks and its claim checks, so these are not padding.
- **Three are real but thinner (3, 4, 5).** The recall Actor is a careful front end to one public API. The injection screen is Shield's rules behind a form: Shield is the substance, and its held-out numbers (7 of 10, then 6 of 12) are modest and say so. The readiness report is a seller-side product on shared page-reading code. None of the three is padding, and none should be sold as an independent engine.
- **No Actor has outside users yet.** The Apify API on Oct 24 shows 12, 9, 7 and 4 total runs for the four published Actors, every run started through the API (our tests, probes and scheduled example runs), and 2 total users each (us). Do not say "used by" or "adopted"; say "published and tested".
- **The product runs the code, not the Actors.** The demo calls the Python modules directly, which is right for speed and for offline rehearsal. The Actors are how outside agents and developers reach the same logic, and how an agent could pay per call (`data/claim_check/agent_pay.py`; the real paid run is #347).
- **Zero real claim catches.** The Claim Checker's honest result on real listings is that sellers' titles matched their pages. We show its catches on labelled fixtures and label them as fixtures (SIM).

## What is not ours: the data-gathering Actors

These are other developers' Actors that we call to collect MIRROR listings (`data/mirror/actors.py`, `data/mirror/parts.py`). They are tools we use, not Actors we built, and they must never be counted among ours.

| Actor | Used for |
|---|---|
| `benthepythondev/bestbuy-scraper`, `axlymxp/bestbuy-scraper` | Best Buy asks (two independent families, so a baseline has two dated sources) |
| `sian.agency/microcenter-product-scraper`, `fortuitous_pirate/microcenter-scraper` | Micro Center asks (same two-family reason) |
| `shahidirfan/B-H-Photo-Scraper` | B&H asks |
| `junglee/Amazon-crawler` | Amazon asks (only when Amazon itself is the seller) |
| `caffein.dev/ebay-sold-listings`, `memo23/ebay-search-scraper-ppe` | eBay sold history for the baseline; live eBay asks |
| `apify/website-content-crawler` | Central Computers category pages (a real SF store that never joined: comparison only, never orderable) |
| `kawsar/newegg-product-scraper`, `lulzasaur/pcpartpicker-scraper` | Tried; returned 0 items on Oct 24, so unused |

## What we should do with this

1. **Lead with 1 and 2** when we talk about Actors, and name 3, 4 and 5 for what they are. Say "five published or built Actors" only with the status column beside it.
2. **The injection screen is private.** Make it public, or change its README's Store link to say it is private; until then call it "private on Apify".
3. **Do not claim usage.** Quote the run counts above if asked.
4. **Raise the value of 3, 4 and 5 by using them:** have the advocate call the recall Actor's matcher for the full Build Story parts, show the injection screen blocking the injected listing in the Shield beat (it already does through Shield), and run the readiness report on one real store page in the pitch.
5. **Do not add more Actors for the count.** A sixth would need a product use and a real number before it earns a row here.
