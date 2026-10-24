// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { asOrigin, asSim, bidsFromRows, clusterArrivals, feedFromRows, latestRound, linesFromRows, originCounts, originMixLabel, reviewFromRows, roundFromRows } from "./screens.ts";

const ts = (msSinceEpoch: number) => ({ microsSinceUnixEpoch: BigInt(msSinceEpoch) * 1000n }) as any;
const T0 = Date.UTC(2026, 9, 24, 9, 0, 0);

const result = (over: Record<string, unknown> = {}) => ({
  id: 1n, roundId: "round-1", bidId: "bid-a", sellerId: "fair-price-pc", persona: "Fair Price PC (SIM)", rank: 1, landed: 1289,
  reasons: [] as string[], lines: [{ offeredCondition: "new", unitPrice: 1289 }], origin: "SIM", source: "https://example.com/fair", ...over,
});
const event = (over: Record<string, unknown> = {}) => ({
  id: 1n, kind: "bid_sealed", refTable: "bid", refId: "bid-a", sellerId: "fair-price-pc", label: "", origin: "SIM", at: ts(T0), ...over,
});
const round = (over: Record<string, unknown> = {}) => ({
  id: "round-1", needId: "need-1", openedAt: ts(T0), deadline: ts(T0 + 8000), extensions: 0, state: "closed", sealedCount: 2, closedAt: ts(T0 + 8000), origin: "SIM", ...over,
});

test("asOrigin keeps LIVE and MIRROR and turns anything else into SIM", () => {
  assert.equal(asOrigin("LIVE"), "LIVE");
  assert.equal(asOrigin("MIRROR"), "MIRROR");
  for (const o of ["SIM", "", "live", "mirror", "REAL"]) assert.equal(asOrigin(o), "SIM", o);
});

test("asSim relabels every LIVE or MIRROR origin field as SIM, deep, and leaves other fields alone", () => {
  const out = asSim({ origin: "LIVE", landed: 5, rows: [{ origin: "MIRROR", sellerOrigin: "LIVE", note: "LIVE" }], at: new Date(T0) });
  assert.deepEqual(out, { origin: "SIM", landed: 5, rows: [{ origin: "SIM", sellerOrigin: "SIM", note: "LIVE" }], at: new Date(T0) });
});

test("bidsFromRows: a source of just https:// renders the row with no link, and a real URL keeps its link", () => {
  const [bad] = bidsFromRows([result({ source: "https://" })], [], "round-1");
  assert.equal(bad!.sourceUrl, undefined);
  assert.equal(bad!.seller, "Fair Price PC (SIM)");
  const [good] = bidsFromRows([result()], [], "round-1");
  assert.equal(good!.sourceUrl, "https://example.com/fair");
  const [label] = bidsFromRows([result({ source: "sim:fixture" })], [], "round-1");
  assert.equal(label!.sourceUrl, undefined);
});

test("bidsFromRows shows the landed price from the row and never invents an adjusted score", () => {
  const [b] = bidsFromRows([result({ landed: 1247.02 })], [], "round-1");
  assert.equal(b!.landed, 1247.02);
  assert.equal("adjusted" in b!, false);
});

test("bidsFromRows ranks 1, 2, then unranked; filters to the round; the advocate veto blocks the win", () => {
  const rows = [
    result({ id: 3n, bidId: "c", rank: 0, landed: 900, reasons: ["Below the seller's own floor"] }),
    result({ id: 2n, bidId: "b", rank: 2, landed: 1300 }),
    result({ id: 1n, bidId: "a", rank: 1, landed: 1200 }),
    result({ id: 4n, bidId: "z", roundId: "round-0", rank: 1 }),
  ];
  const bids = bidsFromRows(rows, [event({ kind: "advocate_card", refId: "a", label: "Advocate veto (fit.gpu_length)" })], "round-1");
  assert.deepEqual(bids.map((b) => b.rank), [1, 2, null]);
  assert.equal(bids[0]!.recommendation, "veto");
  assert.equal(bids[0]!.won, false);
  assert.equal(bids[1]!.recommendation, "unchecked");
  assert.equal(bids[2]!.recommendation, "refused");
  assert.equal(bids[0]!.rowRef, "round_result/1");
});

test("latestRound picks the most recently opened round", () => {
  assert.equal(latestRound([round({ id: "r1" }), round({ id: "r2", openedAt: ts(T0 + 1) })])!.id, "r2");
  assert.equal(latestRound([]), undefined);
});

