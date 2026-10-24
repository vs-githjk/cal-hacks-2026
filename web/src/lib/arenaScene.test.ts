// Run with: npm test --prefix web (node --test, no extra dependency).
// Fixtures are SIM rows in the shape the market writes (round, seller_needs, round_result, floor_event), reasons as close_round writes them.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  IDLE, MAX_SEQUENCE_MS, offerKey, playback, projectArenaScene,
  type ArenaRows, type ArenaScene, type EventRow, type LineRow, type NeedRow, type Playback, type ResultRow, type RoundRow,
} from "./arenaScene.ts";
import { SAMPLES } from "./arenaFixture.ts";

// ---- row builders

const ts = (ms: number) => ({ microsSinceUnixEpoch: BigInt(ms) * 1000n });
const round = (over: Partial<RoundRow> = {}): RoundRow => ({ id: "r1", needId: "n1", openedAt: ts(1000), deadline: ts(91_000), state: "open", sealedCount: 0, origin: "SIM", ...over });
const need = (over: Partial<NeedRow> = {}): NeedRow => ({ roundId: "r1", skuSpec: "rtx 5070 ti", condition: "new", quantity: 1, unit: "each", ...over });
const line = (over: Partial<LineRow> = {}): LineRow => ({ skuSpec: "rtx 5070 ti", offeredSpec: "rtx 5070 ti", offeredCondition: "new", unitPrice: 1000, quantity: 1, ...over });

let nextId = 1n;
const result = (bid: string, over: Partial<ResultRow> = {}): ResultRow => ({
  id: nextId++, roundId: "r1", bidId: bid, sellerId: `s-${bid}`, persona: `Seller ${bid}`, rank: 0, landed: 1000, reasons: [], lines: [line()], origin: "SIM", source: "", ...over,
});
const ranked = (bid: string, rank: number, landed = 1000 + rank, over: Partial<ResultRow> = {}) => result(bid, { rank, landed, ...over });
const event = (kind: string, refId: string, over: Partial<EventRow> = {}): EventRow => ({
  id: nextId++, kind, refTable: kind === "auction_closed" || kind === "round_opened" ? "round" : "bid", refId, sellerId: "", label: kind, origin: "SIM", at: ts(2000), ...over,
});
const closedBy = (sellerId: string, roundId = "r1") => event("auction_closed", roundId, { sellerId, label: sellerId ? "Round closed: 1 ranked, 0 out" : "Round closed: no eligible bid" });
const rows = (over: Partial<ArenaRows> = {}): ArenaRows => ({ rounds: [], needs: [], results: [], events: [], ...over });

const VETO = "Advocate veto (fit.gpu_length: The card is 336 mm; your case allows 305 mm) [source: https://specs.example.test/card]";
const SHIELD = "Bazaar Shield block: shield.override.instruction";

/** One closed round: ranked winner + runner-up, a Shield block, a veto and a below-floor refusal. */
function closedRows(over: Partial<ArenaRows> = {}): ArenaRows {
  const results = [
    ranked("b-win", 1, 1299.99, { sellerId: "win", persona: "Winner Co", lines: [line({ offeredSpec: "asus prime rtx 5070 ti oc" })] }),
    ranked("b-second", 2, 1247.02, { sellerId: "second", persona: "Second Co" }),
    result("b-veto", { sellerId: "veto", persona: "Veto Co", landed: 1199, reasons: [VETO] }),
    result("b-shield", { sellerId: "shield", persona: "Shield Co", landed: 1150, reasons: [SHIELD] }),
    result("b-floor", { sellerId: "floor", persona: "Floor Co", landed: 1090, reasons: ["below this seller floor"] }),
  ];
  return rows({ rounds: [round({ state: "closed", sealedCount: 5 })], results, events: [closedBy("win")], ...over });
}

const dashes = new RegExp("[" + [0x2012, 0x2013, 0x2014, 0x2015].map((c) => String.fromCharCode(c)).join("") + "]");
const knockedIds = (s: ArenaScene) => s.beats.flatMap((b) => b.knocked.map((k) => k.id));

// ---- waiting, round choice, scope

test("no rounds: waiting, everything empty", () => {
  const s = projectArenaScene(rows());
  assert.deepEqual(s, { roundId: null, sample: false, phase: "waiting", requestLabel: "", sealedCount: 0, deadline: null, offers: [], beats: [], winnerBidId: null, problem: null });
  assert.equal(projectArenaScene(rows(), { sample: true }).sample, true);
});

test("the latest round by openedAt is the scene, whatever the row order", () => {
  const old = round({ id: "r-old", openedAt: ts(1000), state: "closed" });
  const fresh = round({ id: "r-new", openedAt: ts(5000), deadline: ts(95_000), sealedCount: 2 });
  for (const rounds of [[old, fresh], [fresh, old]]) {
    const s = projectArenaScene(rows({ rounds }));
    assert.equal(s.roundId, "r-new");
    assert.equal(s.phase, "open");
    assert.equal(s.sealedCount, 2);
    assert.equal(s.deadline!.getTime(), 95_000);
  }
});

