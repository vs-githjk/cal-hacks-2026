# data/ (Lane C)
Apify mirrors, claim-check, fit checker, hosted liar pages, baselines, price feed. Tasks: docs/kickoff/C-data-truth.md.

- `fit_checker/` c2 fit checker (see its README). Tests: `python -m pytest data/tests`.
- `claim_check/` c3 claim check (MOCK, final I/O).
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

Total for the test round: about $0.17 of the $205 credit.
- Return policy: no actor returned it in overview mode. Seller: only eBay and Amazon. Condition: only Best Buy and eBay; first-party stores leave it `unknown` (never guessed).
- Newegg (keywords, then a search URL) and PCPartPicker both returned 0 items; low-use actors, skipped for now.
- Prices are as listed at the snapshot time; show them with the MIRROR badge, URL and date. Do not compare them to a store's claims without a dated baseline (c11).
