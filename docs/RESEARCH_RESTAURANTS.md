# Research: how independent restaurants buy ingredients, and what Bidding Royale can sell today

Goal G-restaurant-research. Written for Master Planner. Fetched Fri Oct 23 2026, 20:03 to 20:08 PDT. Labels: VERIFIED (primary page read by me in this run, quote or number seen), REPORTED (secondary source or a search summary of a page I could not open), UNRESOLVED (tried, not settled), NOT CHECKED (out of time or access). Lines marked INFERENCE are my reasoning, not a sourced fact.

## Plain summary (read this if nothing else)

1. Independents already run a manual "auction" every week: 76% of operators who use both Sysco and Restaurant Depot use one to negotiate against the other, and 70% got a price cut, credit or service fix by citing a competing option (IRC survey of 200+ independents, Apr to Jun 2026, VERIFIED). Median savings from splitting broadline and cash-and-carry: $10,000 a year per operator (IRC, VERIFIED). Bidding Royale should automate this existing behavior, not invent a new one.
2. The distributor side is already buying AI that reads orders from email, text, voicemail and PDFs (Choco OrderAgent, Burnt YC S25 "Ozai", Pepper $50M Series C in Feb 2026). So a restaurant agent can send orders and quote requests as plain email or text today and the supplier's own system ingests them. No supplier needs to "join an auction" for the first version. Sysco and US Foods will not accept agent bids into a live auction on day one; no precedent found for independents running reverse auctions with broadliners (NOT FOUND, see section 4).
3. Food is about a third of sales (NRA: food and labor each about 33 cents of every sales dollar, VERIFIED, Jul 8 2026), wholesale food prices are up 35% since 2019, and 42% of operators said they were not profitable in 2025 (NRA, VERIFIED). Thin margin plus a 33% line means a 2% to 3% food saving is a large share of profit.
4. What operators pay today for adjacent tools: MarketMan $249 (Starter) and $299 (Growth, the tier with "Smart Ordering") per month (VERIFIED, raised in Aug 2026); MarginEdge $330 per location per month (REPORTED); Orderly from $195 per month (REPORTED); Buyers Edge Platform GPO says it is free and claims 2% to 3% savings (REPORTED). None of the products checked run a cross-supplier auction, and only MarketMan's paid tier advertises automated ordering.
5. Smallest wedge to sell this month (INFERENCE from 1 to 4): a "price check and counter-quote" agent. The owner forwards this week's Sysco or US Foods invoice or order guide (photo or email). The agent normalizes each line by pack size and grade, prices it against public sources (WebstaurantStore is publicly priced and fetchable, VERIFIED; USDA terminal market reports need a free key), and drafts the text to the rep ("Depot has romaine 24 ct at $X, can you match?") or splits the order. The sealed auction is the same engine pointed at suppliers who opt in. Live risk: the Sysco and Restaurant Depot merger ($29.1B, FTC second request, close expected by Q3 2027, REPORTED) would remove the price check operators rely on, which strengthens the pitch.

Quality addendum in one line: quality is enforced at the back door (41F receiving rule, count, look, reject, driver credit memo, or a credit request within 24 hours per a distributor policy, VERIFIED); nobody keeps a per-supplier quality score; openFDA recalls are live, free and keyless (1,049 food enforcement reports in 2026 so far, VERIFIED). So the trust story is: spec check, recall check and a supplier scorecard that can outrank a cheaper bid (sections 7 to 9).

Decision for Vidyut: pitch the wedge as "your agent does the weekly Depot-versus-Sysco comparison and the haggling text for you", with the auction as the scale story. Needs Vidyut's call on whether the demo leads with invoice photo in, counter-quote out.

## 1. How independents buy today

| Fact | State | Source |
|---|---|---|
| 75% of surveyed independents use Restaurant Depot; 26% use Sysco and Restaurant Depot at the same time | VERIFIED | IRC survey PDF, Jun 2026 (link S1) |
| Among dual users, 76% use one supplier as leverage on the other; 70% won a price cut, credit or service improvement by citing a competitor; 56% told a rep they would buy a substandard item elsewhere | VERIFIED | S1 |
| 98% of Restaurant Depot users say walk-in buying saved them in a shortage or emergency; "Broadline delivery does not operate on demand; cash-and-carry does." | VERIFIED | S1 |
| "Food trucks, caterers, and new restaurants without an established credit history typically cannot meet broadline minimums." Cash-and-carry has no minimums and no contract | VERIFIED (advocacy source, quote) | S1 |
| Restaurant Depot serves about 725,000 operators, 167 warehouses in 35 states, about $15.8B revenue; its prices run "approximately 20% below broadline distribution, by Sysco's own published figures" | VERIFIED as IRC's claim; underlying Sysco figure NOT CHECKED | S1 |
| Sysco, US Foods and Performance Food Group are the "big 3" broadliners; Sysco share of North American foodservice distribution put at 17% to 20% | VERIFIED (press, quoting "experts") | Racket, Apr 15 2026 (S2) |
| Sysco dropped delivery minimums for regularly scheduled delivery days from Nov 16 2020, "small, medium and large customers, but most particularly for those small companies" (CEO Kevin Hourican) | VERIFIED (2020); whether it still holds in 2026 is UNRESOLVED (the IRC 2026 text says minimums still bite new and small operators) | CNBC, Nov 12 2020 (S3) |
| Sysco credit: online application with personal guarantee and credit pull; "You will receive your credit terms via email within approximately 24 hours"; the sales rep also receives the terms; references help but are not required; ordering on Sysco Shop opens 72 to 96 hours after submission, card payment possible meanwhile | VERIFIED (FAQ text) for the first three; the 72 to 96 hours and card detail REPORTED (search summary of the same FAQ) | Sysco Shop app support FAQ (S4) |
| Credit terms are per account, not a public standard (no public Net 30 guarantee at US Foods) | REPORTED (vendor blog, tier 3) | Resolve Pay blog (S5) |
| Operators compare weekly by spreadsheet: one has used Sysco and US Foods for about nine years and buys each item wherever it is cheaper that week; another prices "my 3 vendors" in a spreadsheet and finds Restaurant Depot 20% to 30% below US Foods except produce and cheese; another hands the Sysco rep a list to quote, then shows US Foods so they "sharpen their pencil"; one submits the list Tuesday and picks up Wednesday | REPORTED (PMQ Think Tank forum via search summary; direct fetch failed, curl status 000) | PMQ Think Tank (S6) |
| Pizza Today: an operator built one master list of about 580 products and asked every vendor to price against it in the same format, color-coding the cheapest | REPORTED (search summary; page 403 to curl) | Pizza Today (S7) |
| Who orders, how often, channels: owner or kitchen manager, weekly or several times a week, via rep, phone, text, Sysco Shop or MOXe portal, plus walk-in Depot runs | INFERENCE from the rows above and the operator quotes below; no survey with counts found | NOT FOUND (searched: "independent restaurant operators how many distributors primary broadline secondary specialty produce survey percent", web search, Oct 23 2026) |
| Number of suppliers per independent | NOT FOUND (same search; NPD 2016 data covers broadline spend share only: independents about a third of broadline sales) | FSR Magazine, 2016 (S8), REPORTED |