test("round scope: another round's results, needs and events never leak into this round", () => {
  const rounds = [round({ id: "r-old", openedAt: ts(1000), state: "closed" }), round({ id: "r1", openedAt: ts(9000), state: "closed", sealedCount: 2 })];
  const results = [
    ranked("b-new", 1, 500, { sellerId: "new" }),
    ranked("b-old", 1, 1, { roundId: "r-old", sellerId: "old", persona: "Old Co" }),
    ranked("b-old2", 2, 2, { roundId: "r-old", sellerId: "old2" }),
  ];
  const events = [
    closedBy("old", "r-old"), closedBy("new"),
    event("bid_sealed", "b-old", { sellerId: "old" }), event("bid_sealed", "b-new", { sellerId: "new" }),
  ];
  const s = projectArenaScene(rows({ rounds, results, needs: [need({ roundId: "r-old", skuSpec: "ssd" })], events }));
  assert.equal(s.phase, "closed");
  assert.equal(s.winnerBidId, "b-new");
  assert.deepEqual(s.offers.map((o) => o.bidId), ["b-new"]);
  assert.deepEqual(s.offers[0]!.events.map((e) => e.kind), ["bid_sealed"]);
  assert.equal(s.requestLabel, "RTX 5070 Ti"); // from the round's own lines, not the other round's need
  assert.ok(!JSON.stringify(s).includes("Old Co"));
});

// ---- open

test("open: no offers and no beats, the sealed count and deadline come from the round row", () => {
  const s = projectArenaScene(rows({ rounds: [round({ sealedCount: 3 })], needs: [need()] }), { sample: true });
  assert.equal(s.phase, "open");
  assert.equal(s.roundId, "r1");
  assert.equal(s.sample, true);
  assert.equal(s.sealedCount, 3);
  assert.equal(s.deadline!.getTime(), 91_000);
  assert.deepEqual(s.offers, []);
  assert.deepEqual(s.beats, []);
  assert.equal(s.winnerBidId, null);
  assert.equal(s.problem, null);
});

test("requestLabel humanizes the need's skuSpec: letter and digit runs split, short words and numbers upper, ti is Ti", () => {
  const label = (skuSpec: string) => projectArenaScene(rows({ rounds: [round()], needs: [need({ skuSpec })] })).requestLabel;
  assert.equal(label("gpu-rtx5070ti-retail"), "GPU RTX 5070 Ti retail");
  assert.equal(label("rtx 5070 ti"), "RTX 5070 Ti");
  assert.equal(label("rtx5070ti"), "RTX 5070 Ti");
  assert.equal(label("nvme_ssd_2tb"), "nvme SSD 2 TB");
  assert.equal(label("  rtx   5070  "), "RTX 5070");
  assert.equal(label(""), "");
});

test("requestLabel joins several items with and, drops repeats, and never reads goal text or other rounds' needs", () => {
  const needs = [need({ skuSpec: "rtx 5070 ti" }), need({ skuSpec: "psu-750w" }), need({ skuSpec: "rtx5070ti" }), need({ roundId: "elsewhere", skuSpec: "ram" })];
  const s = projectArenaScene(rows({ rounds: [round()], needs }));
  assert.equal(s.requestLabel, "RTX 5070 Ti and PSU 750 W");
});

test("with no needs rows (seller_needs lists open rounds only) the label comes from the round's result lines", () => {
  const results = [
    ranked("a", 1, 10, { lines: [line({ skuSpec: "rtx 5070 ti" })] }),
    result("b", { reasons: ["below this seller floor"], lines: [line({ skuSpec: "rtx 5070 ti" }), line({ skuSpec: "psu-750w" })] }),
  ];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-a")] }));
  assert.equal(s.requestLabel, "RTX 5070 Ti and PSU 750 W");
});

test("open with stray result rows still shows no offers and no beats, so no price leaks before close", () => {
  const s = projectArenaScene(closedRows({ rounds: [round({ sealedCount: 5 })], events: [] }));
  assert.equal(s.phase, "open");
  assert.deepEqual(s.offers, []);
  assert.deepEqual(s.beats, []);
  assert.equal(s.winnerBidId, null);
  const json = JSON.stringify(s);
  for (const price of ["1299.99", "1247.02", "1199", "Winner Co", "b-win"]) assert.ok(!json.includes(price), price);
});

// ---- closing

test("closing: closed with no result rows and no auction_closed yet, or any other state string", () => {
  const closing = projectArenaScene(rows({ rounds: [round({ state: "closed", sealedCount: 4 })], needs: [need()] }));
  assert.equal(closing.phase, "closing");
  assert.equal(closing.sealedCount, 4);
  assert.deepEqual([closing.offers, closing.beats, closing.winnerBidId], [[], [], null]);
  assert.equal(closing.requestLabel, "RTX 5070 Ti");

  const odd = projectArenaScene(closedRows({ rounds: [round({ state: "settling" })] }));
  assert.equal(odd.phase, "closing");
  assert.deepEqual([odd.offers, odd.beats, odd.winnerBidId], [[], [], null]);
});

