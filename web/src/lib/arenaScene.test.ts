// Run with: npm test --prefix web (node --test, no extra dependency).
// Fixtures are SIM rows in the shape the market writes (round, seller_needs, round_result, floor_event), reasons as close_round writes them.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  IDLE, MAX_SEQUENCE_MS, isEmptyMarket, offerKey, playback, projectArenaScene, storyFor,
  type ArenaRows, type ArenaScene, type EventRow, type LineRow, type NeedRow, type Playback, type ResultRow, type RoundRow,
} from "./arenaScene.ts";
import { SAMPLES } from "./arenaFixture.ts";
import { boardAt } from "./arenaBoard.ts";

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

test("requestLabel humanizes the need's skuSpec: letter and digit runs split, plain words title-cased, acronyms and short words upper, ti is Ti", () => {
  const label = (skuSpec: string) => projectArenaScene(rows({ rounds: [round()], needs: [need({ skuSpec })] })).requestLabel;
  assert.equal(label("gpu-rtx5070ti-retail"), "GPU RTX 5070 Ti Retail");
  assert.equal(label("rtx 5070 ti"), "RTX 5070 Ti");
  assert.equal(label("rtx5070ti"), "RTX 5070 Ti");
  assert.equal(label("nvme_ssd_2tb"), "NVMe SSD 2 TB");
  assert.equal(label("asus prime rtx 5070 ti oc"), "ASUS Prime RTX 5070 Ti OC");
  assert.equal(label("MSI GAMING evga"), "MSI Gaming EVGA");
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
  assert.equal(s.offers[0]!.product, "ASUS Prime RTX 5070 Ti OC");
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

test("beats for a full close: arrive, one round per eliminated offer (gate, advocate, then ranked worst first), then the crown", () => {
  const s = projectArenaScene(closedRows());
  assert.deepEqual(s.beats.map((b) => [b.kind, b.name]), [
    ["arrive", "Offers opened"], ["gate", "Round 1"], ["gate", "Round 2"], ["advocate", "Round 3"], ["knockout", "Round 4"], ["crown", "Winner"],
  ]);
  assert.deepEqual(s.beats.map((b) => b.ms), [1600, 1500, 1500, 1500, 1500, 2200]);
  assert.deepEqual(s.beats.slice(1, 5).map((b) => b.knocked.map((k) => k.id)), [["b-shield"], ["b-floor"], ["b-veto"], ["b-second"]]);
  assert.ok(s.beats.slice(1, 5).every((b) => b.advancing.length === 0 && b.knocked.length === 1));
});

test("arrive: focus is the referee and the caption counts the sealed offers opened, singular for one", () => {
  const arrive = projectArenaScene(closedRows()).beats[0]!;
  assert.deepEqual(arrive.focus, ["referee"]);
  assert.deepEqual([arrive.advancing, arrive.knocked], [[], []]);
  assert.equal(arrive.caption, "The round closed. 5 sealed offers are opened.");
  const one = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results: [ranked("a", 1)], events: [closedBy("s-a")] }));
  assert.equal(one.beats[0]!.caption, "The round closed. 1 sealed offer is opened.");
});

test("round focus and captions: Shield, other refusal, veto and ranked each name who is out", () => {
  const [, r1, r2, r3, r4] = projectArenaScene(closedRows()).beats;
  assert.deepEqual(r1!.focus, ["shield", offerKey("b-shield")]);
  assert.equal(r1!.caption, "Round 1: Bazaar Shield blocks Shield Co.");
  assert.deepEqual(r2!.focus, ["referee", offerKey("b-floor")]);
  assert.equal(r2!.caption, "Round 2: Floor Co is out, below this seller's floor price.");
  assert.deepEqual(r3!.focus, ["advocate", offerKey("b-veto")]);
  assert.equal(r3!.caption, "Round 3: the advocate vetoes Veto Co, with a cited source.");
  assert.deepEqual(r4!.focus, [offerKey("b-second")]);
  assert.equal(r4!.caption, "Round 4: Second Co is out at $1,247.02, ranked #2.");
  assert.equal(r4!.knocked[0]!.reasonCode, "outranked");
  assert.deepEqual(r1!.knocked.map((k) => k.reasonCode), ["shield_block"]);
});

