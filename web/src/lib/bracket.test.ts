// Run with: npm test --prefix web (node --test, no extra dependency).
// Fixtures are SIM: round_result rows in the shape of web/src/module_bindings (RoundResult), modeled on the
// offline run in demo/out/sample-run.json (same sellers and prices), with reason strings exactly as close_round writes them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildBracket, reasonCode, roundWinner } from "./bracket.ts";

let nextId = 1n;
const row = (over: Record<string, unknown> = {}) => ({
  id: nextId++, roundId: "round-1", bidId: "bid-x", sellerId: "x", persona: "X", rank: 0, landed: 0, reasons: [] as string[],
  lines: [{ skuSpec: "rtx 5070 ti", offeredSpec: "rtx 5070 ti", offeredCondition: "new", unitPrice: 0, quantity: 1 }],
  origin: "SIM", source: "", ...over,
});

// SIM fixture: one closed round, every kind of referee decision.
const sampleRound = () => [
  row({ bidId: "bid-ebay-824742", sellerId: "ebay-824742", persona: "eBay seller ...824742", rank: 1, landed: 1239.99, origin: "MIRROR", source: "https://www.ebay.com/itm/824742" }),
  row({ bidId: "bid-best-buy", sellerId: "best-buy", persona: "Best Buy", rank: 2, landed: 1299.99, origin: "MIRROR", source: "https://www.bestbuy.com/sku/6631085" }),
  row({ bidId: "bid-gadget-grove", sellerId: "gadget-grove", persona: "Gadget Grove (Vedant)", rank: 3, landed: 1286.02, origin: "LIVE" }),
  row({ bidId: "bid-shady-sam", sellerId: "shady-sam", persona: "Shady Sam's Deals", rank: 0, landed: 757.44,
    reasons: ["Bazaar Shield block: hidden instruction to shopping agents", "Advocate veto (advocate.condition) [source: http://127.0.0.1:8765/shady-sam-gpu-5070ti-lies.html]"] }),
  row({ bidId: "bid-bargain-bin", sellerId: "bargain-bin", persona: "Bargain Bin Hardware", rank: 0, landed: 1199,
    reasons: ["Advocate veto (fit.gpu_length) [source: https://bargainbin.example.test/rtx-5070-ti]"] }),
  row({ bidId: "bid-lowball", sellerId: "lowball", persona: "Lowball Direct", rank: 0, landed: 1090, reasons: ["below this seller floor"] }),
  row({ bidId: "bid-ebay-442526", sellerId: "ebay-442526", persona: "eBay seller ...442526", rank: 0, landed: 1399.99, origin: "MIRROR", reasons: ["over_cap: landed $1,399.99 is over the goal cap"] }),
  row({ bidId: "bid-micro-center", sellerId: "micro-center", persona: "Micro Center", rank: 0, landed: 1199.99, origin: "MIRROR", reasons: ["condition: offered unknown, goal asks for new or open-box"] }),
  row({ bidId: "bid-other-round", roundId: "round-0", sellerId: "fair-price-pc", persona: "Fair Price PC", rank: 1, landed: 1 }),
];
const closedEvent = { kind: "auction_closed", refId: "round-1", sellerId: "ebay-824742" };

test("the champion is the round winner: the rank 1 row and the seller auction_closed names", () => {
  const rows = sampleRound();
  const b = buildBracket(rows, "round-1");
  const winner = roundWinner(rows, "round-1", [closedEvent]);
  assert.ok(winner);
  assert.equal(b.champion, winner);
  assert.equal(b.entrants[b.champion!]!.sellerId, closedEvent.sellerId);
  assert.equal(b.stages.at(-1)!.name, "Champion");
});

test("the champion equals the round winner for every field size from 0 to 13 ranked bids, in any row order", () => {
  for (let n = 0; n <= 13; n++) {
    const rows = Array.from({ length: n }, (_, i) => row({ bidId: `b${i}`, sellerId: `s${i}`, rank: i + 1, landed: 1000 + i }));
    rows.reverse();
    const b = buildBracket(rows, "round-1");
    assert.equal(b.champion, roundWinner(rows, "round-1", []), `n=${n}`);
    assert.equal(b.champion, n ? "b0" : null);
  }
});

