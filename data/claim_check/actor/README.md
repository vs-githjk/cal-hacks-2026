# Tech Bazaar claim check (Apify Actor)

Checks what a seller says about a listing against the live listing page, and returns evidence.
**Results are evidence, not a verdict.** A page we cannot read is `unverified`, never `false`.

Apify Store: https://apify.com/anoopibrampur/tech-bazaar-claim-check

Built for Tech Bazaar (Cal Hacks 2026). Source: https://github.com/vs-githjk/cal-hacks-2026 (`data/claim_check/`).

## Price
$0.01 per claim checked; nothing charged when the page cannot be fetched. Only a verified or false result is charged; an unverified result is always free. (Pay-per-event, one `claim-checked` event per charged claim; a restarted run does not charge a claim twice.)

## What it checks
On real store pages, against the page's schema.org Product JSON-LD:
- **Price**
- **Condition** (new, open-box, refurbished, used)
- **Stock**: schema.org availability InStock, LimitedAvailability, OnlineOnly and InStoreOnly count as in stock; OutOfStock, SoldOut, Discontinued, PreOrder, PreSale and BackOrder count as not available now (the reason names the status the page shows)
- **Warranty** term in months, from the page's JSON-LD `warranty` (WarrantyPromise duration) or a plain "N-year warranty" in the product description; a list of promises counts only when they agree, and values outside 0 to 120 whole months come back `unverified`
- **Returns** window, only when the page's JSON-LD states a schema.org `hasMerchantReturnPolicy` (days, or returns not permitted). None of the store pages we could fetch on Oct 24 publish one, so on those a returns claim comes back `unverified`.

A was-price claim is judged only against price history from our own dated captures (never against anything on the page being checked); without our captures of that URL it is `unverified`.

Not checked on real store pages yet: was-price and socket claims are only checked on our SIM test pages (their listing JSON); on real store pages they come back `unverified`. Shipping is not checked at all yet. The Actor has no price-history input.

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

## Example run on a real store page (MIRROR, 2026-10-24 07:31 UTC)
Apify run `4kespJWmbkHwo0FIA` (build `vIlfeUdPfGEYGPbi1`). Listings:
- Canada Computers: https://www.canadacomputers.com/en/powered-by-nvidia/269441/msi-rtx-5070-ti-16g-shadow-3x-oc-gddr7-triple-fans-rtx-5070-ti-16g-shadow-3x-oc.html
- Micro Center: https://www.microcenter.com/product/696024/msi-nvidia-geforce-rtx-5070-ti-gaming-trio-overclocked-triple-fan-16g-gddr7-pcie-50-graphics-card

Run on Apify against a Canada Computers listing (MSI RTX 5070 Ti 16G Shadow 3X OC, prices in CAD) and one Micro Center listing. The claims are test claims we wrote, not claims made by the stores.

| claim | page | result | evidence |
|---|---|---|---|
| price $1,749.99 | Canada Computers | verified | the page shows $1,749.99 (page JSON-LD) |
| condition new | Canada Computers | verified | the page shows new |
| in stock | Canada Computers | false | differs from the listing at 07:31 UTC: the page shows out of stock |
| in stock | Micro Center | unverified | could not verify: page fetch failed (http 403) |

Large US retailers (Micro Center, Best Buy, B&H, Newegg) usually refuse a plain fetch, so their pages come back `unverified`, never `false`.
