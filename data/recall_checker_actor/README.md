# Electronics Recall Checker: is this product recalled?

**Check any electronics product against U.S. government recalls in one call.** Give a brand and a product name (with its model number or UPC if you have them). The Actor reads the **U.S. Consumer Product Safety Commission (CPSC)** recall database and returns, for each product:

- **recalled**: a recall names this exact model or UPC;
- **possible**: a recall of the same brand names the same product line or product name, but not this model (a lead to check, never called a match);
- **none**: CPSC answered and no recall of that brand matches;
- **unverified**: no brand was given, nothing to match (no model, product line or product word), or the lookup failed. A failure is never reported as "none".

Every match carries the **recall page on cpsc.gov**, the date, the **hazard**, the **remedy** (refund, repair or replacement) and how many **units** were recalled.

Built for **AI shopping agents**. Our own, [Tech Bazaar](https://github.com/vs-githjk/cal-hacks-2026), vetoes a recalled product before any money moves. It's also useful to resellers, refurbishers, marketplaces checking listings, and anyone buying second-hand electronics.

## Real example (the default input)

Press **Start** with the default form. Here is what it returned, as a dated sample (Oct 24 2026; CPSC can add recalls at any time):

| Product | Status | Why |
|---|---|---|
| Anker PowerCore 10000 A1263 | **recalled** | CPSC recall of Jun 12 2025 names model A1263: "The lithium-ion battery in the power bank can overheat, posing fire and burn hazards". About 1,158,000 units; remedy: a free replacement from Anker |
| Samsung Galaxy Note7 | **recalled** | Two CPSC recalls (Sep 15 and Oct 13 2016) for the Galaxy Note7 battery fire hazard |
| Anker Nano Charger 30W | **none** | No CPSC recall of Anker names this product |

## How matching works

1. The search is by **brand** (required). The brand must appear as a whole word: a search for "Anker" also returns a recall of "Trankerloop" bath seats, and that is never matched to Anker.
2. **Recalled** needs your **UPC** listed on the recall (leading zeros are ignored, so a 12-digit UPC-A matches the same code listed as a 13-digit EAN-13), or a **model token** from your product name (letters and digits, such as `A1263`, `Note7`, `B650E-F`) in the recall's title, product names or model numbers.
3. **Possible** is a lead, never a match: a **product-line number** (digits only, such as `10000`), a **distinctive product word** (such as `Soundcore` or `PowerCore`), a model named only in the recall's description (which may say "this model is NOT affected"), or, for a name made only of generic words like "Power Bank", every one of those words in the recall.
4. Sizes like `10000mAh`, `65W`, `16GB` or `2.4GHz` are read as product lines or ignored, never as model numbers. Spec words like `3-in-1`, `2-pack`, `2-port`, `USB3.0`, `Qi2`, `wifi6` or `2nd` are ignored too.
5. A brand with no model, product line (4+ digits, such as `10000`) or product word is **unverified** and free: nothing was matched, so it can never say "none". This holds even when you give a UPC and it is not found: most recalls list no UPC, so a UPC that is not listed rules nothing out (a UPC that is listed is still **recalled**). A size (`Anker 128GB`, `Anker 20000mAh Power Bank`), a year (`Anker 2024`) or a spec word is not a product signal either, so it never turns a check into "none".
6. Your UPC field and a recall's UPC field may each list several codes (`841234567890, 841234567891`): each code is compared on its own and any one match is **recalled**. Commas, slashes, semicolons and words always separate codes. Spaces and hyphens inside a code (`8 41234 56789 0`) are kept together when the digits fit one barcode (14 or fewer, so `1234 5678` is read as one 8-digit code); a longer run is split into whole barcodes of 8, 12, 13 or 14 digits. A code shorter than 6 digits is ignored.

Add the model number for the most precise answer, and the UPC if you have it. Without a model, the best you can get is "possible" (or "recalled" if the recall lists your UPC).

## Input

One product, in the form or from the API:

```json
{"brand": "Anker", "product": "PowerCore 10000 A1263", "upc": ""}
```

Many products, one per line as `Brand | Product name | UPC` (the UPC is optional):

```json
{"products": ["Samsung | Galaxy Note7", "Anker | Nano Charger 30W", "Acme | Charger X1 | 841234567890"]}
```

## Output

One dataset row per product:

```json
{"id": "p1", "brand": "Anker", "product": "PowerCore 10000 A1263", "status": "recalled",
 "summary": "RECALLED: Anker PowerCore 10000 A1263 matches 1 CPSC recall(s) on model A1263; latest 2025-06-12: More than One Million Anker Power Banks Recalled Due to Fire and Burn Hazards; ...",
 "recall_url": "https://www.cpsc.gov/Recalls/2025/More-than-One-Million-Anker-Power-Banks-Recalled-Due-to-Fire-and-Burn-Hazards-Manufactured-by-Anker-Innovations",
 "recall_date": "2025-06-12", "hazard": "The lithium-ion battery in the power bank can overheat, posing fire and burn hazards. ...",
 "remedy": "Consumers should immediately stop using the recalled power banks and contact Anker Innovations ...",
 "units": "About 1,158,000", "match_on": "model A1263", "matches": [], "possible": [],
 "checked_at": "2026-10-24T20:17:00+00:00", "source_url": "https://www.saferproducts.gov/RestWebServices/Recall?format=json&ProductName=Anker",
 "origin": "MIRROR"}
```

`matches` and `possible` list every recall found, each with its title, date, page, products, hazard, remedy, units and `match_on`. The run's status line gives the summary, for example `3 product(s): 2 recalled, 0 possible, 1 none, 0 unverified`, and the key-value store's `OUTPUT` record holds every row.

## Pricing

**$0.002 per product checked** (pay per event, configured in the Apify Console, not in this repo), and Apify platform usage is included.

| You check | You pay |
|---|---|
| 1 product | $0.002 |
| 100 products | $0.20 |
| 1,000 products | $2.00 |
| A product with no brand, no model or product name, or a failed lookup (unverified) | free |

Each run also has Apify's run start event of $0.00005. A product is charged only when CPSC answered, and it is charged before its row is delivered. When your spending limit is reached, the run stops and the status line says how many products were not checked. A restarted run never charges a product twice.

## Agents can pay per call (experimental)

This is an Apify platform feature, not something this Actor's code sets up, and we have reached its pay wall but not paid through it yet. An AI agent with a stablecoin wallet and **no Apify account** can pay for this Actor itself, through [Apify's Agent General Interface](https://agi.apify.com/AGENTS.md). The agent buys a prepaid, spend-capped token by paying an HTTP 402 challenge: x402 takes USDC on Base, or USDC or USDT on Solana, and MPP takes USDC.e or pathUSD on Tempo. It then runs this Actor with `Authorization: Bearer <token>`. This works because the Actor uses limited permissions.

## Use it from an AI agent or your code

**AI agents (MCP):** `https://mcp.apify.com?tools=anoopibrampur/electronics-recall-checker` adds it as a tool in any MCP client.

**API (one call, results in the response):**

```bash
curl -X POST "https://api.apify.com/v2/acts/anoopibrampur~electronics-recall-checker/run-sync-get-dataset-items" \
  -H "Authorization: Bearer YOUR_APIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"brand": "Anker", "product": "PowerCore 10000 A1263"}'
```

## Our other Actors

- [**Listing Claim Checker**](https://apify.com/anoopibrampur/tech-bazaar-claim-check) checks what a seller says (price, stock, condition, warranty, returns) against the live product page.
- [**PC Build Compatibility Checker**](https://apify.com/anoopibrampur/pc-build-compatibility-checker) runs 12 fit rules with maker sources, so a part fits before you buy it.

## FAQ

**Does "none" mean the product is safe?** No. It means no U.S. CPSC recall of that brand matches this product as of the time shown. It does not cover other countries' regulators, and it does not cover recalls that do not name the model.

**Why does it say "possible" instead of "recalled"?** Because the recall does not name your model. A recall of "PowerCore 10000 A1263" is not a recall of the A1229. We show it as a lead, with the recall page, so you can compare model and serial numbers yourself.

**How fresh is the data?** Each answer is a dated read of the CPSC API, cached per brand for 24 hours within a run's container (MIRROR); `checked_at` says when it was read.

**Can it miss a recall?** Yes. The search asks CPSC for recalls whose product name contains your brand, so a recall whose product names leave the brand out is never fetched. Adding the UPC does not change the search, only the matching.

**What does it fetch?** Only the CPSC recall API (saferproducts.gov). It never visits store pages, so it is fast and never blocked.

## Source

[github.com/vs-githjk/cal-hacks-2026](https://github.com/vs-githjk/cal-hacks-2026), `data/recall_checker.py` and `data/recalls.py`. Labels: results are MIRROR (a dated read of CPSC data). **Building from git alone fails:** run `./bundle.sh` first, which copies the recall code into `src/data/`.