// ---- closed

test("closed: the winner is the rank 1 bid and matches auction_closed", () => {
  const s = projectArenaScene(closedRows());
  assert.equal(s.phase, "closed");
  assert.equal(s.winnerBidId, "b-win");
  assert.equal(s.problem, null);
  assert.equal(s.sealedCount, 5);
});

test("offers: ranked by rank, then Gate refusals, then advocate vetoes, each by bid id; any row order gives the same scene", () => {
  const base = closedRows();
  const s = projectArenaScene(base);
  assert.deepEqual(s.offers.map((o) => o.bidId), ["b-win", "b-second", "b-floor", "b-shield", "b-veto"]);
  assert.deepEqual(s.offers.map((o) => o.outcome), ["winner", "ranked", "knocked", "knocked", "knocked"]);
  assert.deepEqual(s.offers.map((o) => o.rank), [1, 2, null, null, null]);
  assert.deepEqual(s.offers.map((o) => o.key), ["b-win", "b-second", "b-floor", "b-shield", "b-veto"].map(offerKey));
  assert.deepEqual(s.offers.map((o) => o.knock?.reasonCode), [undefined, "outranked", "below_floor", "shield_block", "advocate_veto"]);
  assert.equal(s.offers[0]!.name, "Winner Co");
  assert.equal(s.offers[0]!.landed, 1299.99);
  assert.equal(s.offers[0]!.product, "asus prime RTX 5070 Ti OC");
  assert.equal(s.offers[1]!.product, "RTX 5070 Ti");
  assert.match(s.offers[0]!.rowRef, /^round_result\/\d+$/);
  const reversed = projectArenaScene({ ...base, results: [...base.results].reverse(), events: [...base.events].reverse() });
  assert.deepEqual(reversed, s);
});

test("the outranked offer keeps outcome ranked but carries the referee's knockout knock", () => {
  const second = projectArenaScene(closedRows()).offers[1]!;
  assert.equal(second.outcome, "ranked");
  assert.equal(second.knock!.reasonCode, "outranked");
  assert.equal(second.knock!.reasonText, "Referee ranked Winner Co #1 ahead: $1,299.99 vs $1,247.02");
});

test("product falls back to the skuSpec when offeredSpec is empty, and origin is normalised", () => {
  const results = [ranked("a", 1, 10, { origin: "live?", lines: [line({ offeredSpec: "", skuSpec: "gpu-rtx5070ti" })] }), ranked("b", 2, 11, { origin: "MIRROR" })];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-a")] }));
  assert.equal(s.offers[0]!.product, "GPU RTX 5070 Ti");
  assert.deepEqual(s.offers.map((o) => o.origin), ["SIM", "MIRROR"]);
});

test("a vetoed offer carries the cited source; an unsafe source URL is dropped", () => {
  const veto = projectArenaScene(closedRows()).offers.find((o) => o.bidId === "b-veto")!;
  assert.equal(veto.outcome, "knocked");
  assert.equal(veto.knock!.ruleId, "fit.gpu_length");
  assert.equal(veto.sourceUrl, "https://specs.example.test/card");
  const bad = closedRows();
  bad.results[2]!.reasons = ["Advocate veto (fit.gpu_length) [source: https://]"];
  assert.equal(projectArenaScene(bad).offers.find((o) => o.bidId === "b-veto")!.sourceUrl, undefined);
});

test("a ranked offer's listing link comes from its row source via safeUrl", () => {
  const results = [ranked("a", 1, 10, { source: "https://www.ebay.com/itm/1" }), ranked("b", 2, 11, { source: "https://" })];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-a")] }));
  assert.deepEqual(s.offers.map((o) => o.sourceUrl), ["https://www.ebay.com/itm/1", undefined]);
});

test("events link to an offer by refId === bidId only, sorted by id; the same sellerId or timing is not a link", () => {
  const base = closedRows();
  const events: EventRow[] = [
    event("advocate_card", "b-veto", { id: 30n, refTable: "bid_check", label: "Advocate veto (fit.gpu_length)" }),
    event("bid_sealed", "b-veto", { id: 10n, sellerId: "veto", label: "A sealed bid arrived", origin: "live?" }),
    event("bid_sealed", "b-other-bid", { id: 20n, sellerId: "veto", label: "same seller, different bid" }),
    event("verdict", "b-win", { id: 25n, refTable: "bid_check", label: "Bazaar Shield: allow" }),
    closedBy("win"),
  ];
  const s = projectArenaScene({ ...base, events });
  const veto = s.offers.find((o) => o.bidId === "b-veto")!;
  assert.deepEqual(veto.events, [
    { id: "10", kind: "bid_sealed", label: "A sealed bid arrived", origin: "SIM" },
    { id: "30", kind: "advocate_card", label: "Advocate veto (fit.gpu_length)", origin: "SIM" },
  ]);
  assert.deepEqual(s.offers.find((o) => o.bidId === "b-win")!.events.map((e) => e.id), ["25"]);
  assert.ok(!s.offers.some((o) => o.events.some((e) => e.label === "same seller, different bid")));
  assert.deepEqual(s.offers.find((o) => o.bidId === "b-second")!.events, []);
});

