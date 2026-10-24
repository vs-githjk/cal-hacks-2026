# Board: Lane B
Append your own lines here only: `- [HH:MM] what you did or need | @who`. Each lane has its own file, so PRs never conflict.
- [20:36] proposed contracts SpecCard, SupplierTerms, OrderPlan, ReceivingEvent, QualityRecord, FloorEvent v2 on lane-b-market-floor (see docs/CHANGES.md) | @A @C @D please object before 22:30
- [20:36] building the 2D sealed bid board first as the data view and fallback, then the 3D floor on top per Vidyut's 20:30 decision; both draw only from floor_events rows
- [21:56] proposed LossReport, Goal, Allowance, origin+source on Bid and Claim in docs/CHANGES.md (also: SpecCard now = C's, FloorEvent kinds extended, supplier_id to seller_id) | @A @D object before 22:30
- [21:58] rename to computer gear done at 01d990b (52 tests green, fee in market/config.ts PROPOSED, fee-never-ranks test), PR #5 to main | @Vidyut review when you can; @C SpecCard on B is now yours byte for byte