test("roundWinner refuses a round whose auction_closed names a different seller than rank 1", () => {
  assert.throws(() => roundWinner(sampleRound(), "round-1", [{ ...closedEvent, sellerId: "best-buy" }]), /winner/);
});

test("Gate knocks out refusals (Shield, below floor, over_cap, off need) with their reason; a Shield block wins over a veto on the same bid", () => {
  const gate = buildBracket(sampleRound(), "round-1").stages.find((s) => s.name === "Gate")!;
  const codes = Object.fromEntries(gate.heats.flatMap((h) => h.knocked).map((k) => [k.id, k.reasonCode]));
  assert.deepEqual(codes, { "bid-shady-sam": "shield_block", "bid-lowball": "below_floor", "bid-ebay-442526": "over_cap", "bid-micro-center": "off_need" });
});

test("Heat 1 knocks out advocate vetoes with the rule id and source", () => {
  const heat = buildBracket(sampleRound(), "round-1").stages.find((s) => s.name === "Heat 1")!;
  const k = heat.heats.flatMap((h) => h.knocked);
  assert.equal(k.length, 1);
  assert.deepEqual(k[0], {
    id: "bid-bargain-bin", reasonCode: "advocate_veto", ruleId: "fit.gpu_length", sourceUrl: "https://bargainbin.example.test/rtx-5070-ti",
    reasonText: "Advocate veto (fit.gpu_length)",
  });
});

test("a live veto with detail in the parens keeps the rule id alone and the full detail as text", () => {
  const rows = [row({ bidId: "v", reasons: ["Advocate veto (fit.gpu_length: The card is longer than your case allows) [source: https://www.gigabyte.com/x]"] })];
  const k = buildBracket(rows, "round-1").stages[1]!.heats[0]!.knocked[0]!;
  assert.equal(k.ruleId, "fit.gpu_length");
  assert.equal(k.reasonText, "Advocate veto (fit.gpu_length: The card is longer than your case allows)");
  assert.equal(k.sourceUrl, "https://www.gigabyte.com/x");
});

test("every knocked entrant carries a reason_code drawn from the round's own data", () => {
  const rows = sampleRound();
  const b = buildBracket(rows, "round-1");
  const knocked = b.stages.flatMap((s) => s.heats.flatMap((h) => h.knocked));
  assert.equal(knocked.length, rows.filter((r) => r.roundId === "round-1").length - 1);
  for (const k of knocked) {
    const r = rows.find((x) => x.bidId === k.id)!;
    if (k.reasonCode === "outranked") assert.ok(r.rank > 1);
    else assert.ok(r.reasons.some((x) => reasonCode(x) === k.reasonCode), k.id);
  }
});

test("knockout heats: the referee rank decides, the loser shows both landed prices, and only rows of this round play", () => {
  const b = buildBracket(sampleRound(), "round-1");
  assert.ok(!("bid-other-round" in b.entrants));
  const ko = b.stages.filter((s) => s.kind === "knockout");
  assert.deepEqual(ko.map((s) => s.name), ["Semifinal", "Final"]);
  // 3 ranked: seed 1 has a bye, seeds 2 and 3 meet.
  assert.deepEqual(ko[0]!.heats.map((h) => ({ e: h.entrants, a: h.advances, bye: h.bye })), [
    { e: ["bid-ebay-824742"], a: "bid-ebay-824742", bye: true },
    { e: ["bid-best-buy", "bid-gadget-grove"], a: "bid-best-buy", bye: false },
  ]);
  const lost = ko[0]!.heats[1]!.knocked[0]!;
  assert.equal(lost.reasonCode, "outranked");
  assert.equal(lost.reasonText, "Referee ranked Best Buy #2 ahead: $1,299.99 vs $1,286.02");
});