test("Shield blocks go before other refusals even when their bid ids sort the other way", () => {
  const s = projectArenaScene(rows({
    rounds: [round({ state: "closed" })],
    results: [ranked("w", 1), result("a-floor", { reasons: ["below this seller floor"] }), result("z-shield", { reasons: [SHIELD] })],
    events: [closedBy("s-w")],
  }));
  assert.deepEqual(s.beats.filter((b) => b.kind === "gate").map((b) => b.knocked[0]!.id), ["z-shield", "a-floor"]);
});

test("a veto caption drops 'with a cited source' when the knock has no usable source", () => {
  const veto = (source: string) => projectArenaScene(rows({
    rounds: [round({ state: "closed" })],
    results: [ranked("w", 1), result("v", { persona: "Vee", reasons: ["Advocate veto (fit.psu_watts) [source: " + source + "]"] })],
    events: [closedBy("s-w")],
  })).beats.find((b) => b.kind === "advocate")!.caption;
  assert.equal(veto("https://specs.example.test/psu"), "Round 1: the advocate vetoes Vee, with a cited source.");
  assert.equal(veto("https://"), "Round 1: the advocate vetoes Vee.");
});

test("with nothing refused or vetoed the rounds are only the ranked losers", () => {
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results: [ranked("a", 1), ranked("b", 2)], events: [closedBy("s-a")] }));
  assert.deepEqual(s.beats.map((b) => b.kind), ["arrive", "knockout", "crown"]);
});