### Operator quotes (real, dated)

- "I worked with Sysco and they sent me poor quality salmon and tried increasing the price after the 2nd delivery. I told my rep I was moving to Restaurant Depot and from then on the quality was good and pricing was lowered to the original quote." Full-service restaurant, San Francisco (IRC survey, Jun 2026, S1, VERIFIED).
- "We would have zero leverage regarding pricing AND service with nowhere to turn for alternatives. US Foods is not able to handle our needs, and Sysco knows that." Full-service restaurant, Louisville KY (S1, VERIFIED).
- "Sysco was continuously missing the spec on our brisket, which is about a $30k per-month spend. When we told them we would go to a local supplier they reacted quickly and credited us for hundreds of pounds in brisket. We purchase all of our spices and honey from the restaurant depot, because all of the broadline suppliers are consistently 50% higher cost." Restaurant, bar and catering, Shakopee MN (S1, VERIFIED). Note: this is exactly the spec-equivalence check the devil's advocate does.
- "Smaller restaurants, you're working with the income you're getting as you're getting it." Althoff, Minneapolis area restaurateur; and "If you look at the same product between every single food purveyor, whether it's Sysco, US Foods, Performance Food Service, Restaurant Depot is the cheapest." Moser, Dahlia's (Racket, Apr 15 2026, S2, VERIFIED).
- "When I owned a cafe, a Coca Cola rep once came by ... I found I could buy other drinks more cheaply from Restaurant Depot and filled the fridges with them." HN commenter, Nov 6 2024 (S9, VERIFIED text; identity unverified).
- Reddit (r/restaurateur, r/KitchenConfidential): NOT CHECKED. reddit.com refuses automated clients (lesson from earlier runs) and the web search returned no Reddit threads. A 10 minute human pass would add voice; the IRC quotes are stronger evidence anyway.

## 2. Pain with numbers

| Number | State | Source |
|---|---|---|
| Pre-pandemic typical independent: food and labor "each accounting for approximately 33 cents of every dollar in sales"; other costs about 29%; pre-tax margin about 5% | VERIFIED | NRA, Jul 8 2026 (S10) |
| Average wholesale food prices up 35% since pre-pandemic; total restaurant expenses up 36% from 2019 to 2026 | VERIFIED | S10 |
| 42% of operators said their restaurant was not profitable in 2025 | VERIFIED | S10 |
| Food cost averaged 30% of sales in June 2026 across 12,000+ restaurants on MarginEdge | REPORTED (search summary; platform sample) | MarginEdge blog (S11) |
| IRC: sector net margins "3 to 5%"; 9,500 restaurant locations lost in 2025 | VERIFIED as IRC's claim | S1 |
| Savings from a second supplier: of 82 operators with a specific figure, median $10,000 a year, mean about $23,000; 61% save $10,000 or more; reported range 1% to 50% of food cost; dual Sysco plus Depot users median $15,000 | VERIFIED (small self-reported sample, n=82) | S1 |
| Time on inventory: Oracle and Technomic study says 66% of independents spend about three hours a week managing inventory; a later write-up of the same study says 32% spend three hours or more | REPORTED, conflicting, 2016 era | Hospitality Tech via search (S12) |
| Time spent ordering specifically (hours per week) | NOT FOUND (searched: "survey restaurant operators time spent ordering inventory hours per week food cost percentage 2025", web search, Oct 23 2026). Ask the two venue restaurants this question; it becomes the pitch number |
| Foodservice surplus food in 2024: 12.5M tons (17.7% of US total), valued at $157B, "equivalent to 14% of foodservice sales"; 78.4% of foodservice food waste went to landfill | VERIFIED | ReFED foodservice fact sheet 2025 (S13). Caution: this includes plate waste and prepared food, not only over-ordering. Top wasted type is prepared foods (11.2M tons) |
| Waste caused by over-ordering specifically | NOT FOUND (ReFED sheet does not split it) |
| Price volatility: operators reported food costs up about 34% year over year (TouchBistro 2025, 600 independents) and 29% (Popmenu 2025) | REPORTED (search summaries of vendor surveys) | S14 |
| Stockouts: 98% of Depot users used walk-in buying to cover a shortage or emergency | VERIFIED | S1 |

## 3. Competitors and adjacent products

