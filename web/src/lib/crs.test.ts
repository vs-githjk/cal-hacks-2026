// Run with: npm test --prefix web (node --test, no extra dependency).
// Fixtures are SIM rows in the supplier_signal shape (docs/changes/0033-A-crs-supplier-signal.md).
import { test } from "node:test";
import assert from "node:assert/strict";
import { CRS_REASON, crsFor } from "./crs.ts";

const NOW = Date.parse("2026-10-24T12:00:00Z");
const sig = (over: Record<string, string> = {}) => ({ supplierId: "seller_1", stability: "verified_stable", checkedAt: "2026-10-24T07:50:12Z", source: "sandbox", ...over });

test("each band shows the fixed reason text; only verified_stable is eligible; not_verified is greyed", () => {
  const ok = crsFor([sig()], "seller_1", NOW)!;
  assert.deepEqual(ok, { band: "verified_stable", reason: CRS_REASON.verified_stable, cached: null, eligible: true, greyed: false });
  const caution = crsFor([sig({ stability: "caution" })], "seller_1", NOW)!;
  assert.deepEqual([caution.reason, caution.eligible, caution.greyed], ["CRS sandbox returned a fraud alert; additional proof is required.", false, false]);
  const no = crsFor([sig({ stability: "not_verified" })], "seller_1", NOW)!;
  assert.deepEqual([no.reason, no.eligible, no.greyed], ["CRS sandbox could not verify the synthetic representative identity.", false, true]);
  assert.equal(CRS_REASON.verified_stable, "Synthetic representative identity verified by CRS sandbox.");
});

test("a recorded result keeps its original time: cached from CRS <time>", () => {
  assert.equal(crsFor([sig({ source: "recorded" })], "seller_1", NOW)!.cached, "cached from CRS 2026-10-24 07:50 UTC");
  assert.equal(crsFor([sig({ source: "sandbox" })], "seller_1", NOW)!.cached, null);
});

test("an unknown band is not_verified; a result older than 24 hours is unavailable, greyed and not eligible", () => {
  assert.equal(crsFor([sig({ stability: "mixed" })], "seller_1", NOW)!.band, "not_verified");
  const old = crsFor([sig({ checkedAt: "2026-10-23T07:50:12Z" })], "seller_1", NOW)!;
  assert.deepEqual([old.band, old.reason, old.eligible, old.greyed], ["unavailable", "CRS sandbox check unavailable; a current recorded result may be used.", false, true]);
});

test("a seller with no signal (trusted individual, exempt) gets no band; the latest row wins", () => {
  assert.equal(crsFor([sig()], "seller_9", NOW), null);
  const two = [sig({ stability: "caution", checkedAt: "2026-10-24T07:00:00Z" }), sig({ checkedAt: "2026-10-24T08:00:00Z" })];
  assert.equal(crsFor(two, "seller_1", NOW)!.band, "verified_stable");
});
