# Real versus simulated (update on every merge; this feeds the README and the pitch)

| Component | Status (LIVE, MIRROR, SIM, SANDBOX, RECORDED) | How we know | Owner lane |
|---|---|---|---|
| Builder's owned parts (ownership memory) | SIM until a real builder shares their parts; real once told to the agent | | A |
| Seller catalogs and prices (Newegg, Amazon, Best Buy, Micro Center, B&H, eBay) | MIRROR (Apify or Bright Data, dated) | | C |
| Price baseline | MIRROR: eBay sold listings for used, docyx dataset (mid-2025, before the price spike) for the old baseline; both dated | | C |
| Price history series | SIM unless a real source works; labelled on screen | | C |
| Seller bids | SIM seller agents built from real scraped listings (marketplace or used sellers); big-box stores do not bid. Any real seller that joins bids LIVE. | | A |
| Claim checks | LIVE against our hosted pages ("Honest Hal", "Shady Sam"); MIRROR for real stores, in neutral wording | | C |
| Fit checks (socket, RAM, PSU, clearance) | LIVE code over a dated open dataset (docyx/pc-part-dataset, MIT) plus two small tables we wrote | | C |
| CPSC recalls | LIVE API call; a labelled fixture if no real record fits a demo part | | C |
| Seller stability (CRS) | SANDBOX (CRS test identities) | | D |
| Allowance approval and voice call | Auto-approval inside the allowance: LIVE code. Cartesia call: in-browser call first; phone call (Twilio or SIP) TO VERIFY and labelled | | D |
| Payments | SANDBOX (Stripe test mode, Visa test card; no real money) | | D |
| Visa Trusted Agent Protocol signatures | LIVE | | D |
| Visa Intelligent Commerce | Adapter, only with Visa sandbox access | | D |
| Shield verdicts | LIVE | | D |
| Receiving check photos | A real box if we can get one, else labelled sample photos | | C |
| Seller demand and trend dashboard | SIM requests from the wind tunnel plus a public MIRROR signal (best-seller ranks) | | C |
| Wind tunnel builders | SIM by design | | D |
| 3D floor | LIVE state (every character traces to a market row) | | B |