test("ranked losers go out worst rank first, each exactly once, and the winner is never knocked", () => {
  const results = Array.from({ length: 6 }, (_, i) => ranked("b" + (i + 1), i + 1, 100 + i, { persona: "P" + (i + 1) }));
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-b1")] }));
  const rounds = s.beats.filter((b) => b.kind === "knockout");
  assert.deepEqual(rounds.map((b) => b.knocked[0]!.id), ["b6", "b5", "b4", "b3", "b2"]);
  assert.deepEqual(rounds.map((b) => b.name), ["Round 1", "Round 2", "Round 3", "Round 4", "Round 5"]);
  assert.equal(rounds[0]!.caption, "Round 1: P6 is out at $105, ranked #6.");
  assert.equal(rounds[4]!.caption, "Round 5: P2 is out at $101, ranked #2.");
  assert.ok(!knockedIds(s).includes("b1"));
  assert.deepEqual(s.beats.map((b) => b.kind), ["arrive", ...rounds.map(() => "knockout"), "crown"]);
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

test("a very long field is scaled down so the whole close still fits MAX_SEQUENCE_MS", () => {
  const results = [
    ...Array.from({ length: 38 }, (_, i) => ranked("b" + String(i + 1).padStart(2, "0"), i + 1, 900 + i)),
    result("x-shield", { reasons: [SHIELD] }),
    result("x-veto", { reasons: [VETO] }),
  ];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-b01")] }));
  assert.equal(s.beats.length, 1 + 39 + 1);
  const total = s.beats.reduce((n, b) => n + b.ms, 0);
  assert.ok(total <= MAX_SEQUENCE_MS, String(total));
  assert.ok(total > MAX_SEQUENCE_MS * 0.95, String(total)); // scaled, not collapsed
  assert.ok(s.beats.every((b) => Number.isInteger(b.ms) && b.ms > 0));
  assert.ok(s.beats.find((b) => b.kind === "crown")!.ms > s.beats.find((b) => b.kind === "knockout")!.ms);
});

test("every non-winner is knocked exactly once across the round beats, in gate, advocate, ranked order", () => {
  const s = projectArenaScene(closedRows());
  const ids = knockedIds(s);
  assert.equal(ids.length, s.offers.length - 1);
  assert.deepEqual([...ids].sort(), s.offers.filter((o) => o.outcome !== "winner").map((o) => o.bidId).sort());
  assert.deepEqual(ids, ["b-shield", "b-floor", "b-veto", "b-second"]);
  assert.ok(!ids.includes(s.winnerBidId!));
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

test("SAMPLES['gpu-review']: a caught listing ranked 1 projects to inconsistent, nobody crowned", () => {
  const s = projectArenaScene(SAMPLES["gpu-review"], { sample: true });
  assert.equal(s.phase, "inconsistent");
  assert.equal(s.winnerBidId, null);
  assert.ok(boardAt(s, 0).buyerLine.startsWith("Winner under review"));
});

test("SAMPLES.gpu: a closed GPU round, five sellers, Byte Bros Outlet wins over the open-box runner-up", () => {
  const sample = SAMPLES.gpu;
  assert.ok(sample.rounds.length === 1 && sample.results.length === 5);
  const s = projectArenaScene(sample, { sample: true });
  assert.equal(s.phase, "closed");
  assert.equal(s.sample, true);
  assert.equal(s.requestLabel, "RTX 5070 Ti");
  assert.equal(s.sealedCount, 5);
  assert.deepEqual(s.offers.map((o) => o.sellerId), ["seller_1", "seller_5", "seller_2", "seller_3", "seller_6"]);
  assert.deepEqual(s.offers.map((o) => o.name), ["Byte Bros Outlet", "ReNew Refurb", "Silicon Sally's Surplus", "FlashDeal Frankie", "Central Computers"]);
  assert.deepEqual(s.offers.map((o) => o.landed), [1299.99, 1247.02, 1150, 1199, 1349.99]);
  assert.deepEqual(s.offers.map((o) => o.outcome), ["winner", "ranked", "knocked", "knocked", "knocked"]);
  assert.deepEqual(s.offers.map((o) => o.knock?.reasonCode), [undefined, "outranked", "shield_block", "advocate_veto", "advocate_veto"]);
  assert.equal(s.winnerBidId, s.offers[0]!.bidId);
  assert.equal(s.offers[0]!.product, "ASUS Prime RTX 5070 Ti OC");
  assert.equal(s.offers[1]!.product, "RTX 5070 Ti");
  const veto = s.offers[3]!;
  assert.equal(veto.knock!.ruleId, "advocate.condition");
  assert.match(veto.sourceUrl!, /^https:\/\//);
  const central = s.offers.find((o) => o.sellerId === "seller_6")!;
  const centralRow = SAMPLES.gpu.results.find((r) => r.sellerId === "seller_6")!;
  assert.equal(central.origin, "MIRROR");
  assert.equal(central.outcome, "knocked");
  assert.equal(central.knock!.reasonCode, "advocate_veto");
  assert.equal(central.knock!.ruleId, "mirror_not_orderable");
  assert.equal(central.knock!.sourceUrl, centralRow.source);
  assert.match(central.knock!.sourceUrl!, /^https:\/\/www\.centralcomputer\.com\//);
  assert.notEqual(s.winnerBidId, central.bidId);
  assert.equal(s.winnerBidId, s.offers.find((o) => o.sellerId === "seller_1")!.bidId);
  const renew = SAMPLES.gpu.results.find((r) => r.sellerId === "seller_5")!;
  assert.equal(renew.lines.length, 2);
  assert.deepEqual(renew.lines.map((l) => l.offeredCondition), ["refurbished", "open-box"]);
  assert.ok(renew.lines.every((l) => l.skuSpec === "rtx 5070 ti" && l.quantity === 1));
  assert.ok(renew.lines.reduce((t, l) => t + l.unitPrice, 0) < renew.landed);
  assert.ok(SAMPLES.gpu.results.filter((r) => r.sellerId !== "seller_6").every((r) => r.origin === "SIM"));
  assert.deepEqual(s.beats.map((x) => x.kind), ["arrive", "gate", "advocate", "advocate", "knockout", "crown"]);
  assert.deepEqual(s.beats.map((x) => x.name), ["Offers opened", "Round 1", "Round 2", "Round 3", "Round 4", "Winner"]);
  assert.equal(s.beats[1]!.caption, "Round 1: Bazaar Shield blocks Silicon Sally's Surplus.");
  assert.equal(s.beats[2]!.caption, "Round 2: the advocate vetoes FlashDeal Frankie, with a cited source.");
  assert.equal(s.beats[3]!.caption, "Round 3: the advocate vetoes Central Computers, with a cited source.");
  assert.equal(s.beats[4]!.caption, "Round 4: ReNew Refurb is out at $1,247.02, ranked #2. Its refurbished offer ranks below new.");
  assert.deepEqual(s.offers.map((o) => o.condition), ["new", "refurbished", "open-box", "new", "new"]);
  assert.equal(s.beats[5]!.caption, "Byte Bros Outlet wins at $1,299.99 before sales tax.");
  assert.ok(s.offers.every((o) => (o.origin === "MIRROR") === (o.sellerId === "seller_6") && o.events.length > 0));
  assert.ok(sample.results.every((r) => r.origin === (r.sellerId === "seller_6" ? "MIRROR" : "SIM")) && sample.events.every((e) => e.origin === "SIM") && sample.rounds.every((r) => r.origin === "SIM"));
});

test("SAMPLES.gpu: events are the ones the market writes and link to their bid by refId", () => {
  const s = projectArenaScene(SAMPLES.gpu, { sample: true });
  const kinds = (sellerId: string) => s.offers.find((o) => o.sellerId === sellerId)!.events.map((e) => e.kind);
  assert.deepEqual(kinds("seller_1"), ["bid_sealed", "verdict", "advocate_card", "stock_held"]);
  assert.deepEqual(kinds("seller_3"), ["bid_sealed", "verdict", "advocate_card"]);
  assert.deepEqual(kinds("seller_2"), ["bid_sealed", "verdict"]);
  assert.deepEqual(kinds("seller_6"), ["bid_sealed", "verdict", "advocate_card"]);
  const tail = SAMPLES.gpu.events.slice(-4).map((e) => [e.kind, e.sellerId, e.refTable]);
  assert.deepEqual(tail, [["stock_held", "seller_1", "stock_hold"], ["auction_closed", "seller_1", "round"], ["approval_call_placed", "", "round"], ["pulse_note", "", "round"]]);
  const closed = SAMPLES.gpu.events.find((e) => e.kind === "auction_closed")!;
  assert.equal(closed.refId, SAMPLES.gpu.rounds[0]!.id);
  assert.equal(closed.sellerId, "seller_1");
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

test("SAMPLES.ssd: three ranked sellers and a refused Seller D make three rounds, then the crown", () => {
  const s = projectArenaScene(SAMPLES.ssd, { sample: true });
  assert.equal(s.phase, "closed");
  assert.equal(s.requestLabel, "NVMe SSD 2 TB");
  assert.deepEqual(s.offers.map((o) => o.sellerId), ["seller-a", "seller-b", "seller-c", "seller-d"]);
  assert.deepEqual(s.offers.map((o) => o.name), ["Seller A", "Seller B", "Seller C", "Seller D"]);
  assert.deepEqual(s.offers.map((o) => o.outcome), ["winner", "ranked", "ranked", "knocked"]);
  assert.deepEqual(s.beats.map((b) => b.name), ["Offers opened", "Round 1", "Round 2", "Round 3", "Winner"]);
  assert.equal(s.beats[1]!.caption, "Round 1: Seller D is out, below this seller's floor price.");
  assert.equal(s.beats[2]!.caption, "Round 2: Seller C is out at $131, ranked #3.");
  assert.equal(s.beats[3]!.caption, "Round 3: Seller B is out at $124.50, ranked #2.");
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

// ---- conditions in the knockout caption

test("condition: each offer carries its first line's offered condition, or empty when the line has none", () => {
  const results = [
    ranked("a", 1, 10, { lines: [line({ offeredCondition: "open-box" })] }),
    ranked("b", 2, 11, { lines: [line({ offeredCondition: "" })] }),
    result("c", { reasons: ["below this seller floor"], lines: [] }),
  ];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("s-a")] }));
  assert.deepEqual(s.offers.map((o) => o.condition), ["open-box", "", ""]);
});

test("a ranked loser's caption adds the condition clause only when its condition and the winner's are both known and differ", () => {
  const out = (ca: string, cb: string) => projectArenaScene(rows({
    rounds: [round({ state: "closed" })],
    results: [
      ranked("a", 1, 120, { persona: "Alpha", lines: [line({ offeredCondition: ca })] }),
      ranked("b", 2, 100, { persona: "Beta", lines: [line({ offeredCondition: cb })] }),
    ],
    events: [closedBy("s-a")],
  })).beats.find((b) => b.kind === "knockout")!.caption;
  assert.equal(out("new", "open-box"), "Round 1: Beta is out at $100, ranked #2. Its open-box offer ranks below new.");
  assert.equal(out("new", "new"), "Round 1: Beta is out at $100, ranked #2.");
  assert.equal(out("new", ""), "Round 1: Beta is out at $100, ranked #2.");
  assert.equal(out("", "open-box"), "Round 1: Beta is out at $100, ranked #2.");
});

// ---- seek

test("playback: seek jumps to a beat, clamps to 0..beats.length, and stops playing", () => {
  const playing = { roundId: "r1", beat: 1, playing: true, sawOpen: false, replay: true };
  assert.deepEqual(playback(playing, { type: "seek", beat: 3 }, CLOSED), { ...playing, beat: 3, playing: false });
  assert.deepEqual(playback(playing, { type: "seek", beat: 0 }, CLOSED), { ...playing, beat: 0, playing: false });
  assert.equal(playback(playing, { type: "seek", beat: 99 }, CLOSED).beat, N);
  assert.equal(playback(playing, { type: "seek", beat: -4 }, CLOSED).beat, 0);
  assert.equal(playback(playing, { type: "seek", beat: 2.9 }, CLOSED).beat, 2);
  assert.equal(playback(playing, { type: "seek", beat: Number.NaN }, CLOSED).beat, 0);
  const still = { ...playing, beat: 3, playing: false };
  assert.equal(playback(still, { type: "seek", beat: 3 }, CLOSED), still);
  assert.equal(playback(still, { type: "seek", beat: 9 }, NOBODY).beat, 0); // no beats: nowhere to go
});

// ---- storyFor

const pbAt = (scene: ArenaScene, beat: number, over: Partial<Playback> = {}): Playback => ({ roundId: scene.roundId, beat, playing: false, sawOpen: false, replay: false, ...over });
const openWith = (sealedCount: number) => sceneOf(rows({ rounds: [round({ sealedCount })], needs: [need()] }));
const timeOf = (d: Date) => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });

test("story: waiting", () => {
  assert.deepEqual(storyFor(WAITING, IDLE), {
    status: "Live round", hero: "", caption: "No round yet. When a buyer posts a request, it appears here.", stage: null, step: null, note: null,
  });
});

test("story: open with nothing sealed says when sellers can bid until; the hero is the request", () => {
  const scene = openWith(0);
  const story = storyFor(scene, pbAt(scene, 0));
  assert.equal(story.status, "Live round");
  assert.equal(story.hero, "RTX 5070 Ti");
  assert.equal(story.caption, "Sealed round open. Sellers can bid until " + timeOf(scene.deadline!) + ".");
  assert.match(story.caption, /until \d{1,2}:\d{2}:\d{2}\s?[AP]M\.$/);
  assert.deepEqual([story.stage, story.step, story.note], [null, null, null]);
});

test("story: open with sealed offers counts them, singular for one, and keeps prices hidden", () => {
  assert.equal(storyFor(openWith(3), pbAt(openWith(3), 0)).caption, "3 sealed offers are in. Prices stay hidden until the round closes.");
  assert.equal(storyFor(openWith(1), pbAt(openWith(1), 0)).caption, "1 sealed offer is in. Prices stay hidden until the round closes.");
});

test("story: closing waits for the referee", () => {
  const story = storyFor(CLOSING, pbAt(CLOSING, 0));
  assert.equal(story.status, "Live round");
  assert.equal(story.caption, "Round closed. Waiting for the referee's result.");
  assert.equal(story.hero, "");
});

test("story: a closed round at beat 0, mid close, and at the final frame", () => {
  const start = storyFor(CLOSED, pbAt(CLOSED, 0, { playing: true }));
  assert.equal(start.caption, "The round closed. The referee is opening the sealed offers.");
  assert.equal(start.hero, "RTX 5070 Ti");
  assert.deepEqual([start.stage, start.step, start.note], [null, "0 of 6", null]);

  const mid = storyFor(CLOSED, pbAt(CLOSED, 2, { playing: true }));
  assert.equal(mid.caption, CLOSED.beats[1]!.caption);
  assert.deepEqual([mid.stage, mid.step, mid.hero], ["Round 1", "2 of 6", "RTX 5070 Ti"]);

  const end = storyFor(CLOSED, pbAt(CLOSED, N));
  assert.equal(end.caption, "Winner Co wins at $1,299.99 before sales tax.");
  assert.equal(end.hero, "$1,299.99");
  assert.deepEqual([end.stage, end.step], ["Winner", "6 of 6"]);
});

test("story: the round note shows during every round beat and nowhere else", () => {
  const note = "Each round removes the weakest remaining offer by the referee's sealed ranking. Sellers did not bid against each other live.";
  assert.equal(N, 6);
  for (let k = 0; k <= N; k++) assert.equal(storyFor(CLOSED, pbAt(CLOSED, k)).note, k >= 2 && k <= 5 ? note : null, "beat " + k);
});

test("story: status is Sample run for samples, Live round while a live close plays, Recorded round otherwise", () => {
  const sample = projectArenaScene(SAMPLES.gpu, { sample: true });
  assert.equal(storyFor(sample, pbAt(sample, 0)).status, "Sample run");
  assert.equal(storyFor(sample, pbAt(sample, 5, { playing: true, replay: true })).status, "Sample run");
  assert.equal(storyFor(CLOSED, pbAt(CLOSED, 2, { playing: true })).status, "Live round");
  assert.equal(storyFor(CLOSED, pbAt(CLOSED, 2, { playing: true, replay: true })).status, "Recorded round");
  assert.equal(storyFor(CLOSED, pbAt(CLOSED, N)).status, "Recorded round");
  assert.equal(storyFor(CLOSED, pbAt(CLOSED, 0)).status, "Recorded round");
  assert.equal(storyFor(openWith(2), pbAt(openWith(2), 0)).status, "Live round");
});

test("story: nobody won (no eligible bid, or every offer knocked) says so at the final frame", () => {
  const none = storyFor(NOBODY, pbAt(NOBODY, 0));
  assert.equal(none.caption, "No offer passed the checks, so nobody won this round.");
  assert.deepEqual([none.stage, none.step, none.note], [null, null, null]);
  const results = [result("a", { reasons: [SHIELD] }), result("b", { reasons: [VETO] })];
  const allOut = sceneOf(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("")] }));
  assert.equal(storyFor(allOut, pbAt(allOut, 0)).caption, "The round closed. The referee is opening the sealed offers.");
  const end = storyFor(allOut, pbAt(allOut, allOut.beats.length));
  assert.equal(end.caption, "No offer passed the checks, so nobody won this round.");
  assert.equal(end.hero, "RTX 5070 Ti");
});

test("story: inconsistent rows say so and show no winner", () => {
  const story = storyFor(BAD, pbAt(BAD, 0));
  assert.equal(story.caption, "The result rows disagree, so no winner is shown.");
  assert.deepEqual([story.stage, story.step, story.note], [null, null, null]);
  assert.ok(!story.hero.startsWith("$"));
});

test("story: playback state for another round is read as a reset to this one, so history shows its final frame", () => {
  const story = storyFor(CLOSED, IDLE);
  assert.equal(story.caption, "Winner Co wins at $1,299.99 before sales tax.");
  assert.equal(storyFor(CLOSED, { ...IDLE, roundId: "elsewhere", beat: 2, playing: true }).hero, "$1,299.99");
});

test("story: no text uses em or en dashes", () => {
  for (const scene of [WAITING, OPEN, CLOSING, CLOSED, NOBODY, BAD, ...Object.values(SAMPLES).map((r) => projectArenaScene(r, { sample: true }))]) {
    for (let k = 0; k <= scene.beats.length; k++) {
      assert.doesNotMatch(JSON.stringify(storyFor(scene, pbAt(scene, k))), dashes);
    }
  }
});

test("isEmptyMarket is true for 0 or 1 rows in total and false for 2", () => {
  assert.equal(isEmptyMarket(rows()), true);
  assert.equal(isEmptyMarket(rows({ rounds: [round()] })), true);
  assert.equal(isEmptyMarket(rows({ rounds: [round()], needs: [need()] })), false);
});

test("T7: a caught MIRROR row ranked first gives an inconsistent scene with the safe buyer line", () => {
  const mirror = ranked("b-mirror", 1, 1000, { sellerId: "mirror", origin: "MIRROR", reasons: ["Advocate veto (mirror_not_orderable) [source: https://example.com/x]"] });
  const sim = ranked("b-sim", 2, 1100, { sellerId: "sim" });
  const scene = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results: [mirror, sim], events: [closedBy("mirror")] }));
  assert.equal(scene.phase, "inconsistent");
  assert.equal(scene.winnerBidId, null);
  assert.deepEqual(scene.beats, []);
  assert.equal(scene.offers.length, 2);
  assert.equal(scene.offers.find((o) => o.bidId === "b-mirror")!.knock?.reasonCode, "advocate_veto");
  assert.equal(boardAt(scene, 0).buyerLine, "Winner under review: the market record ranks a caught listing. Nobody is crowned.");
  assert.equal(boardAt(scene, 99).buyerLine, "Winner under review: the market record ranks a caught listing. Nobody is crowned.");
});

test("T8: SAMPLES keep their winners and beat counts", () => {
  const g = projectArenaScene(SAMPLES.gpu, { sample: true });
  assert.deepEqual([g.phase, g.winnerBidId, g.beats.length], ["closed", "bid-round-sample-gpu-seller_1", 6]);
  const d = projectArenaScene(SAMPLES.ssd, { sample: true });
  assert.deepEqual([d.phase, d.winnerBidId, d.beats.length], ["closed", "bid-round-sample-ssd-seller-a", 5]);
});

test("board tally for a round with no winner still sums, with winner 0", () => {
  const results = [result("a", { reasons: [SHIELD] }), result("b", { reasons: [VETO] })];
  const s = projectArenaScene(rows({ rounds: [round({ state: "closed" })], results, events: [closedBy("")] }));
  for (let b = 0; b <= s.beats.length; b++) {
    const t = boardAt(s, b).tally;
    assert.equal(t.winner, 0);
    assert.equal(t.winner + t.outbid + t.caught + t.stillIn, t.bids);
  }
  assert.equal(boardAt(s, s.beats.length).tallyLine, "2 bids: 0 winner, 0 outbid, 2 caught");
});