test("roundFromRows reads the window from the round_opened label and lists arrivals in time order", () => {
  const events = [
    event({ id: 1n, kind: "round_opened", refTable: "round", refId: "round-1", label: "Sealed round open for 6 s" }),
    event({ id: 3n, kind: "bid_sealed", refId: "bid-b", sellerId: "lowball", at: ts(T0 + 3000) }),
    event({ id: 2n, kind: "bid_sealed", refId: "bid-a", at: ts(T0 + 1000) }),
    event({ id: 4n, kind: "bid_rejected", refId: "bid-c", sellerId: "lowball", at: ts(T0 + 9000) }),
  ];
  const v = roundFromRows(round(), events, [result()]);
  assert.equal(v.windowMs, 6000);
  assert.equal(v.closedMs, 8000);
  assert.equal(v.state, "closed");
  assert.deepEqual(v.arrivals.map((a) => [a.label, a.atMs]), [["Fair Price PC (SIM)", 1000], ["lowball", 3000]]);
});

test("feedFromRows classifies events, keeps notes as SIM and sorts newest first", () => {
  const feed = feedFromRows(
    [
      event({ id: 1n, kind: "auction_closed", label: "Round closed, winner", at: ts(T0) }),
      event({ id: 2n, kind: "verdict", label: "Bazaar Shield: block", at: ts(T0 + 1000) }),
      event({ id: 3n, kind: "verdict", label: "Bazaar Shield: allow", at: ts(T0 + 2000) }),
    ],
    [{ id: 9n, klass: "veto", text: "Your advocate vetoed", at: ts(T0 + 3000) }],
  );
  assert.deepEqual(feed.map((f) => [f.key, f.kind]), [["n9", "veto"], ["e2", "block"], ["e1", "deal"]]);
  assert.equal(feed[0]!.origin, "SIM");
});

test("linesFromRows marks the picked line, alt lines and floor refusals", () => {
  const rows = [result({ lines: [{ offeredCondition: "open-box", unitPrice: 1190 }, { offeredCondition: "new", unitPrice: 1230 }], landed: 1190 })];
  const lines = linesFromRows(rows, [event({ id: 5n, kind: "bid_rejected", refId: "bid-x", sellerId: "lowball", at: ts(T0 + 500) })], round());
  assert.deepEqual(lines.map((l) => [l.condition, l.landed, l.outcome.kind]), [["open-box", 1190, "won"], ["new", 1230, "alt"], ["·", 0, "refused"]]);
});

test("originCounts counts each origin", () => {
  assert.deepEqual(originCounts([{ origin: "SIM" }, { origin: "LIVE" }, { origin: "SIM" }]), { LIVE: 1, MIRROR: 0, SIM: 2 });
});

test("#167 originMixLabel shows the honest mix, dropping zero counts, instead of a single misleading chip", () => {
  assert.equal(originMixLabel({ LIVE: 0, MIRROR: 12, SIM: 6 }), "12 MIRROR · 6 SIM");
  assert.equal(originMixLabel({ LIVE: 1, MIRROR: 0, SIM: 0 }), "1 LIVE");
  assert.equal(originMixLabel({ LIVE: 0, MIRROR: 0, SIM: 0 }), "");
});

test("#167 clusterArrivals keeps every arrival, merging a dense run into one cluster", () => {
  const a = (atMs: number, label = `b${atMs}`) => ({ label, atMs, origin: "MIRROR" as const, refused: false });
  // 18 arrivals inside a 6000 ms window, 17 of them within the first 150 ms (a demo flood), one late.
  const flood = Array.from({ length: 17 }, (_, i) => a(i * 8));
  const clusters = clusterArrivals([...flood, a(5000, "late")], 6000, 0.03);
  assert.equal(clusters.flat().length, 18, "no arrival is dropped");
  assert.equal(clusters.length, 2);
  assert.equal(clusters[0]!.length, 17);
  assert.deepEqual(clusters[1], [a(5000, "late")]);
});

test("#167 clusterArrivals keeps well-spaced arrivals apart, one per cluster", () => {
  const a = (atMs: number) => ({ label: `b${atMs}`, atMs, origin: "SIM" as const, refused: false });
  const clusters = clusterArrivals([a(0), a(1000), a(2000)], 6000, 0.03); // 1000 ms apart, gap threshold 180 ms
  assert.equal(clusters.length, 3);
  assert.ok(clusters.every((c) => c.length === 1));
});

test("clusterArrivals on an empty round is empty, and a single arrival is its own cluster", () => {
  assert.deepEqual(clusterArrivals([], 6000), []);
  const only = [{ label: "b", atMs: 10, origin: "SIM" as const, refused: false }];
  assert.deepEqual(clusterArrivals(only, 6000), [only]);
});

test("reviewFromRows shows the latest expiring code, with the origin normalized", () => {
  const row = (h: string, exp: number) => ({ mandateHash: h, mandateId: "m", amount: 780, payee: "p", expiry: ts(exp), code: "c", failures: 0, locked: false, origin: "sim" });
  const r = reviewFromRows([row("a", T0), row("b", T0 + 1)])!;
  assert.equal(r.mandateHash, "b");
  assert.equal(r.origin, "SIM");
  assert.equal(reviewFromRows([]), null);
});
