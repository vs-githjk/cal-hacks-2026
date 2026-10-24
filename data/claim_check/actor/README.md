# Tech Bazaar claim check (Apify Actor)

Checks what a seller says about a listing against the live listing page, and returns evidence.
**Results are evidence, not a verdict.** A page we cannot read is `unverified`, never `false`.

Built for Tech Bazaar (Cal Hacks 2026). Source: https://github.com/vs-githjk/cal-hacks-2026 (`data/claim_check/`).

## What it checks
Against the page's schema.org Product JSON-LD (or the listing JSON on our SIM test pages):
- **Price** and **was price** (a "was $X" claim is checked against the price history you pass in)
- **Condition** (new, open-box, refurbished, used)
- **Stock** (in stock, out of stock)
- **Returns** window and CPU **socket**

Not checked yet: shipping and warranty claims (they come back `unverified`).

## Input
```json
{"claims": [{"id": "c1", "text": "in stock", "kind": "stock", "evidence_url": "https://www.example-store.com/p/123"}]}
```
Optional `field` and `value` on a claim skip text parsing.

## Output (one dataset row per claim)
The claim plus `result` (`verified`, `unverified` or `false`), `evidence_url`, `checked_at` (UTC), `method`, `evidence_hash` (sha256 of the page) and `reason`. Wording is neutral, for example "differs from the listing at time T".

## Safety
Only http and https. Every hop's address must be public (no localhost, private, link-local, cloud metadata or CGNAT), redirects are re-checked (at most 3), pages over 2 MB are refused and requests time out.

## Labels
Results on real store pages are MIRROR (a dated read of a public page). Results on our test pages are SIM. We never call a real store a liar: a mismatch means the page differed at that time.

## Build
`./bundle.sh` copies the checker into `src/data/` (gitignored), then push this folder.
