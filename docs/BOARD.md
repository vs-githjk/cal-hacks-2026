# Team board (one line per post, newest at the bottom)
Format: `- [HH:MM] lane: what you did or found | @lane ask, if any`

- [20:05] setup: repo scaffolded; lanes A to D have branches; read docs/kickoff/00-shared.md first.
- [20:14] setup: lanes assigned: A Abhinav, B Vedant, C Anoop, D Vidyut. Hour plan in docs/HOUR_PLAN.md. Repo watcher checks every 20 min and reviews every PR.
- [20:15] research: docs/RESEARCH_RESTAURANTS.md has how restaurants order, quality checks, openFDA recalls (no key, use curl -g), a 30-line demo order guide (section 8) and safe on-screen numbers (section 9) | @C use section 8 to seed the demo restaurant
- [20:22] planner: docs/PRODUCT_GTM.md proposes the product core, demo beats (Marlow's), ICP, pricing and cuts; decisions pending with Vidyut (2D vs 3D floor, Hyphenate tier, price, new pitch text)
- [21:45] C: fit_checker and claim_check MOCKS on main path: `from data.fit_checker import check_fit` (SpecCards in, {verdict, reasons, rule_id, checks} out); `from data.claim_check import check_claim` (Claim in, {result, evidence_url, checked_at, method, evidence_hash} out) | @A build a2 against these now
- [21:53] C: c2 fit checker done (11 rules, 31 tests). Frozen 44-build set: 42/43 decided correct, 0 false OK after one rule, 1 uncertain; see data/RESULTS.md. Build specs still need a human spec-page re-check | @A swap the mock: same import, same output plus notes[]
- [21:55] C: c4 liar pages (SIM) built: Honest Hal and Shady Sam with lie toggle (fake was price, open box as new, wrong socket) + injected page with hidden instruction and payee swap at data/liar_pages/site/shady-sam-gpu-5070ti-injected.html | @D use it for the beat-3 Shield test
- [21:56] C status: DONE c2 fit checker (PR #2), c4 liar pages (PR #4). STUB claim_check (mock, final I/O, PR #1). BLOCKED c1: runner ready (draft PR #3), needs APIFY_TOKEN, then `python -m data.mirror.run_actors`. NEXT: c1 runs, human re-check of fit_builds.json specs, c3 claim-check on the liar pages, c5 merchant sim, c6 Photon spike
- [22:10] C: c1 mirrors ran: 6 of 8 actors work (Micro Center, Best Buy, B&H, eBay sold, eBay live, Amazon), 20 RTX 5070 Ti SpecCards with snapshot ids in data/mirror/snapshots, about $0.17 total; Newegg and PCPartPicker returned 0 items | @A mirrored offers ready for bids
- [22:19] C: c3 claim check real (replaces mock, same import, adds reason). 3 planted lies return false with evidence URLs on the liar pages (localhost); Actor wrapper in data/claim_check/actor, not yet run on Apify | @A swap the mock; a14: ./bundle.sh && apify push from that folder
