# Board history (frozen at Fri 22:30). New lines go in docs/board/<your lane>.md
# Team board (one line per post, newest at the bottom)
Format: `- [HH:MM] lane: what you did or found | @lane ask, if any`

- [20:05] setup: repo scaffolded; lanes A to D have branches; read docs/kickoff/00-shared.md first.
- [20:14] setup: lanes assigned: A Abhinav, B Vedant, C Anoop, D Vidyut. Hour plan in docs/HOUR_PLAN.md. Repo watcher checks every 20 min and reviews every PR.
- [20:15] research: docs/RESEARCH_RESTAURANTS.md has how restaurants order, quality checks, openFDA recalls (no key, use curl -g), a 30-line demo order guide (section 8) and safe on-screen numbers (section 9) | @C use section 8 to seed the demo restaurant
- [20:22] planner: docs/PRODUCT_GTM.md proposes the product core, demo beats (Marlow's), ICP, pricing and cuts; decisions pending with Vidyut (2D vs 3D floor, Hyphenate tier, price, new pitch text)
- [21:45] C: fit_checker and claim_check MOCKS on main path: `from data.fit_checker import check_fit` (SpecCards in, {verdict, reasons, rule_id, checks} out); `from data.claim_check import check_claim` (Claim in, {result, evidence_url, checked_at, method, evidence_hash} out) | @A build a2 against these now
- [21:53] C: c2 fit checker done (11 rules, 31 tests). Frozen 44-build set: 42/43 decided correct, 0 false OK after one rule, 1 uncertain; see data/RESULTS.md. Build specs still need a human spec-page re-check | @A swap the mock: same import, same output plus notes[]
