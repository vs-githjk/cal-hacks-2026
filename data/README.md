# data/ (Lane C)
Apify mirrors, claim-check, fit checker, hosted liar pages, baselines, price feed. Tasks: docs/kickoff/C-data-truth.md.

- `fit_checker/` c2 fit checker (see its README). Tests: `python -m pytest data/tests`.
- `claim_check/` c3 claim check (real; checks every field a claim states, the worst result wins).
- `fit_builds.json` frozen build set; scores in `RESULTS.md`.

## Data sources and rights
- `docyx/pc-part-dataset` (MIT licence on the repo). **Its data was scraped from PCPartPicker, so the rights to the data itself are unclear; check before shipping it in a product.** We use its field names and rows for normalization tests; it is not committed here.

- `liar_pages/` c4 SIM liar pages: `python -m data.liar_pages.build`, then serve `data/liar_pages/site/` with `python -m http.server` (static, works on any wifi). Hal and Sam, lies off/on per file; `shady-sam-gpu-5070ti-injected.html` carries a hidden instruction and a payee swap for Shield (beat 3). Page facts are in `<script id="listing">` JSON; `price_history.json` (SIM) is the baseline for the fake "was" price.
## c1 Apify mirrors (MIRROR, first test run 2026-10-24, query "RTX 5070 Ti", 3 to 5 items each)
Run: `python -m data.mirror.run_actors [store ...]`; rebuild SpecCards from logged runs at no cost: `--renormalize`. Log: `mirror/runs.json`, raw items: `mirror/raw/`, SpecCards with snapshot id and date: `mirror/snapshots/`.

| store | actor | items | cost this run (USD, Apify usageTotalUsd) | fields returned | status |
|---|---|---|---|---|---|
| newegg | `kawsar/newegg-product-scraper` | 0 | 0 | - | returned 0 items, skipped |
| microcenter | `sian.agency/microcenter-product-scraper` | 3 | 0.09275 | model_number, price, stock, title, url | works |
| bestbuy | `benthepythondev/bestbuy-scraper` | 3 | 0.00755 | condition, model_number, price, title, url, was_price | works |
| bh | `shahidirfan/B-H-Photo-Scraper` | 3 | 0.0035 | model_number, price, shipping, stock, title, url | works |
| ebay_sold | `caffein.dev/ebay-sold-listings` | 5 | 0.0201 | condition, date, price, seller, shipping, title, url | works |
| ebay_live | `memo23/ebay-search-scraper-ppe` | 3 | 0.029 | condition, price, seller, shipping, stock, title, url | works |
| amazon | `junglee/Amazon-crawler` | 3 | 0.015 | price, seller, shipping, stock, title, url | works |
| pcpartpicker | `lulzasaur/pcpartpicker-scraper` | 0 | 0.0002 | - | returned 0 items, skipped |

Second source (provider apify-b, #47):

| store | actor | items | cost this run (USD) | status |
|---|---|---|---|---|
| bestbuy | `axlymxp/bestbuy-scraper` | 3 | 0 | used |
| microcenter | `fortuitous_pirate/microcenter-scraper` | 0 | 0.02 | returned 0 items, no snapshot file |

apify-b re-checks listings the first set already has (Best Buy only); the baseline counts each listing URL once.

Total for the test round: about $0.17 of the $205 credit.

Central Computers (SF), #308: `compass/crawler-google-places` run 6SmKVMYDvJoTjqxwh found the SF stores, and
`apify/website-content-crawler` runs K0YOWTRV573VJkfis and xu69poHiWFOfd54LI read the store's RTX 50 series page; about $0.21 in all.
12 RTX 5070 Ti rows in `mirror/snapshots/centralcomputers-20261024T2112Z.json` (no `runs.json` record, so `--renormalize` never rewrites it).
Condition is `unknown` (the pages do not say); per-store stock is the store's own figure. Central Computers is not a partner.
- Return policy: no actor returned it in overview mode. Seller: only eBay and Amazon. Condition: only Best Buy and eBay; first-party stores leave it `unknown` (never guessed).
- Newegg (keywords, then a search URL) and PCPartPicker both returned 0 items; low-use actors, skipped for now.
- Prices are as listed at the snapshot time; show them with the MIRROR badge, URL and date. Do not compare them to a store's claims without a dated baseline (c11).

## c3 claim check
- `from data.claim_check import check_claim` (final I/O, adds `reason`). Rules: price, was price (vs dated price history), condition, stock, return window, socket (vs maker table). Unreadable page = unverified, never false.
- Done-check (SIM, liar pages served on localhost): open box listed as new, fake was price and wrong socket all return false with evidence URLs; the honest page verifies. Saved in `claim_check/done_check.json`.
- Real store pages: only schema.org JSON-LD is read so far; many stores block plain fetches, which returns unverified.
- Apify Actor wrapper in `claim_check/actor/`, published: https://apify.com/anoopibrampur/tech-bazaar-claim-check

## c11 baselines
- `python3 -m data.baselines` writes `data/baselines/feed.json` (recorded price feed, MIRROR, dated) and prints the RTX 5070 Ti reference. `baseline(sku, at)` needs two dated providers within 24 h; until Bright Data is approved it reports `one_source`. Retail, in-stock, new or unstated asks only; eBay sold and eBay live are separate series, never in the median.
- Second Apify family (provider label `apify-b`, run with `python3 -m data.mirror.run_actors --second <store>`; Best Buy and Micro Center only, other stores print "no second-family actor"): `axlymxp/bestbuy-scraper` (Best Buy, 3 items, $0 logged) and `fortuitous_pirate/microcenter-scraper` (Micro Center, 0 items, $0.02 logged, no snapshot file kept). apify-b re-checked the same Best Buy listings, so the baseline keeps one observation per listing URL and `n` counts distinct listings.
