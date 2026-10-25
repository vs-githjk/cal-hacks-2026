# Listing Claim Checker: price, stock, condition

**Checks a seller's claim against the live listing page.** Paste a product page and what the seller says about it ("price $1,749.99", "new", "in stock"). The Actor reads the live page and returns, for every claim, **verified**, **false** or **unverified**, with the evidence: the page URL, the time it was read and a sha256 hash of the page.

## What you get

- One row per claim: **verified**, **false** or **unverified**, with the page URL, the time it was read and a sha256 of the page.
- Sample row (from the dated run below): `{"text": "in stock", "result": "false", "reason": "claim says in stock; differs from the listing ...: the page shows out of stock", "evidence_url": "https://www.canadacomputers.com/...", "evidence_hash": "sha256 of the page", "checked_at": "2026-10-24T18:28:40+00:00"}`
- Price: **$0.01 per claim** that comes back verified or false; unverified is free (plus Apify's $0.00005 run start).

Built for **AI shopping agents** (our own, [Fish Market](https://github.com/vs-githjk/fish-market-nothing-fishy), uses it to catch sellers whose words do not match their listing before money moves), and useful to marketplaces, price-match teams and anyone who buys on someone else's word.

**Results are evidence, not a verdict.** A page we cannot read is `unverified`, never `false`, and the wording is neutral: a mismatch means "the page differed at that time", never that a store lied.

## What it checks

| Claim | Read from the page | Example claim text |
|---|---|---|
| **Price** | schema.org Product JSON-LD offer price and `priceCurrency` | `price $1,749.99` |
| **Condition** | schema.org itemCondition: New is new, Used and Damaged are used, Refurbished is refurbished | `new`, `refurbished`, `used` |
| **Stock** | schema.org availability (InStock, OutOfStock, PreOrder, BackOrder, ...) | `in stock` |
| **Warranty** | JSON-LD `warranty`, or "N-year warranty" in the description | `2-year warranty` |
| **Returns** | JSON-LD `hasMerchantReturnPolicy` | `30-day returns` |

A price claim is read as USD unless it names another currency (for example `C$1,749.99`). A CAD or other non-USD page leaves a `$` price claim **unverified**, with both currencies named in the reason; it is never `false` or `verified`.

schema.org has no open-box condition, so an `open-box` claim can never be confirmed from the page: it is compared with what the page states (a page marked new gives `false`, "differs from the listing").

One claim line can state several things ("new, in stock, $1,749.99"). All of them are checked, and the line is `false` if any one differs from the page.

## How to use it

1. Paste the **product page URL**.
2. Add the **claims**, one per line, as the seller wrote them.
3. Run. Each claim becomes one row in the results table, and the run's status line sums it up, for example `3 claim(s): 2 verified, 1 false, 0 unverified`. If your spending limit stops a run early, the line says how many claims were not checked.

To check many listings in one run, use **Batch** (advanced): a list of `{id, text, evidence_url}`, each with its own page.

## Input example

```json
{
  "listingUrl": "https://www.canadacomputers.com/en/powered-by-nvidia/269441/msi-rtx-5070-ti-16g-shadow-3x-oc-gddr7-triple-fans-rtx-5070-ti-16g-shadow-3x-oc.html",
  "claimTexts": ["price $1,749.99", "new", "in stock"]
}
```

## Output example

**A dated sample of one run** (Oct 24 2026, 18:28 UTC), not what a run returns today: prices and stock change, and every run reads the page again. The claims are test claims we wrote, not the store's.

| Claim | Result | Reason |
|---|---|---|
| price $1,749.99 | verified | the page shows $1,749.99 |
| new | verified | the page shows new |
| in stock | **false** | claim says in stock; differs from the listing at 2026-10-24T18:28:40+00:00: the page shows out of stock |

Each dataset row is the claim plus:

```json
{
  "id": "c3",
  "text": "in stock",
  "evidence_url": "https://www.canadacomputers.com/en/powered-by-nvidia/269441/...",
  "result": "false",
  "reason": "claim says in stock; differs from the listing at 2026-10-24T18:28:40+00:00: the page shows out of stock",
  "checked_at": "2026-10-24T18:28:40+00:00",
  "method": "fetched page, page JSON-LD, stock rule",
  "evidence_hash": "sha256 of the page bytes"
}
```

The price row above was verified before the Actor read `priceCurrency`. This Canada Computers page prices in CAD (saved copy: `data/claim_check/fixtures/mirror-canadacomputers-269441.html`), so the same `price $1,749.99` claim now comes back unverified. The prefilled example input uses this page.

The key-value store's `OUTPUT` record holds the summary and all rows together.

## Use it from an AI agent or your code

**AI agents (MCP):** add the Actor to any MCP client through Apify's MCP server, `https://mcp.apify.com?tools=anoopibrampur/tech-bazaar-claim-check`. The agent passes a page and claims and gets the rows back as a tool result.

**API (one call, results in the response):**

```bash
curl -X POST "https://api.apify.com/v2/acts/anoopibrampur~tech-bazaar-claim-check/run-sync-get-dataset-items" \
  -H "Authorization: Bearer YOUR_APIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"listingUrl": "https://shop.example/product/123", "claimTexts": ["price $99.99", "in stock"]}'
```

It also works with Apify integrations (webhooks, Make, Zapier, n8n) like any Actor.

## Pricing

**$0.01 per claim checked** (pay per event), and Apify platform usage is included.

| You check | You pay |
|---|---|
| 1 claim (verified or false) | $0.01 |
| 100 claims | $1.00 |
| 1,000 claims | $10.00 |
| An `unverified` claim (page blocked, unreadable, or no data to judge) | free |

Each run also has Apify's run start event of $0.00005. Only a `verified` or `false` result is charged, and a restarted run never charges a claim twice. You can cap the spend per run; the Actor stops at your limit and the status line says how many claims were not checked.

## Agents can pay per call (experimental)

An AI agent with a stablecoin wallet and **no Apify account** can pay for this Actor itself, through [Apify's Agent General Interface](https://agi.apify.com/AGENTS.md):

1. The agent asks for a prepaid token: `GET https://agi.apify.com/protocols/x402/prepaid-tokens?amount=1&currency=usd` answers **HTTP 402** with a payment challenge. x402 takes USDC on Base, or USDC or USDT on Solana. MPP (`/protocols/mpp/...`) takes USDC.e or pathUSD on Tempo, or USDC or USDT on Solana.
2. The agent's wallet pays it (for example `npx awal x402 pay ...`, `mppx ...` or `pay.sh`), and Apify returns a token with a hard spend cap: at least $1, it expires after 14 days, and unused balance is not refunded.
3. The agent runs this Actor with `Authorization: Bearer <token>`, and each claim is metered against that balance. This works because the Actor uses limited permissions.

**What we have verified (Oct 24 2026):** our probe, [`data/claim_check/agent_pay_probe.py`](https://github.com/vs-githjk/fish-market-nothing-fishy/blob/main/data/claim_check/agent_pay_probe.py), sends unpaid requests only and reaches the 402 pay wall for a prepaid token (x402 and MPP) and for a proxied run of this Actor ($1.00 USDC on Base). Its saved output is [`data/claim_check/agent_pay_probe.txt`](https://github.com/vs-githjk/fish-market-nothing-fishy/blob/main/data/claim_check/agent_pay_probe.txt). That is *reached, not paid*. This section will say LIVE only after a real paid run.

## Our other Actor

- [**PC Build Compatibility Checker: will these parts fit?**](https://apify.com/anoopibrampur/pc-build-compatibility-checker) runs 12 fit rules (socket, RAM, PSU wattage and cables, GPU length, cooler height, form factors) with maker sources, so you know the part you are about to buy fits the rest of the build.

## Good to know

- **Big US retailers often block plain fetches** (Micro Center, Best Buy, B&H, Newegg usually answer 403). Those claims come back `unverified` and free, never `false`. Store pages that publish schema.org Product data work best.
- **Was-price ("was $1,999") claims** are not judged from the page being checked, because a page can state any was-price. Without independent dated price history they come back `unverified`.
- **Shipping** claims are not checked yet.
- **Safety:** only http and https; every hop must be a public address (no localhost, private, link-local, cloud metadata or CGNAT); redirects are re-checked (at most 3); pages over 2 MB are refused; requests time out.

## FAQ

**Why "unverified" instead of "false" when a page is blocked?** Because we did not see the page. Calling a claim false needs evidence, so we only say false when the page we read says otherwise.

**Can I prove later what the page said?** Each row has the page's sha256 hash and the time it was read. If you keep the page, the hash shows it is the same one we checked.

**Does it work on any store?** Any public page with schema.org Product data (most shops publish it for search engines). Pages without it come back `unverified`.

## Labels

Results on real store pages are MIRROR (a dated read of a public page). Source: [github.com/vs-githjk/fish-market-nothing-fishy](https://github.com/vs-githjk/fish-market-nothing-fishy), `data/claim_check/`. Developers: `./bundle.sh` copies the checker into `src/data/` before a push.
