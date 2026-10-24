# Bidding Royale: hour-by-hour plan (Fri 20:15 to Sun 09:00 PDT)
Lanes: A Abhinav (agents, Fetch.ai, quality advocate) · B Vedant (market, screens, 3D floor) · C Anoop (data, forecast, quality data) · D Vidyut (Shield, payments, CRS, trust; also integration owner and pitch).
Hard deadline: Sun 09:00 submit on Devpost. Judging Sun 10:30 (whole team at the table, live demo).

| When (PDT) | A Abhinav | B Vedant | C Anoop | D Vidyut | Gate |
|---|---|---|---|---|---|
| Fri 20:15 to 21:30 | Agentverse account, hello agent with Chat Protocol reachable in ASI:One | SpacetimeDB hello module, reducer called from Python; Next.js shell | Run Apify WebstaurantStore and CHEF'STORE actors on 5 items; register USDA key; openFDA recall call | Shield FastAPI skeleton; Stripe test charge on a Visa test card; CRS sandbox call | Every credential requested; every hello works |
| Fri 21:30 to 22:30 | Freeze contracts with everyone (contracts/ + docs/CHANGES.md) | Same | Same; seed the demo restaurant: 25-line order guide, 8 weeks of usage | Same; Trusted Agent Protocol signing spike | Contracts frozen 22:30 |
| Fri 22:30 to Sat 00:30 | Restaurant agent: forecast in, sealed request out; supplier agent template with floor and perks | Auction module (sealed bids, deadline, floor in reducer); owner view reads live state | Forecast v1 (moving average plus trend, reason shown); spec normalizer (grade, pack, case) | /screen with first attack corpus; /check-claim calling C; Payment Protocol commit to Stripe | SpacetimeDB or Convex decided 23:00 |
| Sat 00:30 to 03:00 | Quality advocate v1 (need, spec, freshness, recall, price), Interactive Cards (carousel, review) | Supplier dashboard; bid stream; 2D floor first | Mirrored supplier catalogs for the 25 items; claim checker against our hosted "Honest Hal" and "Shady Sam" pages | CRS supplier signal (private, signal only); mandate and idempotency; hosted liar pages | First real path by 03:00 (mocks allowed for 1 hop) |
| Sat 03:00 | Decide: 2D or 3D floor, Visa VIC go or no-go, cut list | | | | Integration check by Vidyut |
| Sat 03:30 to 07:30 | SLEEP | Integrate, fix | SLEEP | Integrate, fix, demo path runs every 2 hours | Pair 1 sleeps |
| Sat 07:30 to 11:30 | Advocate veto logic, recovery from failed calls, register 6 agents | SLEEP | Measured numbers: price vs baseline on 25 items, forecast error on held-out weeks | SLEEP until 10:00, then restaurant and supplier interviews (2 real ones), docs/INTERVIEWS.md | Pair 2 sleeps |
| Sat 11:30 to 14:00 | Hero loop polish inside ASI:One | Owner view leads with hours and dollars saved; receiving screen | Receiving check: delivery photo vs spec (vision), supplier quality record | Shield console for judges; real-vs-simulated badges; one real order | DEMO PATH GREEN 14:00 on the deployed build; re-judge (10 Sonnet judges) |
| Sat 14:00 to 19:00 | Wind tunnel buyers (with D); voices script | 3D floor with personas (if chosen at 03:00), Cartesia voices | Wind tunnel numbers on held-out set; quality data polish | Hostile agents and catch rate; Hyphenate purchasing ledger (stretch) | Storyboard approved 19:00 |
| Sat 19:00 to 23:00 | Bug fixes; agent addresses in README | Floor polish (no new 3D features after 22:00) | README numbers, REAL_VS_SIMULATED table | Record demo footage 21:00 to 23:00; pitch draft | |
| Sat 23:00 to Sun 03:00 | Rehearsals; edge cases | Rehearsals | Rehearsals | Rough cut of video; Devpost draft | FEATURE FREEZE Sun 03:00 |
| Sun 03:00 to 06:00 | Sleep 03:00 to 05:00 | Fix only | Sleep 03:00 to 05:00 | Final video (under the cap), Devpost written | Devpost complete 06:00 |
| Sun 06:00 to 08:30 | Final rehearsal x3 | Deployed build check | Fallback recordings ready | T-60 health check; submit | SUBMITTED by 08:30 |
| Sun 09:00 | Deadline | | | | |
| Sun 10:30 to 12:30 | Judging: whole team at the table, 3 min pitch, 2 min Q&A | | | | |

Always on: post progress in docs/BOARD.md; PRs into main small and often; the repo watcher checks every 20 minutes and reviews every PR; anything more than 90 minutes behind a gate is flagged to Vidyut.