test("inconsistent: auction_closed names a different seller than rank 1, so nobody is crowned", () => {
  const s = projectArenaScene(closedRows({ events: [closedBy("second")] }));
  assert.equal(s.phase, "inconsistent");
  assert.match(s.problem!, /winner mismatch/);
  assert.equal(s.winnerBidId, null);
  assert.deepEqual(s.beats, []);
  assert.deepEqual(s.offers.map((o) => o.outcome), ["ranked", "ranked", "knocked", "knocked", "knocked"]);
  assert.ok(s.offers.every((o) => o.outcome !== "winner"));
  assert.equal(s.offers[0]!.bidId, "b-win");
  assert.equal(s.offers.find((o) => o.bidId === "b-veto")!.knock!.reasonCode, "advocate_veto");
});

test("inconsistent: auction_closed names a seller but the round has no result rows", () => {
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], events: [closedBy("ghost")] }));
  assert.equal(s.phase, "inconsistent");
  assert.match(s.problem!, /ghost/);
  assert.deepEqual([s.offers, s.beats, s.winnerBidId], [[], [], null]);
});

test("the no-eligible-bid close: closed, no offers, no beats, no winner", () => {
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed", sealedCount: 2 })], events: [closedBy("")] }));
  assert.equal(s.phase, "closed");
  assert.deepEqual([s.offers, s.beats, s.winnerBidId, s.problem], [[], [], null, null]);
  assert.equal(s.sealedCount, 2);
});

test("every offer knocked: closed with results but no champion, so no knockout and no crown beats", () => {
  const results = [result("a", { reasons: [SHIELD] }), result("b", { reasons: [VETO] })];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("")] }));
  assert.equal(s.phase, "closed");
  assert.equal(s.winnerBidId, null);
  assert.deepEqual(s.beats.map((b) => b.kind), ["arrive", "gate", "advocate"]);
  assert.deepEqual(s.offers.map((o) => o.outcome), ["knocked", "knocked"]);
});

test("projection is pure: it does not touch its input", () => {
  const input = closedRows();
  const before = JSON.stringify(input, (_k, v) => (typeof v === "bigint" ? `${v}n` : v));
  projectArenaScene(input);
  assert.equal(JSON.stringify(input, (_k, v) => (typeof v === "bigint" ? `${v}n` : v)), before);
});

// ---- beats

test("beats for a full close: arrive, gate, advocate, Final, crown, in the bracket's order", () => {
  const s = projectArenaScene(closedRows());
  assert.deepEqual(s.beats.map((b) => [b.kind, b.name]), [
    ["arrive", "Offers opened"], ["gate", "Gate"], ["advocate", "Heat 1"], ["knockout", "Final"], ["crown", "Winner"],
  ]);
  assert.deepEqual(s.beats.map((b) => b.ms), [1800, 1400, 1400, 1200, 2200]);
});

test("arrive: focus is the referee and the caption counts the sealed offers opened, singular for one", () => {
  const arrive = projectArenaScene(closedRows()).beats[0]!;
  assert.deepEqual(arrive.focus, ["referee"]);
  assert.deepEqual([arrive.advancing, arrive.knocked], [[], []]);
  assert.equal(arrive.caption, "The round closed. 5 sealed offers are opened.");
  const one = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results: [ranked("a", 1)], events: [closedBy("s-a")] }));
  assert.equal(one.beats[0]!.caption, "The round closed. 1 sealed offer is opened.");
});

test("gate: Shield first, then the referee, then the knocked offers; the caption counts the refusals", () => {
  const gate = projectArenaScene(closedRows()).beats[1]!;
  assert.deepEqual(gate.focus, ["shield", "referee", offerKey("b-floor"), offerKey("b-shield")]);
  assert.deepEqual(gate.knocked.map((k) => [k.id, k.reasonCode]), [["b-floor", "below_floor"], ["b-shield", "shield_block"]]);
  assert.deepEqual(gate.advancing, []);
  assert.equal(gate.caption, "The referee refused 2 offers before ranking.");
});

test("gate: only Shield blocks give the Shield caption and no referee stop; only other refusals skip the Shield", () => {
  const shieldOnly = projectArenaScene(rows({
    rounds: [round({ state: "closed" })], results: [ranked("w", 1), result("x", { reasons: [SHIELD] }), result("y", { reasons: ["Bazaar Shield quarantine: shield.x"] })], events: [closedBy("s-w")],
  }));
  const g1 = shieldOnly.beats.find((b) => b.kind === "gate")!;
  assert.deepEqual(g1.focus, ["shield", offerKey("x"), offerKey("y")]);
  assert.equal(g1.caption, "Bazaar Shield blocked 2 offers.");
  const floorOnly = projectArenaScene(rows({
    rounds: [round({ state: "closed" })], results: [ranked("w", 1), result("x", { reasons: ["below this seller floor"] })], events: [closedBy("s-w")],
  }));
  const g2 = floorOnly.beats.find((b) => b.kind === "gate")!;
  assert.deepEqual(g2.focus, ["referee", offerKey("x")]);
  assert.equal(g2.caption, "The referee refused 1 offer before ranking.");
});

