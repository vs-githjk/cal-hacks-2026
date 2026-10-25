# Seller Agent-Readiness Report: what do AI shoppers see on your listings?

AI shopping agents are starting to buy for people. They do not look at your photos or read your page the way a person does. They read the structured product data on the page, and when a fact is missing or contradicts the title, they skip the listing or flag it to their buyer. This Actor reads each of your product pages the way such an agent does and tells you, per listing, what it could not read and how to fix it.

## What you get

- One row per listing URL: **blocks**, **warns**, **ready** or **unreadable**, each finding with what an AI shopper sees and the fix.
- Sample row (the default input): `{"url": "https://www.canadacomputers.com/...", "status": "warns", "findings": [{"rule_id": "listing.returns_unknown", "severity": "warns", "fix": "..."}, {"rule_id": "listing.shipping_unknown", ...}]}`
- Price: **$0.02 per listing read**; an unreadable page is free.

Give it your own listing URLs. For each one you get **blocks** (an agent would skip it), **warns** (an agent cannot confirm something), **ready** (nothing found), or **unreadable** (the page could not be fetched, so nothing is known, and it is free). Every finding names the rule, says what an agent sees, links the page, and gives the fix.

It is public on the Apify Store: [anoopibrampur/seller-agent-readiness-report](https://apify.com/anoopibrampur/seller-agent-readiness-report).

It was built for [Fish Market](https://github.com/vs-githjk/cal-hacks-2026), a market where buyer agents compare seller offers. The title-claim, stock and shipping checks are the ones our own buyer agents run; the structured-data checks were added for sellers.

## Real example (the default input)

The default input is a real Canada Computers listing for an MSI RTX 5070 Ti. An Apify run of this Actor on Oct 24 2026 (run `cmaUq7VR6HPKpCHMf`, LIVE fetch of the page) ended with **WARNS: 0 block(s), 2 warning(s); first: listing.returns_unknown**:

- `listing.returns_unknown`: no return policy in the Product data, so an agent cannot compare returns across sellers.
- `listing.shipping_unknown`: no shipping cost an agent can read, so it cannot compute a landed price.

The page's JSON-LD gave the title, price ($1,749.99 CAD), condition (new), stock (sold out) and model number, so no other rule fired. A page changes over time, so a run today may give a different answer.

## What it checks

| Rule | Severity | What an agent sees |
|---|---|---|
| `listing.no_structured_data` | blocks | No schema.org Product data, so price, stock and condition are guesses from page text |
| `listing.price_unreadable` | blocks | Product data with no price an agent can read: it must be a number of at least 0.01, or plain digits such as "1749.99" (no currency sign, no thousands separator), in `offers.price`, `offers.priceSpecification.price` or an AggregateOffer's `lowPrice` |
| `claim.*` | blocks | A title claim (such as "NEW" or "in stock") that the page's own data contradicts |
| `listing.price_range` | warns | An AggregateOffer price range: the lowPrice is read as the price, so an agent cannot tell what this listing costs |
| `listing.currency_unknown` | warns | A price with no three-letter currency code (such as USD) in priceCurrency |
| `listing.condition_unknown` | warns | No item condition, so new and used look the same |
| `listing.stock_unknown` | warns | No availability (a schema.org value such as https://schema.org/InStock), so an agent cannot tell if it ships now |
| `listing.name_unreadable` | warns | No product name as plain text |
| `listing.shipping_unknown` | warns | No shipping cost as a number, so no landed price |
| `listing.returns_unknown` | warns | No return policy in the Product data |
| `listing.model_unknown` | warns | No mpn, gtin or sku, so the exact model cannot be matched to maker specs |

The facts come from the page's schema.org Product JSON-LD. A page with no structured data gets one finding, `listing.no_structured_data`, since nothing else can be read reliably. When several Product blocks are on a page, the one whose `url` or `@id` is the page is read, else the first with `offers`; a Product whose `url` is another page (a related product) is never read. A page whose data cannot be parsed is **unreadable** (free), and so is a bot check (a Cloudflare, Akamai, PerimeterX or DataDome challenge, "Access Denied" or a captcha page) shown instead of the listing.

**What it does not do:** it does not compare your price with other stores, and it does not check whether a part fits a buyer's build. Our dated price data covers too few products to be fair to every seller, so a price verdict would mostly say "no data".

## Input

`listingUrls`: your product page URLs, one per line, up to 200 per run. Each page is fetched once, from public addresses only, with a 2 MB cap and 30 seconds per page. A run stops after 15 minutes; the listings left are not checked and not charged, and the status line says how many.

## Output

One dataset row per listing: `status`, `summary`, the counts of `blocks` and `warns`, the first finding and its fix, every finding (`rule_id`, `severity`, `what_an_agent_sees`, `source_url`, `fix`), `facts_read` (what an agent could read: title, price, currency, condition, stock, shipping, returns), `read_from`, `checked_at` and `origin`. The `origin` is LIVE: one fetch of your page at `checked_at`. The status line gives the run summary, for example `4 listing(s): 1 blocks, 1 warns, 1 ready, 1 unreadable`, and the key-value store's `OUTPUT` record holds every row.

## Pricing

**$0.02 per listing reported** (pay per event, configured in the Apify Console, not in this repo). Apify platform usage is included.

| You check | You pay |
|---|---|
| 1 listing | $0.02 |
| 50 listings | $1.00 |
| 200 listings | $4.00 |
| A page that could not be fetched or read, or a bot check page (unreadable) | free |

Each run also has Apify's run start event of $0.00005. A listing is charged only when its page was read, and it is charged before its row is delivered. When your spending limit is reached, the run stops and the status line says how many listings were not checked. A restarted run never charges a listing twice.

## Use it from your code or an AI agent

**API (one call, results in the response):**

```bash
curl -X POST "https://api.apify.com/v2/acts/anoopibrampur~seller-agent-readiness-report/run-sync-get-dataset-items" \
  -H "Authorization: Bearer YOUR_APIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"listingUrls": ["https://your-store.example/product/123"]}'
```

**AI agents (MCP):** `https://mcp.apify.com?tools=anoopibrampur/seller-agent-readiness-report` adds it as a tool in any MCP client.

## Our other Actors

- [**Listing Claim Checker**](https://apify.com/anoopibrampur/tech-bazaar-claim-check) checks what a seller says (price, stock, condition, warranty, returns) against the live product page.
- [**PC Build Compatibility Checker**](https://apify.com/anoopibrampur/pc-build-compatibility-checker) runs 12 fit rules with maker sources, so a part fits before you buy it.
- [**Electronics Recall Checker**](https://apify.com/anoopibrampur/electronics-recall-checker) checks a product against U.S. CPSC recalls by brand, model and UPC.

## FAQ

**Does "ready" mean agents will buy from me?** No. It means an agent can read the basic facts and no title claim contradicts them. Agents still compare price, seller record and fit.

**Why "warns" and not "fails"?** A warning means an agent cannot confirm something, not that your listing is wrong. Many agents treat an unconfirmed fact as a reason to prefer another seller.

**My page shows the shipping cost. Why does it say unknown?** The Actor reads shipping from `offers.shippingDetails.shippingRate.value` in the Product data. Shipping shown only in page text or at checkout cannot be read reliably.

**Can I check a competitor's page?** The Actor reads any public page, but it is built for your own listings: the findings are fixes for the page owner.

**Is a page fetched more than once?** No. One GET per URL per run. A page that blocks the fetch or needs JavaScript to show its data is reported as unreadable or as having no structured data.

## Source

The code is open: `data/readiness.py` and `data/readiness_actor/` in [vs-githjk/cal-hacks-2026](https://github.com/vs-githjk/cal-hacks-2026). The rules reuse our seller report (`data/seller_report.py`) and the claim checker's page reader.
