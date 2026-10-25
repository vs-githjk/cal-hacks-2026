// Run with: npm test --prefix web (node --test, no extra dependency).
// Fixtures are SIM rows in the supplier_signal shape (docs/changes/0033-A-crs-supplier-signal.md).
import { test } from "node:test";
import assert from "node:assert/strict";
import { CRS_REASON, crsFor } from "./crs.ts";

const NOW = Date.parse("2026-10-24T12:00:00Z");
const sig = (over: Record<string, string> = {}) => ({ supplierId: "seller_1", stability: "verified_stable", checkedAt: "2026-10-24T07:50:12Z", source: "sandbox", ...over });

test("each band shows the fixed reason text; only verified_stable is eligible; not_verified is greyed", () => {
  const ok = crsFor([sig()], "seller_1", NOW)!;
  assert.deepEqual(ok, { band: "verified_stable", reason: CRS_REASON.verified_stable, cached: null, eligible: true, greyed: false, origin: "LIVE" });
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

// #332: a simulated (or mirror, or live) source is never shown with sandbox-only text, and carries an honest origin chip.
test("#332 a simulated-source row is eligible but never claims the CRS sandbox text; the origin chip is honest", () => {
  const sim = crsFor([sig({ source: "simulated" })], "seller_1", NOW)!;
  assert.equal(sim.band, "verified_stable");
  assert.equal(sim.eligible, true);
  assert.equal(sim.origin, "SIM");
  assert.doesNotMatch(sim.reason, /sandbox/i);

  const live = crsFor([sig({ source: "live" })], "seller_1", NOW)!;
  assert.equal(live.origin, "LIVE");
  assert.doesNotMatch(live.reason, /sandbox/i);

  const mirror = crsFor([sig({ source: "mirror" })], "seller_1", NOW)!;
  assert.equal(mirror.origin, "MIRROR");
  assert.doesNotMatch(mirror.reason, /sandbox/i);

  // sandbox and recorded keep the fixed sandbox text and get an honest origin chip too.
  assert.match(crsFor([sig({ source: "sandbox" })], "seller_1", NOW)!.reason, /sandbox/i);
  assert.equal(crsFor([sig({ source: "sandbox" })], "seller_1", NOW)!.origin, "LIVE");
  assert.match(crsFor([sig({ source: "recorded" })], "seller_1", NOW)!.reason, /sandbox/i);
  assert.equal(crsFor([sig({ source: "recorded" })], "seller_1", NOW)!.origin, "MIRROR");
});

// #332: a future checked_at cannot be "fresh forever" -- a clock cannot run ahead of the server's.
test("#332 a checked_at far in the future is unavailable, not an endless verified_stable", () => {
  const future = crsFor([sig({ checkedAt: "2099-01-01T00:00:00Z" })], "seller_1", NOW)!;
  assert.deepEqual([future.band, future.eligible, future.greyed], ["unavailable", false, true]);
  // a few seconds of clock skew is still fine
  const closeEnough = crsFor([sig({ checkedAt: new Date(NOW + 60_000).toISOString() })], "seller_1", NOW)!;
  assert.equal(closeEnough.band, "verified_stable");
});
