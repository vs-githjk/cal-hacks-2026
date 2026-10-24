# data/ (Lane C)
Apify mirrors, claim-check, fit checker, hosted liar pages, baselines, price feed. Tasks: docs/kickoff/C-data-truth.md.

- `fit_checker/` c2 fit checker (see its README). Tests: `python -m pytest data/tests`.
- `claim_check/` c3 claim check (MOCK, final I/O).
- `fit_builds.json` frozen build set; scores in `RESULTS.md`.

## Data sources and rights
- `docyx/pc-part-dataset` (MIT licence on the repo). **Its data was scraped from PCPartPicker, so the rights to the data itself are unclear; check before shipping it in a product.** We use its field names and rows for normalization tests; it is not committed here.