| Product | Side | What it does | Price | Forecast | Multi-supplier price compare | Auction | Auto-order | State |
|---|---|---|---|---|---|---|---|---|
| MarketMan | Restaurant | Inventory, recipe costing, AvT, invoice scans (50/mo on Starter), vendor EDI | Starter $249/mo, Growth $299/mo (adds "Smart Ordering", "Order By Recipe", unlimited invoice scans), Enterprise from $449; API add-on $25 to $199/mo by locations | Smart Ordering (par based, details NOT CHECKED) | Not advertised on pricing page | No | Suggested orders on Growth | VERIFIED pricing page; raise from $199/$249 between Aug 10 and Aug 17 2026 (PricingSaaS diff, S15b) |
| MarginEdge | Restaurant | Invoice processing (unlimited), bill pay, recipe costing, inventory and ordering, daily P&L | $330 per location per month (vendor figure via search); raised $80M Series D Aug 2026 | Not checked | Price tracking from invoices (NOT CHECKED in detail) | No | No evidence | REPORTED (S16, S17) |
| Orderly | Restaurant | COGS from invoice lines plus weekly sales, no counts; Food Ops add-on with over-ordering alerts | From $195 per month | Over-ordering alerts | Not stated | No | No | REPORTED (Capterra, S18) |
| xtraCHEF by Toast | Restaurant | Invoice capture and food cost inside Toast | Quote based; listings say from $149/mo | NOT CHECKED | NOT CHECKED | No | NOT CHECKED | REPORTED (S19) |
| BlueCart | Both | Ordering marketplace and supplier storefronts | No price on its pricing page (fetched, no figures); third-party listings $10 to $250/mo | NOT CHECKED | Partial (marketplace) | No | NOT CHECKED | UNRESOLVED |
| Choco | Distributor (since its pivot) | "OrderAgent" captures orders from "emails, PDFs, voicemails, even handwritten notes" into the distributor ERP (page dated Nov 17 2025); SalesHub, CustomerHub | Quote based | n/a | No | No | Supplier side only | VERIFIED product page; funding $33.5M Series A 2019, Series B 2021 at over EUR 500M valuation REPORTED |
| Pepper | Distributor | Ordering, sales, receivables and payments platform for independent distributors; 500+ distributors, about $30B GMV | $50M Series C, Feb 2026, led by Lead Edge Capital | n/a | No | No | Supplier side | REPORTED (MDM 403 to curl, search summary, S20) |
| Burnt (YC S25) | Distributor | Agent "Ozai" monitors emails, calls, voicemails, WhatsApp, fax, decides if a message is an order and enters it into the ERP | NOT CHECKED; YC page links TechCrunch Sep 25 2025 on backing from Steph Curry's VC firm | n/a | No | No | Supplier side | VERIFIED product text (S21); funding REPORTED |
| GrubMarket | Distributor | Sales AI agent that finds customers and generates price sheets (Jun 2026) | n/a | n/a | No | No | No | REPORTED (S22) |
| Buyers Edge Platform | GPO | Rebates from 350+ manufacturers on purchases you already make with your current distributors; 45,000+ locations | "100% free, with no fees, dues, or hidden costs" (site) vs a profile claiming subscription fees; claims 2% to 3% average annual savings | No | No | No (pre-negotiated) | No | REPORTED (S23); fee question UNRESOLVED |
| Kutlerri.ai, Loop AI, Innovorder | Restaurant ops | Agents for delivery sales, marketing spend, prime cost; not supplier ordering | Kutlerri $4M (Sep 2026), Loop AI $14M Series A (Feb 2026), Innovorder EUR 20M (Jun 2026) | n/a | No | No | No | REPORTED (S24) |
| Apicbase, Restaurant365 purchasing, Craftable, Galley | Restaurant | Back-office inventory and purchasing suites | Not on public pages (R365 pricing page fetched, no dollar figures) | NOT CHECKED | NOT CHECKED | No evidence | NOT CHECKED | NOT CHECKED (time) |
| BuyMyOrder | Restaurant | "Restaurants place orders online and distributors compete to lower the price" | n/a | n/a | n/a | Yes (reverse auction) | n/a | REPORTED (Gust profile, prototype stage, one employee, S25). Closest prior art to the auction; no sign of traction |

Bottom line (INFERENCE): money and AI in 2025 to 2026 went to the distributor side (order intake, sales agents). Restaurant-side tools stop at invoices, costing and par-based suggested orders. Nobody checked runs a cross-supplier auction or an agent that negotiates for the restaurant. A funded restaurant-side buying agent startup: NOT FOUND (searched: "AI procurement agent restaurants startup raises 2026 ordering suppliers autonomous", "restaurant AI purchasing agent automatically places orders with distributors 2026 launch independent restaurants startup seed", web search, Oct 23 2026). Saltz (Berlin, agents standardizing supplier emails and PDFs into one marketplace) came up only on a LinkedIn profile, REPORTED tier 4.

## 4. Distributor dynamics: will suppliers take bids from an agent?

