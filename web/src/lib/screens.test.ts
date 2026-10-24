// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { Timestamp } from "spacetimedb";
import { asOrigin, asSim, bidsFromRows, dealFromRows, feedFromRows, latestRound, linesFromRows, originCounts, reviewFromRows, roundFromRows, shieldFromRows, vetoFromRows } from "./screens.ts";

const ts = (msSinceEpoch: number) => ({ microsSinceUnixEpoch: BigInt(msSinceEpoch) * 1000n }) as unknown as Timestamp;
const T0 = Date.UTC(2026, 9, 24, 9, 0, 0);

const result = (over: Record<string, unknown> = {}) => ({
  id: 1n, roundId: "round-1", bidId: "bid-a", sellerId: "fair-price-pc", persona: "Fair Price PC (SIM)", rank: 1, landed: 1289,
  reasons: [] as string[], lines: [{ offeredCondition: "new", unitPrice: 1289 }], origin: "SIM", source: "https://example.com/fair",
  adjustedTotal: 1289, adjustmentReason: "", ...over,
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

test("bidsFromRows shows the landed price from the row, and the real stored adjusted_total, never a recomputed one", () => {
  const [b] = bidsFromRows([result({ landed: 1247.02, adjustedTotal: 1296.9, adjustmentReason: "open-box condition, +4%" })], [], "round-1");
  assert.equal(b!.landed, 1247.02);
  assert.equal(b!.adjusted, 1296.9);
  assert.equal(b!.adjustedReason, "open-box condition, +4%");
});

test("bidsFromRows never shows an adjusted score for a row that was not ranked", () => {
  const [b] = bidsFromRows([result({ rank: 0, adjustedTotal: 1090, adjustmentReason: "" })], [], "round-1");
  assert.equal(b!.rank, null);
  assert.equal(b!.adjusted, null);
  assert.equal(b!.adjustedReason, "");
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

test("reviewFromRows shows the latest expiring code, with the origin normalized", () => {
  const row = (h: string, exp: number) => ({ mandateHash: h, mandateId: "m", amount: 780, payee: "p", expiry: ts(exp), code: "c", failures: 0, locked: false, origin: "sim" });
  const r = reviewFromRows([row("a", T0), row("b", T0 + 1)])!;
  assert.equal(r.mandateHash, "b");
  assert.equal(r.origin, "SIM");
  assert.equal(reviewFromRows([]), null);
});

test("#191 a ranked row the referee held back (advocate caution) shows as held back with its reason, never as the winner", () => {
  const held = "held back: advocate caution (fit.unconfirmed: card length not on the listing)";
  const rows = [
    result({ id: 1n, bidId: "bid-bb", sellerId: "best-buy", persona: "Best Buy", rank: 1, landed: 1299.99 }),
    result({ id: 2n, bidId: "bid-eb", sellerId: "ebay-235887", persona: "eBay seller", rank: 2, landed: 1036.99, reasons: [held] }),
  ];
  const bids = bidsFromRows(rows, [], "round-1");
  const eb = bids.find((b) => b.seller === "eBay seller")!;
  assert.equal(eb.heldBack, held);
  assert.equal(eb.won, false);
  assert.deepEqual(bids.filter((b) => b.won).map((b) => b.seller), ["Best Buy"]);
  const lines = linesFromRows(rows, [], round());
  assert.deepEqual(lines.find((l) => l.seller === "eBay seller")!.outcome, { kind: "held", rank: 2, note: held });
});

// #191-5: live veto, Shield, approval and receipt cards from my_bid_checks and my_deals (shapes from module_bindings, SIM fixtures).
const check = (over: Record<string, unknown> = {}) => ({
  id: 1n, bidId: "bid-bb", roundId: "round-1", sellerId: "bargain-bin", persona: "Bargain Bin Hardware", bidOrigin: "SIM", kind: "advocate",
  result: "veto", detail: "fit.gpu_length: 336 mm card, your case allows 305 mm", evidenceUrl: "https://bargainbin.example.test/5070ti", origin: "SIM", at: ts(T0), ...over,
});
const deal = (over: Record<string, unknown> = {}) => ({
  mandateHash: "abcdef0123456789", mandateId: "mdt-1", dealId: "round-1:bid-a", amount: 1299.99, payee: "best-buy", expiry: ts(T0 + 600_000),
  withinAllowance: false, origin: "SIM", approvalMethod: "", voiceApprovalId: "", approvedAt: undefined, paymentRef: "", paymentMode: "", paidAt: undefined, ...over,
});

test("#191-5 the latest advocate veto in the round becomes the veto card, with the false claim, rule, source and landed price", () => {
  const checks = [check({ id: 1n, kind: "claim", result: "false", detail: "BRAND NEW, factory sealed", evidenceUrl: "https://x.test/p" }), check({ id: 2n })];
  const v = vetoFromRows(checks, [result({ bidId: "bid-bb", landed: 1199 })], "round-1")!;
  assert.deepEqual({ ...v, checkedAt: undefined }, {
    seller: "Bargain Bin Hardware", origin: "SIM", landed: 1199, claim: "BRAND NEW, factory sealed", finding: "336 mm card, your case allows 305 mm",
    ruleId: "fit.gpu_length", sourceUrl: "https://bargainbin.example.test/5070ti", checkedAt: undefined, checkOrigin: "SIM",
  });
  assert.equal(vetoFromRows([check({ result: "buy" })], [], "round-1"), null);
  assert.equal(vetoFromRows(checks, [], "round-2"), null);
});

test("#191-5 a Shield block becomes the Shield card with its rule ids; fields the market does not store stay absent", () => {
  const s = shieldFromRows([check({ kind: "shield", result: "block", detail: "shield.payee.swap, shield.hidden.instruction", evidenceUrl: "", origin: "LIVE" })], "round-1")!;
  assert.equal(s.verdict, "block");
  assert.deepEqual(s.ruleIds, ["shield.payee.swap", "shield.hidden.instruction"]);
  assert.equal(s.verdictOrigin, "LIVE");
  assert.equal(s.chars, undefined);
  assert.deepEqual(s.evidence, []);
  assert.equal(shieldFromRows([check({ kind: "shield", result: "allow", detail: "" })], "round-1"), null);
});

test("#191-5 my_deals: approval shows only once the call approved it, the receipt only once paid", () => {
  assert.deepEqual(dealFromRows([deal()], 250), { approval: null, receipt: null });
  const approved = dealFromRows([deal({ approvalMethod: "voice_code", voiceApprovalId: "va-1", approvedAt: ts(T0 + 1000) })], 250);
  assert.equal(approved.approval!.attempts[0]!.label, "Approved on the call");
  assert.equal(approved.receipt, null);
  const paid = dealFromRows([deal({ approvalMethod: "voice_code", voiceApprovalId: "va-1", approvedAt: ts(T0 + 1000), paymentRef: "ch_sim_1", paymentMode: "sim", paidAt: ts(T0 + 2000) })], 250);
  assert.equal(paid.receipt!.chargeId, "ch_sim_1");
  assert.equal(paid.receipt!.chargeStatus, "SIM stub, no money moved");
  assert.equal(paid.receipt!.amount, 1299.99);
  assert.equal(paid.receipt!.seller, "best-buy");
});
