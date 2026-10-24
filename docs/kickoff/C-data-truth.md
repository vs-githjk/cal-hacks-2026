# Lane C: Data and truth (Apify, Bright Data, Capital One Nessie)
Paste 00-shared.md first, then this.

You own data/. Goal: real stores and the real web inside the market, and every claim checkable.

Tasks in order:
1. Store mirrors with Apify: through the Apify MCP server (mcp.apify.com: search-actors, call-actor, rag-web-browser, web-fetch) or Store Actors, mirror 10 to 20 real online stores' listings for the demo products (title, price, shipping, return policy, fees, stock, reviews). Package the mirror as our own Apify Actor and publish it (Best Actor, $400).
2. Price history and the open web with Bright Data (MCP server, SERP API, Web Unlocker): best public price now, price history where available, outside reviews, lookalike-shop signals.
3. Claim checker: given a Claim (stock, shipping, fees, returns, price), check it against the live page and return verified, unverified or false with an evidence URL. Shield (Lane D) calls this.
4. Review signals: simple, explainable fake-review indicators with evidence (burst timing, duplicate text), never a black-box score.
5. Capital One Nessie (api.nessieisreal.com, get a key from the Capital One booth): seed demo shoppers with accounts and purchases; expose recent purchases and balance to the advocate ("you bought headphones three weeks ago"). Criteria: completeness, creativity, complexity.
6. Measured numbers for the pitch: on N real products, savings versus the best public price, and how often the advocate's warnings were correct.
Done when: store agents bid from real mirrored data, every claim on screen has a check result and a link, and the README has the measured numbers.

## Latest direction additions
- Supplier catalogs: Apify Store actors exist for WebstaurantStore (parseforge/webstaurantstore-scraper), Sysco (parseforge/sysco-scraper), CHEF'STORE wholesale prices covering Restaurant Depot, Sysco and US Foods (parseforge/restaurant-depot-sysco-us-foods-chef-store-scraper), Instacart and Costco. Test each one in the first hour; record cost per run.
- Market baseline: USDA AMS Market News wholesale prices (public; verify the API and key) plus Bright Data for supplier sites.
- Usage learner (new, you own it): from a seeded order history and weekly counts, predict next week's quantity per item with a simple, explainable model (moving average plus trend, with the reason shown), and measure the error on held-out weeks.
- Spec normalizer: map listings to grade, pack size and case count so bids compare like for like.

## Visa and quality update (Fri 20:20)
- Quality data: openFDA food enforcement and recall API (api.fda.gov/food/enforcement.json, public), USDA grade standards and spec fields, supplier reviews and complaints via Apify and Bright Data, and our own receiving results (rejects, credits) per supplier.
- Receiving check: a vision model compares a delivery photo to the spec (count, size, ripeness, damage); store results as a supplier quality record (a record of events, not an opaque score).
- Measured numbers for the pitch: hours saved per week (ordering time before versus after, from interviews), dollars saved versus baseline, waste avoided from the forecast, quality issues caught.