- Precedent for reverse auctions in food: institutional and government buyers use them (for example a Connecticut state food procurement with a two-phase reverse auction on cost plus percentage markup per unit across dairy, meat, produce, dry goods), and USPS policy says auctions suit "simple commodity items ... which can be clearly defined" (REPORTED via search, S26). A sanitation-supply trade article says distributors join auctions only for "significant volume" buyers such as universities, chains, large hotels, and fear auctions "diminished the role of the distributor" (REPORTED; adjacent industry, the page fetched but the article body did not extract).
- Independents running reverse auctions with Sysco or US Foods: NOT FOUND (searched: "reverse auction foodservice distributors bid restaurant purchasing precedent independent restaurants suppliers bid", web search, Oct 23 2026).
- What already works (VERIFIED, S1): reps do respond to a credible competing quote. 70% of dual users got a cut, credit or fix by citing an alternative. That is a one-round sealed bid run by hand.
- Sysco is trying to buy Restaurant Depot (Jetro) for $29.1B (Racket, S2, VERIFIED; one tier 4 page says $8.2B, which is the 2015 Sysco and US Foods deal value the FTC blocked, so ignore it). FTC issued a second request (Sysco SEC filings, REPORTED), started civil investigative demands to customers by Aug 27 2026 (MLex, REPORTED), close anticipated by Q3 2027 (CFO Dive, REPORTED). If it closes, independents lose their main price check, which raises the value of an agent that keeps many suppliers in play. If US Foods' CHEF'STORE is the precedent, IRC says prices rose after that acquisition (VERIFIED as IRC claim).
- What makes a supplier say yes (INFERENCE, label in pitch as such): (a) the order arrives in the channel they already process, which is email, text or portal, and Choco and Burnt prove distributors are automating exactly that intake; (b) predictable recurring volume (a weekly forecast is a standing order); (c) drop size and route density over their minimums; (d) a buyer who pays (the CRS stability check runs both ways: suppliers want credit-worthy buyers, see the Sysco personal guarantee and credit pull, S4); (e) no public price race: sealed bids visible only to the buyer protect their list pricing. Smaller specialty and produce suppliers and regional broadliners (Pepper's 500+ customers) are the realistic first bidders, not Sysco.

## 5. Data access realities

| Source | Public or login | Detail | State |
|---|---|---|---|
| WebstaurantStore | Public | Search page returns prices to curl, for example "Romaine Hearts - 48/Case ... Plus Member Price $131.03 / Case $2.73 / Each Regularly $164.49" (fetched 20:07 PDT Oct 23 2026, HTTP 200). Pack size and per-unit price are on the page, which is what spec normalization needs | VERIFIED |
| Sysco Shop, US Foods MOXe | Login | Customer-specific pricing behind an account opened via credit application (Sysco FAQ). Public scraping of contract prices is not possible; the restaurant's own invoice or order guide is the route | VERIFIED for Sysco account process; MOXe NOT CHECKED |
| Restaurant Depot, CHEF'STORE | Membership or store | Not fetched in this run; Lane C's Apify actors are the plan. Check terms of use before scraping | NOT CHECKED |
| USDA AMS My Market News (MARS) API | Free, key required | Base `https://marsapi.ams.usda.gov/services/v1.2/reports`; unauthenticated call returned HTTP 403 at 20:04 PDT (VERIFIED). Key: register with USDA eAuth, then "Show API key" in My Market News; send it as the basic-auth username with blank password (`-u KEY:`); HTTPS only; no browser calls, one key per account (REPORTED, official docs page via search summary; direct fetch timed out). Daily terminal market reports, for example Boston fruit 2285 and vegetables 2286 (REPORTED). eAuth email confirmation takes "within a few hours" (REPORTED), so register now | Mixed, see cells |
| Invoice OCR as the data source | Restaurant owned | The incumbents price on it: MarketMan meters invoice scans (50/mo Starter, unlimited Growth), MarginEdge sells unlimited invoice processing, Orderly computes COGS from invoice lines. An invoice photo gives the restaurant's own contract price, pack size and item code without any supplier login | VERIFIED (MarketMan), REPORTED (others) |

## 6. Smallest wedge a restaurant would pay for this month

What they pay today: MarketMan $249 to $299 per month (VERIFIED), MarginEdge $330 per location (REPORTED), Orderly from $195 (REPORTED), GPO free with 2% to 3% claimed savings (REPORTED). What they gain by hand today: median $10,000 a year from playing two suppliers against each other (VERIFIED, n=82).

Recommended wedge (INFERENCE; depends on no UNRESOLVED fact except willingness to pay, which only the venue interviews can settle):
1. Input: photo or forwarded email of this week's broadline invoice or order guide.
2. Agent: OCR the lines, normalize pack size, grade and case count, and price each against WebstaurantStore (live), USDA terminal reports (baseline) and any supplier the owner names.
3. Output: a list of "same spec, cheaper elsewhere" lines with landed cost, plus a ready-to-send text or email to the rep asking for a match, or a split order. The devil's advocate rejects false matches (the brisket spec story above is the example).
4. Price to test with the two venue restaurants: $99 per month per location (under MarketMan Starter), or 10% to 20% of verified savings. Both are assumptions to put to the interviewees, not sourced prices.
5. The sealed auction and auto-order within limits are the same engine once two or more suppliers accept RFQs by email or text; demo it with opt-in suppliers and label simulated bidders.

Questions for the Sat interviews (docs/INTERVIEWS.md): who places the order and how many hours a week; how many suppliers and which channel each; do you already quote one against another; last time a rep matched a price; would you pay $99 a month or a share of savings.

## 7. Quality: how restaurants judge and enforce it today (addendum from Vidyut)

Plain version: quality is enforced at the back door, in the minute the driver is standing there. The cook checks temperature, looks, counts, and either refuses the case (driver writes a credit memo on the spot) or asks the rep for a credit within about a day. Specs are set by grade (USDA beef grades, U.S. No. 1 produce), pack size and brand. Complaints and credits live in texts, invoices and the chef's memory, not in a per-supplier scorecard. That gap is where the agent earns trust.

| Fact | State | Source |
|---|---|---|
| Food Code receiving rule: refrigerated TCS food at 41F (5C) or below on receipt, unless the law governing distribution sets another temperature (milk, molluscan shellfish); raw shell eggs must arrive in equipment holding ambient air at 45F or below; hot food at 135F or above; "Upon receipt, TCS food shall be free of evidence of previous temperature abuse" | REPORTED (state adoptions of Food Code 3-202.11 via search: South Carolina, Minnesota) | Q1 |
| Supplier credit policy (Baldor, a large Northeast produce and specialty distributor; page updated Oct 20 2026): report problems "with the driver at the time of delivery and/or our Sales team within 24 hours". Reasons listed: poor quality ("blemished, moldy/rotten, expired, frozen item arrived thawed"), damaged, short ("no charge for backordered items"), mis-entered or subbed, mis-picked, incorrect price, recall. "Inform the driver before the delivery is completed. The driver will issue a credit on the spot and provide you with a credit memo." Unsafe items are credited but not taken back | VERIFIED (Zendesk API JSON, 20:12 PDT) | Q2 |
| Spec quality is a lever operators already pull: "Sysco was continuously missing the spec on our brisket ... When we told them we would go to a local supplier they reacted quickly and credited us for hundreds of pounds in brisket" (Shakopee MN); "they sent me poor quality salmon and tried increasing the price after the 2nd delivery" (San Francisco); 56% of dual Sysco and Depot users told a rep they would buy a substandard item elsewhere | VERIFIED | S1 |
| USDA grade standards for vegetables "are voluntary and provide ... a uniform language for describing the quality and condition of commodities"; AMS also publishes Institutional Meat Purchase Specifications (IMPS) and Commercial Item Descriptions | VERIFIED (AMS page, 20:12) | Q3 |
| Beef grade mix, National Beef Quality Audit 2022 (instrument graded): about 8.2% Prime, 74.8% Choice, 15.7% Select, 1.3% other. Grade reflects marbling and maturity, "says nothing about breed, feed or how the animal was raised" | REPORTED (search summary of the NBQA table and press) | Q4 |
| Recall data is live and covers foodservice packs: openFDA food enforcement returned 1,049 reports dated Jan 1 to Oct 23 2026 (Class I 384, Class II 546, Class III 117; data last updated 2026-10-14). A romaine query returned 10 reports since 2024, including an Aug 19 2026 Class I Taylor Farms de Mexico recall for "Potential Cyclospora contamination" on "BLEND LETT/ROM ... 4/5#" foodservice packs distributed to 27 states | VERIFIED (live calls, HTTP 200, 0.50 s, no key, no rate-limit headers returned, 20:12 PDT) | Q5 |
| Per-supplier quality or complaint tracking at independents | NOT FOUND (searched: "chef receiving deliveries reject case credit memo driver sign invoice short shipped quality complaint restaurant", web search, Oct 23 2026). Vendor blogs (Supy) argue that if the receiving record does not capture what arrived, "the credit never exists" (REPORTED, tier 3 to 4) |
| Public supplier review or complaint sources | NOT CHECKED beyond openFDA (time). The restaurant's own credit memos are the better source |
| Shelf life and ripeness windows, origin and certification checks | NOT CHECKED in sources this run. INFERENCE for the demo: the advocate checks pack date or "best by" on receipt, ripeness stage for items like avocados and tomatoes (for example "ripe in 2 to 3 days" against the menu date), country of origin and certifications (organic, MSC) only where the spec demands them |

What the agent should do with quality (INFERENCE, built from the rows above):
1. Spec card per line: grade (Choice, U.S. No. 1), pack (4/5 lb, 48 ct), brand or equal, origin if required, max receiving temperature.
2. Bid check: a cheaper bid at a lower grade or a different pack is flagged "not equivalent" with the reason. Normalize to price per pound or per each.
3. Recall check: every line matched against openFDA enforcement before ordering and on receipt (live, free, no key).
4. Receiving check-in on a phone: temperature, count, photo, accept or reject; reject auto-drafts the credit request inside the 24 hour window.
5. Supplier scorecard: credits, shorts, subs, late drops and spec misses per supplier feed back into the next auction as a quality score next to price. This is the "trust" Visa asked for: the agent prefers the reliable supplier when the price gap is small, and says why.

## 8. Demo model: one believable independent restaurant, one week

Assumptions are labelled. Pack sizes are common foodservice packs; prices are left blank on purpose so Lane C fills them from live sources (WebstaurantStore, USDA terminal reports) with a source badge. Do not invent prices on screen.

Restaurant (INFERENCE, a composite): "Marlow's", a 70 seat full-service American bistro in Oakland, one location, dinner six nights plus weekend brunch. Owner-chef plus a kitchen manager (KM) who does counts and orders. Suppliers: one broadliner (Sysco or US Foods) for dry, dairy, frozen, paper and most protein; one produce house (a regional specialty produce distributor); weekly Restaurant Depot run for gaps and price checks (75% of independents use Depot, S1); a local bakery for bread.

Weekly cycle (INFERENCE unless marked):
- Sunday night: KM counts the walk-in, reach-ins and dry storage against par (par = weekly use plus safety stock, divided by deliveries per week; one guide suggests safety stock of about 20% to 30% of weekly usage, REPORTED, Q6).
- Monday morning: KM builds the broadliner order from the order guide in the supplier portal (Sysco Shop or MOXe) or texts the rep; produce order by text or email to the produce house. Cutoff for next-day delivery is typically the afternoon or evening before (NOT FOUND as a published policy; confirm with the venue restaurants).
- Tuesday and Friday: broadliner deliveries. Produce: Tuesday, Thursday, Saturday. Receiving check at the back door (section 7). One operator in the PMQ forum: list in Tuesday, pickup Wednesday morning (REPORTED, S6).
- Wednesday: Depot run for anything short, cheaper or forgotten.
- Thursday: mid-week top-up order for the weekend.
- Monday after: owner reconciles invoices and credit memos against what was received.

Sample order guide (30 lines; pack sizes typical, illustrative):

| # | Item | Spec | Pack | Unit ordered | Par (units) | Supplier type |
|---|---|---|---|---|---|---|
| 1 | Romaine hearts | U.S. No. 1 | 48 ct case | case | 2 | Produce |
| 2 | Iceberg, chopped | fresh cut | 4/5 lb | case | 1 | Produce |
| 3 | Yellow onions, jumbo | U.S. No. 1 | 50 lb sack | sack | 1 | Produce |
| 4 | Carrots, jumbo | U.S. No. 1 | 50 lb | case | 0.5 | Produce |
| 5 | Roma tomatoes | U.S. No. 1, ripening stage 4 to 5 | 25 lb | case | 2 | Produce |
| 6 | Hass avocados | #2 size 48 ct, ripe in 2 to 3 days | 48 ct | case | 1 | Produce |
| 7 | Lemons | 115 ct | 40 lb approx | case | 1 | Produce |
| 8 | Russet potatoes | U.S. No. 1, 70 ct | 50 lb | case | 2 | Produce |
| 9 | Garlic, peeled | fresh | 5 lb jar | each | 2 | Produce |
| 10 | Italian parsley | fresh | 60 bunch | case | 0.5 | Produce |
| 11 | Mixed greens (spring mix) | fresh | 3 lb | case | 3 | Produce |
| 12 | Chicken breast, boneless skinless | fresh, no added solution | 4/10 lb | case | 2 | Broadline |
| 13 | Beef ribeye roll, lip-on | USDA Choice, IMPS 112A | about 2/14 lb | lb | 50 lb | Broadline |
| 14 | Ground beef 80/20 | fresh | 4/5 lb chubs | case | 2 | Broadline |
| 15 | Atlantic salmon fillet | skin-on, fresh | 10 lb | case | 2 | Broadline or seafood |
| 16 | Bacon, applewood | 14 to 18 slices per lb | 15 lb | case | 1 | Broadline |
| 17 | Large eggs, shell | Grade A | 15 dozen | case | 2 | Broadline |
| 18 | Heavy cream 40% | | 12/1 qt | case | 1 | Broadline |
| 19 | Butter, unsalted | Grade AA | 36/1 lb | case | 0.5 | Broadline |
| 20 | Parmesan, grated | | 4/5 lb | case | 0.5 | Broadline |
| 21 | Cheddar, sharp, shredded | | 4/5 lb | case | 1 | Broadline |
| 22 | Fryer oil, canola | | 35 lb jug | each | 2 | Broadline or Depot |
| 23 | Olive oil, extra virgin | | 6/1 L or 3 L tins | case | 1 | Broadline |
| 24 | All-purpose flour | | 50 lb bag | bag | 1 | Broadline or Depot |
| 25 | Granulated sugar | | 50 lb bag | bag | 0.5 | Broadline or Depot |
| 26 | Kosher salt | | 3 lb box, 9 per case | case | 0.5 | Broadline or Depot |
| 27 | French fries, 3/8 straight cut | frozen | 6/5 lb | case | 3 | Broadline |
| 28 | Rice, long grain | | 25 lb | bag | 1 | Broadline or Depot |
| 29 | Canned tomatoes, crushed | | 6/#10 cans | case | 1 | Broadline |
| 30 | To-go containers, 9x9 hinged | | 200 ct | case | 1 | Broadline or Depot |

Source notes for the table: romaine 48 ct case and chopped iceberg 4/5 lb are VERIFIED on WebstaurantStore (S29) and the 4/5 lb lettuce blend pack appears in the openFDA recall record (Q5). IMPS exists as an AMS spec system (Q3, VERIFIED); the item number 112A for ribeye roll lip-on is from general knowledge, NOT CHECKED in this run. All other packs, pars and stages are INFERENCE for a demo and should be confirmed with one of the two venue restaurants (ask them for a photo of their real order guide; that is the best seed).

Demo beats this supports: Sunday count shows romaine at 0.5 case vs par 2; agent predicts 2 cases from last 4 weeks; three bids come in; one is cheaper but "Romaine, 24 ct" (pack mismatch, flagged); one is from a lot matching an openFDA Class I recall pattern (flagged with the record link); the reliable supplier with zero credits in the scorecard wins at a small premium, and the agent says why.

## 9. Time and money numbers we can put on screen (Visa feedback)

Rule: show the demo restaurant's own computed numbers, with the industry figures below as context. Do not present vendor claims as measured facts.

| Number | Use on screen? | State | Source |
|---|---|---|---|
| Median $10,000 a year saved by splitting broadline and cash-and-carry (n=82); dual Sysco plus Depot users median $15,000 | Yes, as "what operators save doing this by hand" | VERIFIED | S1 |
| 70% got a price cut, credit or service fix by citing a competitor | Yes | VERIFIED | S1 |
| Food about 33% of sales; pre-tax margin about 5% (so a 3% food saving is about 1 point of sales, roughly a fifth of profit; arithmetic from NRA figures) | Yes, as context | VERIFIED inputs; arithmetic mine | S10 |
| Foodservice surplus food worth 14% of foodservice sales (2024) | Context only; includes plate waste | VERIFIED | S13 |
| About 3 hours a week managing inventory (66% of independents) | Context with date "2016"; conflicting 32% figure exists | REPORTED | S12 |
| "Now it takes us 5 minutes, instead of 30" (ordering, customer quote in a Choco survey post, Nov 17 2021) | Yes, as a quote, labelled vendor testimonial | VERIFIED text | Q7 |
| "8.6 hours per week on supplier ordering", attributed to an NRA 2025 report | No. Only on an automation vendor blog; NRA source not found | REPORTED, tier 4, unconfirmed | Q8 |
| Managers 15 to 20 hours a week on manual inventory (SynergySuite) | No, vendor scenario | REPORTED, tier 4 | Q8 |
| Credits recovered on receiving (dollar per week) | Compute from the demo receiving log | NOT FOUND as an industry number |
| Stockout cost | 98% of Depot users used walk-in buying to cover a shortage (S1, VERIFIED); no dollar figure found | partial |

On-screen "saved this week" panel (INFERENCE, all computed from the demo's own data, each with a source badge): minutes spent (agent log vs the KM's stated baseline from the interview), dollars saved vs last invoice price on the same spec, credits captured at receiving, waste avoided (forecast vs par overage), recalls blocked. Ask both venue restaurants for their baseline: "how long does ordering take you each week?" That one number is worth more than any survey above.

### Addendum sources (fetched Oct 23 2026, PDT)
- Q1 Food Code receiving, state adoptions: https://www.law.cornell.edu/regulations/south-carolina/R-61-25-3.202 and https://www.revisor.mn.gov/rules/4626.0165/ (search only). REPORTED.
- Q2 Baldor Specialty Foods, "How can I request a pickup or credit?", updated 2026-10-20: https://help.baldorfood.com/hc/en-us/articles/360024349313 (fetched via /api/v2/help_center/en-us/articles/360024349313.json, HTTP 200, 20:12). VERIFIED.
- Q3 USDA AMS vegetable grades and standards: https://www.ams.usda.gov/grades-standards/vegetables (HTTP 200, 20:12). VERIFIED.
- Q4 National Beef Quality Audit 2022 table: https://academic.oup.com/view-large/527709288 ; Farm Progress https://www.farmprogress.com/beef/how-does-your-steak-grade (search only). REPORTED.
- Q5 openFDA food enforcement: https://api.fda.gov/food/enforcement.json?search=report_date:[20260101+TO+20261023]&count=classification.exact and ...?search=product_description:romaine+AND+report_date:[20240101+TO+20261023]&limit=2 (HTTP 200, 20:12, no key). VERIFIED. Note: use curl -g, or the square brackets glob and the call silently fails.
- Q6 Par level formulas: https://www.wisk.ai/blog/a-wisks-guide-what-are-par-level-inventory ; https://www.upmenu.com/blog/par-level (search only). REPORTED, tier 3 to 4.
- Q7 Choco, time management survey, published 2021-11-17: https://choco.com/us/stories/time-management-restaurants-work-survey (fetched .md, HTTP 200, 20:12). VERIFIED text; vendor source.
- Q8 https://ustechautomations.com/resources/blog/restaurant-supplier-ordering-automation-roi ; https://www.synergysuite.com/?p=13266 (search only). REPORTED, tier 4.

## What this means, what to do

- Planner: lead the pitch with the IRC 76% and $10,000 median numbers and one operator quote; frame Bidding Royale as automating the weekly price check and haggle, with auctions as phase two. Avoid claiming Sysco or US Foods will bid.
- Lane C: register a USDA eAuth account tonight (hours to confirm); WebstaurantStore curl works for public prices; plan invoice-photo ingestion as a first-class data source.
- Lane A: the advocate's spec-equivalence check (grade, pack size, case count) is the differentiator the brisket quote proves; keep it in the main loop.
- Lane A and C: add a recall check (openFDA, curl -g) and a per-supplier scorecard from receiving and credit memos; quality score sits next to price in the auction.
- Demo: seed from the section 8 order guide, but ask a venue restaurant for a photo of its real order guide and its weekly ordering minutes.
- Everyone: never call a real supplier a liar (red-team rule 5); phrase findings as "differs from the listing at time T".

## Not checked

Reddit threads (blocked to automation); Apicbase, Restaurant365, Craftable, Galley, xtraCHEF and BlueCart official pricing and feature pages; US Foods MOXe login and terms; Restaurant Depot and CHEF'STORE price pages and terms of use; MarketMan "Smart Ordering" mechanics; current Sysco minimums in 2026; any time-spent-ordering survey after 2016; the USDA docs page itself (timed out) and a keyed USDA call (no key; smoke call needs Vidyut's OK and a key in an env var).