test("advocate: the advocate then the vetoed offers; 'each with a cited source' only when every veto has one", () => {
  const adv = projectArenaScene(closedRows()).beats[2]!;
  assert.deepEqual(adv.focus, ["advocate", offerKey("b-veto")]);
  assert.deepEqual(adv.knocked.map((k) => [k.id, k.reasonCode]), [["b-veto", "advocate_veto"]]);
  assert.equal(adv.caption, "The advocate vetoed 1 offer, with a cited source.");

  const two = (sourceB: string) => projectArenaScene(rows({
    rounds: [round({ state: "closed" })],
    results: [ranked("w", 1), result("v1", { reasons: [VETO] }), result("v2", { reasons: [`Advocate veto (fit.psu_watts) [source: ${sourceB}]`] })],
    events: [closedBy("s-w")],
  })).beats.find((b) => b.kind === "advocate")!;
  assert.equal(two("https://specs.example.test/psu").caption, "The advocate vetoed 2 offers, each with a cited source.");
  assert.equal(two("https://").caption, "The advocate vetoed 2 offers.");
});

test("no gate beat when nothing was refused and no advocate beat when nothing was vetoed", () => {
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results: [ranked("a", 1), ranked("b", 2)], events: [closedBy("s-a")] }));
  assert.deepEqual(s.beats.map((b) => b.kind), ["arrive", "knockout", "crown"]);
});

test("knockout with one real heat names the two offers; byes still advance; outranked offers are the knocked list", () => {
  const results = [ranked("a", 1, 100, { persona: "Alpha" }), ranked("b", 2, 120, { persona: "Beta" }), ranked("c", 3, 130, { persona: "Gamma" })];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-a")] }));
  assert.deepEqual(s.beats.map((b) => b.name), ["Offers opened", "Semifinal", "Final", "Winner"]);
  const [, semi, final] = s.beats;
  assert.equal(semi!.caption, "Semifinal: the referee ranked Beta ahead of Gamma.");
  assert.deepEqual(semi!.advancing, ["a", "b"]);
  assert.deepEqual(semi!.knocked.map((k) => k.id), ["c"]);
  assert.deepEqual(semi!.focus, [offerKey("a"), offerKey("b"), offerKey("c")]);
  assert.equal(final!.caption, "Final: the referee ranked Alpha ahead of Beta.");
  assert.deepEqual(final!.advancing, ["a"]);
  assert.deepEqual(final!.knocked.map((k) => k.id), ["b"]);
  assert.deepEqual(final!.focus, [offerKey("a"), offerKey("b")]);
});

test("knockout with several heats says how many offers the ranking moves up", () => {
  const results = Array.from({ length: 6 }, (_, i) => ranked(`b${i + 1}`, i + 1, 100 + i));
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-b1")] }));
  const ko = s.beats.filter((b) => b.kind === "knockout");
  assert.deepEqual(ko.map((b) => b.name), ["Quarterfinal", "Semifinal", "Final"]);
  assert.equal(ko[0]!.caption, "Quarterfinal: the referee's ranking moves 4 offers up.");
  assert.equal(ko[0]!.advancing.length, 4);
  assert.equal(ko[1]!.caption, "Semifinal: the referee's ranking moves 2 offers up.");
  assert.equal(ko[2]!.caption, "Final: the referee ranked Seller b1 ahead of Seller b2.");
});

test("crown: the winner and the buyer, the winner's price before sales tax, last beat", () => {
  const s = projectArenaScene(closedRows());
  const crown = s.beats.at(-1)!;
  assert.equal(crown.kind, "crown");
  assert.equal(crown.name, "Winner");
  assert.deepEqual(crown.focus, [offerKey("b-win"), "buyer"]);
  assert.deepEqual(crown.advancing, [s.winnerBidId]);
  assert.deepEqual(crown.knocked, []);
  assert.equal(crown.caption, "Winner Co wins at $1,299.99 before sales tax.");
});

test("a round with 11 offers totals at most 12000 ms; the crown is last and advances exactly the winner", () => {
  const results = [
    ...Array.from({ length: 8 }, (_, i) => ranked(`r${i + 1}`, i + 1, 900 + i)),
    result("g1", { reasons: ["below this seller floor"] }),
    result("g2", { reasons: [SHIELD] }),
    result("v1", { reasons: [VETO] }),
  ];
  assert.equal(results.length, 11);
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed", sealedCount: 11 })], results, events: [closedBy("s-r1")] }));
  assert.equal(s.offers.length, 11);
  assert.ok(s.beats.reduce((n, b) => n + b.ms, 0) <= MAX_SEQUENCE_MS);
  const last = s.beats.at(-1)!;
  assert.equal(last.kind, "crown");
  assert.deepEqual(last.advancing, [s.winnerBidId]);
  assert.equal(s.winnerBidId, "r1");
  assert.equal(s.beats.filter((b) => b.kind === "crown").length, 1);
});

