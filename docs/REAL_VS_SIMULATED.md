# Real versus simulated (update on every merge; this feeds the README and the pitch)

| Component | Status (LIVE, MIRROR, SIM, SANDBOX, RECORDED) | How we know | Owner lane |
|---|---|---|---|
| Restaurant order history | SIM until a real restaurant shares data | | C |
| Supplier catalogs and prices | MIRROR (Apify, dated) | | C |
| Supplier bids | SIM policy over MIRROR prices; LIVE for any real supplier that joins | | A |
| Claim checks | LIVE against our hosted pages; MIRROR for real suppliers | | C |
| CRS supplier stability | SANDBOX (CRS test identities) | | D |
| Payments | SANDBOX (Stripe test mode, Visa test card) | | D |
| Visa Trusted Agent Protocol signatures | LIVE | | D |
| Shield verdicts | LIVE | | D |