test("5 sellers plus 6 MIRROR listings make a valid bracket with byes", () => {
  const rows = Array.from({ length: 11 }, (_, i) =>
    row({ bidId: `b${i}`, sellerId: `s${i}`, rank: i + 1, landed: 900 + i * 10, origin: i < 5 ? "SIM" : "MIRROR" }));
  const b = buildBracket(rows, "round-1");
  const ko = b.stages.filter((s) => s.kind === "knockout");
  assert.deepEqual(ko.map((s) => s.name), ["Round of 16", "Quarterfinal", "Semifinal", "Final"]);
  assert.equal(ko[0]!.heats.length, 8);
  assert.equal(ko[0]!.heats.filter((h) => h.bye).length, 5);
  for (let i = 1; i < ko.length; i++) {
    const advanced = ko[i - 1]!.heats.map((h) => h.advances);
    assert.deepEqual(ko[i]!.heats.flatMap((h) => h.entrants).sort(), [...advanced].sort() as string[]);
  }
  assert.equal(b.champion, "b0");
});

test("a single eligible bid is crowned with no heats; no eligible bid has no champion", () => {
  const one = buildBracket([row({ bidId: "solo", rank: 1, landed: 10 })], "round-1");
  assert.equal(one.stages.filter((s) => s.kind === "knockout").length, 0);
  assert.equal(one.champion, "solo");
  const none = buildBracket([row({ bidId: "x", reasons: ["below this seller floor"] })], "round-1");
  assert.equal(none.champion, null);
  assert.equal(none.stages.at(-1)!.name, "No champion");
});

test("an unknown origin becomes SIM; LIVE and MIRROR are kept", () => {
  const b = buildBracket([row({ bidId: "a", rank: 1, origin: "live?" }), row({ bidId: "b", rank: 2, origin: "LIVE" }), row({ bidId: "c", rank: 3, origin: "MIRROR" })], "round-1");
  assert.deepEqual([b.entrants.a!.origin, b.entrants.b!.origin, b.entrants.c!.origin], ["SIM", "LIVE", "MIRROR"]);
});

test("reason codes match the strings close_round and rankBids write", () => {
  assert.equal(reasonCode("below this seller floor"), "below_floor");
  assert.equal(reasonCode("Bazaar Shield quarantine: x"), "shield_block");
  assert.equal(reasonCode("over_cap: landed $1 is over the goal cap"), "over_cap");
  assert.equal(reasonCode("Advocate veto (fit.gpu_length) [source: https://a.test]"), "advocate_veto");
  assert.equal(reasonCode("claim did not match the page: open-box"), "claim_false");
  assert.equal(reasonCode("sold out to an earlier round"), "sold_out");
  assert.equal(reasonCode("variant: offered oc, goal asks for retail"), "off_need");
  assert.equal(reasonCode("rtx: not part of this goal"), "off_need");
  assert.equal(reasonCode("new qty_available 0 is not a number above 0"), "off_need");
  assert.equal(reasonCode("something new"), "refused");
});

test("no dash characters in any label or reason the bracket writes", () => {
  const b = buildBracket(sampleRound(), "round-1");
  const text = JSON.stringify(b.stages.map((s) => [s.name, s.heats.map((h) => h.knocked.map((k) => k.reasonText))]));
  assert.doesNotMatch(text, /[\u2012\u2013\u2014\u2015]/);
});

test("a vetoed MIRROR bid that the referee rows rank first: who takes the champion slot", () => {
  const mirror = row({ bidId: "bid-mirror", sellerId: "mirror", persona: "Central Computers", rank: 1, landed: 1000, origin: "MIRROR",
    reasons: ["Advocate veto (mirror_not_orderable) [source: https://example.com/x]"] });
  const sim = row({ bidId: "bid-sim", sellerId: "sim", persona: "Sim Seller", rank: 2, landed: 1100, origin: "SIM" });
  const rows = [mirror, sim];
  const champion = buildBracket(rows, "round-1").champion;
  // Finding: bracket.ts ranks by `rank > 0` only and never reads the veto reasons, so if close_round ever wrote rank 1 on a
  // non-orderable MIRROR row it would be crowned. Documented as is; the guard today is that close_round gives vetoed rows rank 0.
  assert.equal(champion, "bid-mirror");
  assert.equal(roundWinner(rows, "round-1", []), "bid-mirror");
  // an auction_closed naming the SIM seller does not rescue it: roundWinner throws instead of picking the orderable bid
  assert.throws(() => roundWinner(rows, "round-1", [{ kind: "auction_closed", refId: "round-1", sellerId: "sim" }]), /winner/);
});
