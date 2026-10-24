# Team board (one line per post, newest at the bottom)
Format: `- [HH:MM] lane: what you did or found | @lane ask, if any`

- [20:05] setup: repo scaffolded; lanes A to D have branches; read docs/kickoff/00-shared.md first.
- [20:14] setup: lanes assigned: A Abhinav, B Vedant, C Anoop, D Vidyut. Hour plan in docs/HOUR_PLAN.md. Repo watcher checks every 20 min and reviews every PR.
- [20:15] research: docs/RESEARCH_RESTAURANTS.md has how restaurants order, quality checks, openFDA recalls (no key, use curl -g), a 30-line demo order guide (section 8) and safe on-screen numbers (section 9) | @C use section 8 to seed the demo restaurant
- [20:22] planner: docs/PRODUCT_GTM.md proposes the product core, demo beats (Marlow's), ICP, pricing and cuts; decisions pending with Vidyut (2D vs 3D floor, Hyphenate tier, price, new pitch text)
- [20:36] B: proposed contracts SpecCard, SupplierTerms, OrderPlan, ReceivingEvent, QualityRecord, FloorEvent v2 on lane-b-market-floor (see docs/CHANGES.md) | @A @C @D please object before 22:30
- [20:36] B: building the 2D sealed bid board first as the data view and fallback, then the 3D floor on top per Vidyut's 20:30 decision; both draw only from floor_events rows
- [21:56] B: proposed LossReport, Goal, Allowance, origin+source on Bid and Claim in docs/CHANGES.md (also: SpecCard now = C's, FloorEvent kinds extended, supplier_id to seller_id) | @A @D object before 22:30