test("a very long bracket is scaled down so the whole close still fits MAX_SEQUENCE_MS", () => {
  const results = [
    ...Array.from({ length: 38 }, (_, i) => ranked(`b${String(i + 1).padStart(2, "0")}`, i + 1, 900 + i)),
    result("x-shield", { reasons: [SHIELD] }),
    result("x-veto", { reasons: [VETO] }),
  ];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-b01")] }));
  assert.equal(s.beats.filter((b) => b.kind === "knockout").length, 6);
  const total = s.beats.reduce((n, b) => n + b.ms, 0);
  assert.ok(total <= MAX_SEQUENCE_MS, String(total));
  assert.ok(total > MAX_SEQUENCE_MS * 0.95, String(total)); // scaled, not collapsed
  assert.ok(s.beats.every((b) => Number.isInteger(b.ms) && b.ms > 0));
  assert.ok(s.beats.find((b) => b.kind === "crown")!.ms > s.beats.find((b) => b.kind === "knockout")!.ms);
});

test("no bid is knocked twice across beats, and every knocked bid is an offer of this round", () => {
  const s = projectArenaScene(closedRows());
  const ids = knockedIds(s);
  assert.equal(new Set(ids).size, ids.length);
  assert.deepEqual([...ids].sort(), ["b-floor", "b-second", "b-shield", "b-veto"]);
  // a bid with both a Shield block and a veto leaves at the Gate only
  const both = projectArenaScene(rows({
    rounds: [round({ state: "closed" })], results: [ranked("w", 1), result("x", { reasons: [VETO, SHIELD] })], events: [closedBy("s-w")],
  }));
  assert.deepEqual(knockedIds(both), ["x"]);
  assert.deepEqual(both.beats.map((b) => b.kind), ["arrive", "gate", "crown"]);
});

test("captions and names never use em or en dashes", () => {
  for (const sample of Object.values(SAMPLES)) {
    const s = projectArenaScene(sample, { sample: true });
    const text = JSON.stringify([s.requestLabel, s.beats.map((b) => [b.name, b.caption]), s.offers.map((o) => o.knock?.reasonText ?? "")]);
    assert.doesNotMatch(text, dashes);
  }
});

// ---- samples