## Sources (fetched Oct 23 2026, PDT)

- S1 Independent Restaurant Coalition, "Sysco's Acquisition of Restaurant Depot Would Eliminate Independent Restaurants' Last Real Point of Leverage", survey Apr to Jun 2026: https://assets.nationbuilder.com/irc/pages/5026/attachments/original/1783663394/IRC_Sysco_Survey_June_2026.pdf (HTTP 200, 20:07) and https://www.independentrestaurantcoalition.com/survey_finds_three_in_four_operators_rely_on_restaurant_depot_as_a_check_on_broadline_pricing (200, 20:07). VERIFIED. Advocacy source; numbers self-reported.
- S2 Racket, Em Cassel, Apr 15 2026: https://racketmn.com/as-food-giant-sysco-tightens-its-hold-we-asked-local-chefs-and-restaurateurs-how-much-to-worry (200, 20:07). VERIFIED.
- S3 CNBC, Nov 12 2020: https://www.cnbc.com/2020/11/12/sysco-drops-delivery-minimums-helping-restaurants-cope-with-headwinds.html (200, 20:04). VERIFIED.
- S4 Sysco Shop credit application FAQ: https://appsupport.shop.sysco.com/en/articles/4473844-sysco-credit-application-frequently-asked-questions (200, 20:07). VERIFIED.
- S5 Resolve Pay, US Foods payment terms: https://resolvepay.com/blog/us-foods-payment-terms (search only). REPORTED.
- S6 PMQ Think Tank: https://thinktank.pmq.com/t/sysco/6943?page=2 and https://thinktank.pmq.com/t/possibly-looking-for-a-new-food-supplier/13397 (curl 000; search summary). REPORTED.
- S7 Pizza Today vendor management: https://pizzatoday.com/news/restaurant-vendor-management-strategies-that-cut-costs/613817/ (403; search summary). REPORTED.
- S8 FSR Magazine on NPD 2016: https://www.fsrmagazine.com/industry-news/independent-restaurants-increase-spending-broadline-distributors/ (search only). REPORTED.
- S9 Hacker News comment, Nov 6 2024: https://news.ycombinator.com/item?id=42064901 (Algolia API, 20:05). VERIFIED text.
- S10 National Restaurant Association, "Elevated costs continue to pressure restaurant profitability", Jul 8 2026: https://www.restaurant.org/research-and-media/research/restaurant-economic-insights/analysis-commentary/elevated-costs-continue-to-pressure-restaurant-profitability/ (200, 20:07). VERIFIED.
- S11 MarginEdge June 2026 sales metrics: https://www.marginedge.com/blog/june-2026-national-restaurant-sales-metrics (search only). REPORTED.
- S12 Hospitality Tech on Oracle and Technomic: https://hospitalitytech.com/research-reveals-how-operators-manage-labor-inventory-and-loss-prevention (search only). REPORTED.
- S13 ReFED, Food Waste by Sector: Foodservice (2024 data): https://refed.org/downloads/by-sector-foodservice-2025.pdf (200, 20:04, text extracted). VERIFIED.
- S14 TouchBistro 2025 report and Popmenu 2025 study via search: https://www.silicon.co.uk/press-release/touchbistros-2025-state-of-restaurants-report-reveals-89-per-cent-of-u-s-independent-operators-feel-positive-about-the-use-of-ai and https://www.fsrmagazine.com/industry-news/popmenu-study-85-percent-of-restaurants-fighting-harder-for-guests-as-costs-surge-and-demand-softens/ . REPORTED.
- S15 MarketMan pricing: https://www.marketman.com/pricing (200, 20:04). VERIFIED. S15b PricingSaaS diff 2026W34: https://pricingsaas.com/companies/marketman/diffs/2026W34 (200, 20:04). Tier 3.
- S16 MarginEdge pricing via search: https://www.marginedge.com and https://fitsmallbusiness.com/marginedge-review/ . REPORTED.
- S17 MarginEdge $80M Series D: https://technical.ly/entrepreneurship/marginedge-secures-80m-funding-amid-saaspocalypse.md (search only). REPORTED.
- S18 Orderly on Capterra: https://www.capterra.com/p/145549/Orderly/ (search only). REPORTED.
- S19 xtraCHEF listings: https://www.getapp.com/website-ecommerce-software/a/xtrachef/ (search only). REPORTED, tier 4.
- S20 Pepper Series C: https://www.mdm.com/news/technology/ai/pepper-inks-50m-funding-to-provide-independent-food-distributors-with-ai-tools/ (403; search summary). REPORTED.
- S21 Burnt on YC: https://www.ycombinator.com/companies/burnt (200, 20:07). VERIFIED. Choco OrderAgent: https://choco.com/us/stories/suppliers/orderagent-the-ai-order-processing-engine-thats-powering-the-future-of-food-distribution (200, 20:07). VERIFIED. Choco funding: https://techcrunch.com/2019/10/28/choco-raises-33-5m-to-bring-restaurants-and-suppliers-a-modern-ingredient-ordering-platform and https://www.startbase.com/news/gastro-app-choco-sammelt-85-millionen-euro-ein/ (search only). REPORTED.
- S22 GrubMarket sales agent: https://www.digitalcommerce360.com/2026/06/10/grubmarket-ai-agent-for-sales-team/ (search only). REPORTED.
- S23 Buyers Edge Platform: https://buyersedgeplatform.com/blog/buyers-edge-platform-gpo-brands (search only; /join returned 404). REPORTED.
- S24 Kutlerri: https://www.fastcasual.com/news/kutlerriai-raises-4m-to-expand-ai-agents-for-restaurant-sales-costs/ ; Loop AI: https://inc42.com/company/loop-ai/ (search only). REPORTED.
- S25 BuyMyOrder: https://gust.com/companies/buymyorder (search only). REPORTED.
- S26 Reverse auction precedent: https://biznet.ct.gov/SCP_Documents/Bids/49899/Addendum_1.pdf ; https://about.usps.com/manuals/spp/html/spp2_218.htm ; https://cleanlink.com/sm/article.aspx?id=696 (search only, cleanlink body not extracted). REPORTED.
- S27 Sysco and Jetro FTC review: https://www.sec.gov/Archives/edgar/data/0000096021/000110465926110454/tm2625144-15_424b5.htm ; https://www.mlex.com/articles/2518799/sysco-restaurant-depot-deal-draws-scrutiny-as-ftc-queries-third-parties ; https://www.cfodive.com/news/sysco-grants-ceo-interim-cfo-stock-awards-jrd-acquisition/829826/ (search only). REPORTED.
- S28 USDA MARS API: https://marsapi.ams.usda.gov/services/v1.2/reports (403 without key, 20:04, VERIFIED); docs https://mymarketnews.ams.usda.gov/mymarketnews-api/authentication and https://mymarketnews.ams.usda.gov/mars-api/getting-started/basic-instructions (fetch timed out; search summary). REPORTED.
- S29 WebstaurantStore search: https://www.webstaurantstore.com/search/romaine.html (200, 20:07). VERIFIED.

