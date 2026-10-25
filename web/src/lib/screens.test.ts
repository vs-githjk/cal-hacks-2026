// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { Timestamp } from "spacetimedb";
import { allowanceForBuyer, asOrigin, asSim, bidsFromRows, buyerSession, clusterArrivals, dealFromRows, feedFromRows, goalsForBuyer, stateLabel, latestRound, linesFromRows, originCounts, originMixLabel, reviewFromRows, WHOLE_BUILD_ID, isWholeBuild, roundFromRows, roundTitle, shieldFromRows, vetoFromRows, winningBid } from "./screens.ts";

const ts = (msSinceEpoch: number) => ({ microsSinceUnixEpoch: BigInt(msSinceEpoch) * 1000n }) as unknown as Timestamp;
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

test("#213 originMixLabel names the noun and totals the bids, dropping zero counts from the breakdown", () => {
  assert.equal(originMixLabel({ LIVE: 0, MIRROR: 12, SIM: 6 }), "18 bids · 12 MIRROR · 6 SIM");
  assert.equal(originMixLabel({ LIVE: 1, MIRROR: 0, SIM: 0 }), "1 bid · 1 LIVE");
  assert.equal(originMixLabel({ LIVE: 0, MIRROR: 0, SIM: 0 }), "");
});

test("#213 origin mix counts round.arrivals (one per bid), not seller lines (one per condition line, alt and refused included)", () => {
  const rows = [
    result({ lines: [{ offeredCondition: "new", unitPrice: 1200 }, { offeredCondition: "open-box", unitPrice: 1100 }], landed: 1100, origin: "MIRROR" }),
  ];
  const events = [
    event({ kind: "round_opened", refTable: "round", refId: "round-1", label: "Sealed round open for 6 s" }),
    event({ id: 2n, kind: "bid_sealed", refId: "bid-a", sellerId: "fair-price-pc", origin: "MIRROR", at: ts(T0 + 1000) }),
  ];
  const r = round();
  const lines = linesFromRows(rows, events, r);
  assert.equal(lines.length, 2, "sanity: the bid's two condition lines both show in the seller table");
  assert.equal(originCounts(lines).MIRROR, 2, "seller lines double count a two-line bid, the bug");
  const roundView = roundFromRows(r, events, rows);
  assert.equal(originCounts(roundView.arrivals).MIRROR, 1, "the round's arrivals count the bid once, the fix's data source");
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

test("the whole-build code row (my_pending_approvals, no mandate yet) becomes the same review card, marked as the whole build", () => {
  const build = { mandateHash: "agg-hash-1", mandateId: WHOLE_BUILD_ID, amount: 3412.5, payee: "your whole build (8 parts from 4 sellers)", expiry: ts(T0 + 300_000), code: "amber harbor", failures: 0, locked: false, origin: "LIVE" };
  const r = reviewFromRows([build])!;
  assert.equal(r.code, "amber harbor");
  assert.equal(r.amount, 3412.5);
  assert.equal(r.payee, "your whole build (8 parts from 4 sellers)");
  assert.equal(r.origin, "LIVE");
  assert.equal(isWholeBuild(r), true);
  const deal = reviewFromRows([{ ...build, mandateHash: "h1", mandateId: "mdt-1", payee: "seller-c" }])!;
  assert.equal(isWholeBuild(deal), false);
  assert.equal(reviewFromRows([]), null, "no row, no card: the screen says nothing is waiting");
});

// ---- Task 1: the buyer app only ever shows the paired buyer's own goals.

const roleRow = (role: string, subjectId: string) => ({ role, subjectId });
const goalRow = (over: Record<string, unknown> = {}) => ({
  id: "goal-a1", buyerId: "buyer-a", type: "budget_cap", cap: 1300, deadline: ts(T0 + 86_400_000), state: "ACTIVE", reservedAmount: 0, origin: "SIM", createdAt: ts(T0), ...over,
});
const goalItemRow = (goalId: string, skuSpec: string) => ({ goalId, skuSpec, condition: "new", variant: "", quantity: 1, skippedOwnedPartId: "" });
const allowanceRow = (buyerId: string) => ({ buyerId, perPurchaseLimit: 800, periodLimit: 2000, period: "month", spentThisPeriod: 100, ladderStep: 1 });

test("buyerSession: nothing is a buyer until connected, the roles loaded, and one buyer role says so", () => {
  assert.deepEqual(buyerSession(false, true, [roleRow("buyer", "buyer-a")]), { status: "connecting" });
  assert.deepEqual(buyerSession(true, false, [roleRow("buyer", "buyer-a")]), { status: "connecting" });
  assert.deepEqual(buyerSession(true, true, []), { status: "unpaired" });
  assert.deepEqual(buyerSession(true, true, [roleRow("seller", "seller-a")]), { status: "unpaired" });
  assert.deepEqual(buyerSession(true, true, [roleRow("buyer", "")]), { status: "unpaired" }, "an unknown subject is not an identity");
  assert.deepEqual(buyerSession(true, true, [roleRow("buyer", "buyer-a")]), { status: "buyer", buyerId: "buyer-a" });
});

test("buyerSession: switching from buyer A to buyer B follows the role row, and two different buyers fail closed", () => {
  assert.deepEqual(buyerSession(true, true, [roleRow("buyer", "buyer-b")]), { status: "buyer", buyerId: "buyer-b" });
  assert.deepEqual(buyerSession(true, true, [roleRow("buyer", "buyer-a"), roleRow("buyer", "buyer-a")]), { status: "buyer", buyerId: "buyer-a" });
  assert.deepEqual(buyerSession(true, true, [roleRow("buyer", "buyer-a"), roleRow("buyer", "buyer-b")]), { status: "unpaired" });
});

test("goalsForBuyer: an empty dashboard is an empty list, and an unknown buyer sees nothing", () => {
  assert.deepEqual(goalsForBuyer([], [], undefined, "buyer-a"), []);
  assert.deepEqual(goalsForBuyer([goalRow()], [goalItemRow("goal-a1", "RTX 5070")], allowanceRow("buyer-a"), ""), []);
});

test("goalsForBuyer: buyer B's newer goal never shows for buyer A, and switching shows only B's rows and allowance", () => {
  const goals = [
    goalRow(),
    goalRow({ id: "goal-b1", buyerId: "buyer-b", createdAt: ts(T0 + 5000) }), // newer than A's goal
  ];
  const items = [goalItemRow("goal-a1", "RTX 5070"), goalItemRow("goal-b1", "Ryzen 7 9800X3D")];
  const forA = goalsForBuyer(goals, items, allowanceRow("buyer-a"), "buyer-a");
  assert.deepEqual(forA.map((g) => g.id), ["goal-a1"]);
  assert.match(forA[0]!.text, /RTX 5070/);
  assert.doesNotMatch(forA[0]!.text, /Ryzen/);
  assert.equal(forA[0]!.allowance?.perPurchase, 800);
  const forB = goalsForBuyer(goals, items, allowanceRow("buyer-a"), "buyer-b");
  assert.deepEqual(forB.map((g) => g.id), ["goal-b1"]);
  assert.equal(forB[0]!.allowance, null, "buyer A's allowance row is never attached to buyer B");
});

test("goalsForBuyer: open searches come first, newest first, and a newer finished goal does not hide an active one", () => {
  const goals = [
    goalRow({ id: "old-active", createdAt: ts(T0) }),
    goalRow({ id: "new-done", state: "DONE", createdAt: ts(T0 + 9000) }),
    goalRow({ id: "new-active", state: "HUNTING", createdAt: ts(T0 + 3000) }),
  ];
  assert.deepEqual(goalsForBuyer(goals, [], undefined, "buyer-a").map((g) => g.id), ["new-active", "old-active", "new-done"]);
});

test("allowanceForBuyer: only the paired buyer's own spending rule, else none", () => {
  const rows = [allowanceRow("buyer-a"), { ...allowanceRow("buyer-b"), perPurchaseLimit: 50 }];
  assert.equal(allowanceForBuyer(rows, "buyer-b")?.perPurchase, 50);
  assert.equal(allowanceForBuyer(rows, "buyer-a")?.perPurchase, 800);
  assert.equal(allowanceForBuyer(rows, "buyer-c"), null);
  assert.equal(allowanceForBuyer(rows, ""), null);
  assert.equal(allowanceForBuyer([], "buyer-a"), null);
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

test("winningBid returns the winner even when it is a MIRROR bid", () => {
  const w = winningBid([{ seller: "A", origin: "SIM", won: false }, { seller: "Central Computers", origin: "MIRROR", won: true }]);
  assert.equal(w?.seller, "Central Computers");
  assert.equal(w?.origin, "MIRROR");
});

test("roundTitle turns a build round id into a readable name", () => {
  assert.equal(roundTitle("round-goal-build-1-board-2"), "Motherboard, round 2");
  assert.equal(roundTitle("round-goal-build-3-gpu-1"), "Graphics card, round 1");
  assert.equal(roundTitle("round-1"), null);
  assert.equal(roundTitle("round-goal-build-1-board-x"), null);
});

// ---- The skipped-owned-part line names the part that was skipped, not always the PSU (rehearsal 22:17).

test("goalsForBuyer: each skipped owned part is named by its own id, so the case is never called the PSU", () => {
  const items = [
    { ...goalItemRow("goal-a1", "750 w psu"), skippedOwnedPartId: "owned-psu" },
    { ...goalItemRow("goal-a1", "case (305 mm gpu room)"), skippedOwnedPartId: "owned-case" },
    { ...goalItemRow("goal-a1", "rtx 5070 ti"), skippedOwnedPartId: "" },
  ];
  const [g] = goalsForBuyer([goalRow()], items, undefined, "buyer-a");
  assert.deepEqual(g!.skipped.map((s) => s.part), ["PSU", "case"]);
  assert.equal(g!.skipped[0]!.text, "You already own the PSU, so it is not in this hunt.");
  assert.equal(g!.skipped[1]!.text, "You already own the case, so it is not in this hunt.");
});

test("sealed rounds: an open round has no arrivals yet, and the revealed bid events keep their original arrival moments", () => {
  const open = round({ state: "open", closedAt: undefined, deadline: ts(T0 + 8000), sealedCount: 2 });
  const view = roundFromRows(open, [], []);
  assert.deepEqual(view.arrivals, []);
  assert.equal(view.sealedCount, 2);
  // At close the market writes the bid events stamped with each bid's own sealed time (earlier than closedAt).
  const closed = round({ closedAt: ts(T0 + 8200) });
  const events = [
    event({ id: 20n, kind: "bid_sealed", refId: "bid-a", sellerId: "a", at: ts(T0 + 1000) }),
    event({ id: 21n, kind: "bid_rejected", refId: "bid-b", sellerId: "b", at: ts(T0 + 3000) }),
  ];
  const arrivals = roundFromRows(closed, events, [result({ bidId: "bid-a", persona: "A" }), result({ id: 2n, bidId: "bid-b", persona: "B", rank: 0 })]).arrivals;
  assert.deepEqual(arrivals.map((a) => [a.label, a.atMs, a.refused]), [["A", 1000, false], ["B", 3000, true]]);
});

test("sealed rounds: a knocked-out row held back mid-round (rank 0, landed 0, no lines) renders as out with its reason and no price line", () => {
  const held = result({ id: 7n, bidId: "bid-c", persona: "C", rank: 0, landed: 0, lines: [], reasons: ["knocked out: last placed this stage"] });
  const bids = bidsFromRows([held], [], "round-1");
  assert.equal(bids.length, 1);
  assert.equal(bids[0]!.rank, null);
  assert.equal(bids[0]!.landed, 0);
  assert.equal(bids[0]!.recommendation, "ineligible");
  assert.equal(bids[0]!.why, "knocked out: last placed this stage");
  assert.deepEqual(linesFromRows([held], [], round({ state: "open", closedAt: undefined })), []);
});

// ---- #449 item 3 PL-4: the goal card shows the goal's own state and its latest note, not ACTIVE forever.

test("goalsForBuyer: each goal carries its own state and the text of the latest note written for that goal", () => {
  const goals = [goalRow({ id: "g1", state: "HUNTING" }), goalRow({ id: "g2", state: "FAILED", createdAt: ts(T0 + 1000) })];
  const notes = [
    { id: 1n, goalId: "g1", klass: "state", text: "Goal set. The agent is hunting." },
    { id: 3n, goalId: "g1", klass: "state", text: "Calling you now to approve." },
    { id: 4n, goalId: "g1", klass: "veto", text: "Your advocate vetoed a cheaper bid." },  // a veto note is not the goal's state line
    { id: 2n, goalId: "g2", klass: "state", text: "We could not call you: there is no phone number on your account. Nothing was paid." },
    { id: 9n, goalId: "", klass: "state", text: "Approval denied elsewhere." },
  ];
  const [g1, g2] = goalsForBuyer(goals, [], undefined, "buyer-a", notes); // the open goal sorts first
  assert.equal(g1.state, "HUNTING");
  assert.equal(g1.latestNote, "Calling you now to approve.");
  assert.equal(g2.state, "FAILED");
  assert.match(g2.latestNote ?? "", /no phone number/);
  assert.equal(goalsForBuyer(goals, [], undefined, "buyer-a")[0].latestNote, "", "no notes, no line");
});

test("stateLabel: FAILED and the other states read in plain words", () => {
  assert.equal(stateLabel("FAILED"), "Could not finish");
  assert.equal(stateLabel("HOLD_FOR_CALL"), "Hold for call");
  assert.equal(stateLabel("HUNTING"), "hunting");
});