test("SAMPLES.gpu: a closed GPU round, five sellers, Fair Price PC wins over the open-box runner-up", () => {
  const sample = SAMPLES.gpu;
  assert.ok(sample.rounds.length === 1 && sample.results.length === 5);
  const s = projectArenaScene(sample, { sample: true });
  assert.equal(s.phase, "closed");
  assert.equal(s.sample, true);
  assert.equal(s.requestLabel, "RTX 5070 Ti");
  assert.equal(s.sealedCount, 5);
  assert.deepEqual(s.offers.map((o) => o.sellerId), ["fair-price-pc", "gadget-grove", "lowball", "renew-refurb", "bargain-bin"]);
  assert.deepEqual(s.offers.map((o) => o.name), ["Fair Price PC (SIM)", "Gadget Grove (Vedant)", "Lowball Direct (SIM)", "ReNew Refurb (SIM)", "Bargain Bin Hardware (SIM)"]);
  assert.deepEqual(s.offers.map((o) => o.landed), [1299.99, 1247.02, 1090, 1150, 1199]);
  assert.deepEqual(s.offers.map((o) => o.outcome), ["winner", "ranked", "knocked", "knocked", "knocked"]);
  assert.deepEqual(s.offers.map((o) => o.knock?.reasonCode), [undefined, "outranked", "below_floor", "shield_block", "advocate_veto"]);
  assert.equal(s.winnerBidId, s.offers[0]!.bidId);
  assert.equal(s.offers[0]!.product, "asus prime RTX 5070 Ti OC");
  assert.equal(s.offers[1]!.product, "RTX 5070 Ti");
  const veto = s.offers[4]!;
  assert.equal(veto.knock!.ruleId, "fit.gpu_length");
  assert.match(veto.sourceUrl!, /^https:\/\//);
  assert.deepEqual(s.beats.map((b) => b.kind), ["arrive", "gate", "advocate", "knockout", "crown"]);
  assert.equal(s.beats[1]!.caption, "The referee refused 2 offers before ranking.");
  assert.equal(s.beats[4]!.caption, "Fair Price PC (SIM) wins at $1,299.99 before sales tax.");
  assert.ok(s.offers.every((o) => o.origin === "SIM" && o.events.length > 0));
  assert.ok(sample.results.every((r) => r.origin === "SIM") && sample.events.every((e) => e.origin === "SIM") && sample.rounds.every((r) => r.origin === "SIM"));
});

test("SAMPLES.gpu: events are the ones the market writes and link to their bid by refId", () => {
  const s = projectArenaScene(SAMPLES.gpu, { sample: true });
  const kinds = (sellerId: string) => s.offers.find((o) => o.sellerId === sellerId)!.events.map((e) => e.kind);
  assert.deepEqual(kinds("fair-price-pc"), ["bid_sealed", "verdict", "advocate_card", "stock_held"]);
  assert.deepEqual(kinds("bargain-bin"), ["bid_sealed", "verdict", "advocate_card"]);
  assert.deepEqual(kinds("renew-refurb"), ["bid_sealed", "verdict"]);
  assert.deepEqual(kinds("lowball"), ["bid_rejected"]);
  const closed = SAMPLES.gpu.events.find((e) => e.kind === "auction_closed")!;
  assert.equal(closed.refId, SAMPLES.gpu.rounds[0]!.id);
  assert.equal(closed.sellerId, "fair-price-pc");
  assert.ok(SAMPLES.gpu.events.some((e) => e.kind === "round_opened"));
  const ids = SAMPLES.gpu.events.map((e) => e.id);
  assert.equal(new Set(ids).size, ids.length);
});

test("SAMPLES['gpu-open']: the same request, open, three sealed, 90 seconds, one needs row, no results", () => {
  const sample = SAMPLES["gpu-open"];
  assert.equal(sample.needs.length, 1);
  assert.equal(sample.results.length, 0);
  const s = projectArenaScene(sample, { sample: true });
  assert.equal(s.phase, "open");
  assert.equal(s.requestLabel, "RTX 5070 Ti");
  assert.equal(s.sealedCount, 3);
  const r = sample.rounds[0]!;
  assert.equal(s.deadline!.getTime() - Number(r.openedAt.microsSinceUnixEpoch / 1000n), 90_000);
  assert.deepEqual([s.offers, s.beats, s.winnerBidId], [[], [], null]);
  assert.equal(SAMPLES.gpu.rounds[0]!.id !== r.id, true);
});

test("SAMPLES.ssd: three ranked sellers make a Semifinal with a bye and a Final", () => {
  const s = projectArenaScene(SAMPLES.ssd, { sample: true });
  assert.equal(s.phase, "closed");
  assert.equal(s.requestLabel, "nvme SSD 2 TB");
  assert.deepEqual(s.offers.map((o) => o.sellerId), ["seller-a", "seller-b", "seller-c"]);
  assert.deepEqual(s.offers.map((o) => o.name), ["Seller A", "Seller B", "Seller C"]);
  assert.deepEqual(s.offers.map((o) => o.outcome), ["winner", "ranked", "ranked"]);
  assert.deepEqual(s.beats.map((b) => b.name), ["Offers opened", "Semifinal", "Final", "Winner"]);
  assert.equal(s.beats[1]!.caption, "Semifinal: the referee ranked Seller B ahead of Seller C.");
  assert.deepEqual(s.beats[1]!.advancing, [s.offers[0]!.bidId, s.offers[1]!.bidId]);
  assert.equal(s.winnerBidId, s.offers[0]!.bidId);
  assert.equal(SAMPLES.ssd.events.find((e) => e.kind === "auction_closed")!.sellerId, "seller-a");
});

// ---- playback

const sceneOf = (rowSet: ArenaRows): ArenaScene => projectArenaScene(rowSet);
const OPEN = sceneOf(rows({ rounds: [round()], needs: [need()] }));
const CLOSING = sceneOf(rows({ rounds: [round({ state: "closed" })] }));
const CLOSED = sceneOf(closedRows());
const NOBODY = sceneOf(rows({ rounds: [round({ state: "closed" })], events: [closedBy("")] }));
const BAD = sceneOf(closedRows({ events: [closedBy("second")] }));
const WAITING = sceneOf(rows());
const N = CLOSED.beats.length;
const step = (s: Playback, scene: ArenaScene, ...types: ("scene" | "tick" | "pause" | "resume" | "replay" | "skip")[]) => types.reduce((p, type) => playback(p, { type }, scene), s);

test("playback: a round already closed on first sight shows its final frame and never plays", () => {
  const p = playback(IDLE, { type: "scene" }, CLOSED);
  assert.deepEqual(p, { roundId: "r1", beat: N, playing: false, sawOpen: false, replay: false });
  assert.equal(playback(p, { type: "scene" }, CLOSED), p);
  assert.equal(playback(p, { type: "tick" }, CLOSED), p);
});

test("playback: a round seen open and then closed plays its beats once", () => {
  let p = playback(IDLE, { type: "scene" }, OPEN);
  assert.deepEqual(p, { roundId: "r1", beat: 0, playing: false, sawOpen: true, replay: false });
  p = playback(p, { type: "scene" }, CLOSING);
  assert.equal(p.sawOpen, true);
  p = playback(p, { type: "scene" }, CLOSED);
  assert.deepEqual(p, { roundId: "r1", beat: 0, playing: true, sawOpen: false, replay: false });
  for (let i = 1; i < N; i++) {
    p = playback(p, { type: "tick" }, CLOSED);
    assert.deepEqual([p.beat, p.playing], [i, true]);
  }
  p = playback(p, { type: "tick" }, CLOSED);
  assert.deepEqual([p.beat, p.playing], [N, false]);
  // the same rows arriving again do not replay it
  const again = playback(p, { type: "scene" }, CLOSED);
  assert.equal(again, p);
  assert.equal(playback(p, { type: "tick" }, CLOSED), p);
});

test("playback: a round first seen closing and then closed also plays once; a repeated open scene changes nothing", () => {
  const p = playback(playback(IDLE, { type: "scene" }, CLOSING), { type: "scene" }, CLOSED);
  assert.deepEqual([p.beat, p.playing, p.sawOpen], [0, true, false]);
  // already marked: an open scene again returns the same object
  const open = playback(IDLE, { type: "scene" }, OPEN);
  assert.equal(playback(open, { type: "scene" }, OPEN), open);
});

test("playback: re-delivered rows and duplicate scene actions return the same object", () => {
  const open = playback(IDLE, { type: "scene" }, OPEN);
  assert.equal(playback(open, { type: "scene" }, OPEN), open);
  const final = playback(IDLE, { type: "scene" }, CLOSED);
  assert.equal(playback(final, { type: "scene" }, CLOSED), final);
  assert.equal(playback(IDLE, { type: "scene" }, WAITING), IDLE);
  const midway = { ...final, beat: 2, playing: true };
  assert.equal(playback(midway, { type: "scene" }, CLOSED), midway);
});

test("playback: a reconnect that clears the rows, then a closed round, shows the final frame without playing", () => {
  let p = playback(IDLE, { type: "scene" }, OPEN);
  p = playback(p, { type: "scene" }, WAITING); // rows dropped on disconnect: a different (null) round
  assert.deepEqual(p, IDLE);
  p = playback(p, { type: "scene" }, CLOSED);
  assert.deepEqual(p, { roundId: "r1", beat: N, playing: false, sawOpen: false, replay: false });
});

test("playback: a different round resets, with its own sawOpen", () => {
  const playing = { roundId: "other", beat: 2, playing: true, sawOpen: false, replay: true };
  assert.deepEqual(playback(playing, { type: "scene" }, OPEN), { roundId: "r1", beat: 0, playing: false, sawOpen: true, replay: false });
  assert.deepEqual(playback(playing, { type: "scene" }, CLOSED), { roundId: "r1", beat: N, playing: false, sawOpen: false, replay: false });
  assert.deepEqual(playback(playing, { type: "scene" }, BAD), { roundId: "r1", beat: 0, playing: false, sawOpen: false, replay: false });
});

test("playback: a live close with no beats (nobody won) has nothing to play", () => {
  let p = playback(IDLE, { type: "scene" }, OPEN);
  p = playback(p, { type: "scene" }, { ...NOBODY });
  assert.equal(p.playing, false);
  assert.equal(p.beat, 0);
  assert.equal(NOBODY.beats.length, 0);
});

test("playback: an inconsistent round stays at beat 0 and never plays", () => {
  const s = { roundId: "r1", beat: 3, playing: true, sawOpen: true, replay: false };
  const p = playback(s, { type: "scene" }, BAD);
  assert.deepEqual([p.beat, p.playing], [0, false]);
  assert.equal(playback(p, { type: "scene" }, BAD), p);
});

test("playback: tick is ignored unless playing, advances one beat, and stops at the end", () => {
  const idle = playback(IDLE, { type: "scene" }, CLOSED);
  assert.equal(playback({ ...idle, beat: 1 }, { type: "tick" }, CLOSED).beat, 1);
  const p = { ...idle, beat: 0, playing: true };
  assert.deepEqual(playback(p, { type: "tick" }, CLOSED), { ...p, beat: 1 });
  assert.deepEqual(playback({ ...p, beat: N - 1 }, { type: "tick" }, CLOSED), { ...p, beat: N, playing: false });
});

test("playback: pause stops, resume plays while beats remain, replay restarts from the sealed table, skip jumps to the final frame", () => {
  const base = { roundId: "r1", beat: 2, playing: true, sawOpen: false, replay: false };
  assert.deepEqual(playback(base, { type: "pause" }, CLOSED), { ...base, playing: false });
  assert.deepEqual(playback({ ...base, playing: false }, { type: "resume" }, CLOSED), base);
  const done = { ...base, beat: N, playing: false };
  assert.equal(playback(done, { type: "resume" }, CLOSED), done);
  assert.deepEqual(playback(done, { type: "replay" }, CLOSED), { ...done, beat: 0, playing: true, replay: true });
  assert.deepEqual(playback(base, { type: "skip" }, CLOSED), { ...base, beat: N, playing: false });
  // without beats there is nothing to replay
  const none = { roundId: "r1", beat: 0, playing: false, sawOpen: false, replay: false };
  assert.equal(playback(none, { type: "replay" }, NOBODY), none);
  assert.equal(playback(none, { type: "resume" }, NOBODY), none);
});

test("playback: replay then ticks walks every beat and stops on the final frame, replay flag kept", () => {
  let p = playback(IDLE, { type: "scene" }, CLOSED);
  p = step(p, CLOSED, "replay");
  for (let i = 0; i < N; i++) p = step(p, CLOSED, "tick");
  assert.deepEqual(p, { roundId: "r1", beat: N, playing: false, sawOpen: false, replay: true });
});