Consistency scan: Sysco and Restaurant Depot deal value $29.1B in S1 and S2 agree; $8.2B (tier 4) is the 2015 deal per S1, discarded. MarketMan $249/$299 on the live page agrees with the S15b diff dated Aug 17 2026. ReFED 17.7% and $157B from the 2025 sheet (an older sheet says 17.9% and $156B; newer used). Oracle 66% vs 32% conflict left as REPORTED, not used in the summary. IRC n: "more than 200" surveyed, 170 estimated savings, 82 gave figures; the median $10,000 is over the 82.

GOAL: G-restaurant-research met (incl. addendum) · due 21:00 PDT · finished 20:14 PDT
COST: about 55 searches and fetches / 25 plus 8 budget (over: 24 web searches, 31 curl or API fetches, 2 WebFetch, 1 HN API script) · 3 files read · 20 commands · 0 sub-agents

CHECKED_AT: Fri Oct 23 20:14 PDT 2026
SUBJECT: web sources listed above; plan/kickoff/00-shared.md (LATEST DIRECTION)
CHECKED: S1 to S29 and Q1 to Q8 as labelled; openFDA live calls; HN Algolia comments API (7 queries)
NOT CHECKED: see "Not checked" above
UNRESOLVED: order cutoff times; per-supplier quality tracking practice; current Sysco minimums in 2026; Buyers Edge fees; BlueCart price; USDA doc page text (timed out); willingness to pay $99/mo (settle at the venue interviews)
