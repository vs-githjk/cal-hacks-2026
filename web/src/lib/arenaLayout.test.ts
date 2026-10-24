// Run with: npm test --prefix web (node --test, no extra dependency).
// Scenes here are plain object literals so these tests do not depend on how the scene is projected from market rows.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ArenaScene, Beat, Phase, SceneOffer } from "./arenaScene.ts";
import type { Knock, ReasonCode } from "./bracket.ts";
import { seatOf, stageAt } from "./arenaLayout.ts";

const offer = (id: string, over: Partial<SceneOffer> = {}): SceneOffer => ({
  key: `offer:${id}`, bidId: id, rowRef: `round_result/${id}`, sellerId: id, name: id, origin: "SIM", landed: 100, product: "RTX 5070 Ti",
  rank: null, outcome: "ranked", events: [], ...over,
});
const knock = (id: string, reasonCode: ReasonCode): Knock => ({ id, reasonCode, reasonText: reasonCode });
const beat = (kind: Beat["kind"], over: Partial<Beat> = {}): Beat => ({ kind, name: kind, focus: [], advancing: [], knocked: [], caption: "ok", ms: 1000, ...over });
const scene = (over: Partial<ArenaScene> = {}): ArenaScene => ({
  roundId: "r1", sample: true, phase: "open" as Phase, requestLabel: "RTX 5070 Ti", sealedCount: 3, deadline: null, offers: [], beats: [], winnerBidId: null, problem: null, ...over,
});

// a wins; b and c are ranked; d is blocked by the Shield; e is vetoed by the advocate.
const five = (over: Partial<ArenaScene> = {}): ArenaScene => scene({
  phase: "closed", sealedCount: 5,
  offers: [offer("a", { rank: 1, outcome: "winner" }), offer("b", { rank: 2 }), offer("c", { rank: 3 }), offer("d", { outcome: "knocked" }), offer("e", { outcome: "knocked" })],
  winnerBidId: "a",
  beats: [
    beat("arrive"),
    beat("gate", { focus: ["shield", "offer:d"], knocked: [knock("d", "shield_block")] }),
    beat("advocate", { focus: ["advocate", "offer:e"], knocked: [knock("e", "advocate_veto")] }),
    beat("knockout", { name: "Semifinal", focus: ["offer:b", "offer:c"], advancing: ["a", "b"], knocked: [knock("c", "outranked")] }),
    beat("knockout", { name: "Final", focus: ["offer:a", "offer:b"], advancing: ["a"], knocked: [knock("b", "outranked")] }),
    beat("crown", { name: "Winner", focus: ["offer:a"], advancing: ["a"] }),
  ],
  ...over,
});
const ARRIVE = 1, GATE = 2, ADVOCATE = 3, SEMI = 4, FINAL = 5, CROWN = 6;
const radius = (p: { x: number; z: number }) => Math.hypot(p.x, p.z);
const OFFER_KEYS = ["offer:a", "offer:b", "offer:c", "offer:d", "offer:e"];

test("before close no offer is visible and the stack follows sealedCount, capped at 12", () => {
  for (const [sealed, stack] of [[0, 0], [3, 3], [12, 12], [30, 12]] as const) {
    const s = stageAt(scene({ sealedCount: sealed, offers: [] }), 0);
    assert.equal(s.stackCount, stack);
    assert.equal(s.crown, false);
    assert.deepEqual(Object.keys(s.actors).filter((k) => !k.startsWith("anon:")).sort(), ["advocate", "buyer", "referee", "shield"]);
    // one anonymous sealed bidder per envelope, at most 8, with no identity
    const anon = Object.keys(s.actors).filter((k) => k.startsWith("anon:") && s.actors[k]!.visible);
    assert.equal(anon.length, Math.min(sealed, 8));
  }
  const closed = stageAt(five(), 0);
  assert.equal(closed.stackCount, 5);
  for (const k of OFFER_KEYS) assert.equal(closed.actors[k]!.visible, false, k);
  for (const id of ["a", "b", "c", "d", "e"]) assert.equal(closed.cards[id], "stack", id);
  // before arrive, the anonymous bidders stand in the seats the named offers will take
  for (let i = 0; i < 5; i++) {
    assert.equal(closed.actors[`anon:${i}`]!.visible, true);
    assert.equal(closed.actors[`anon:${i}`]!.x, stageAt(five(), 1).actors[OFFER_KEYS[i]!]!.x);
  }
  assert.equal(Object.keys(stageAt(five(), 1).actors).filter((k) => k.startsWith("anon:") && stageAt(five(), 1).actors[k]!.visible).length, 0);
});

test("waiting shows an empty dais with the light on the buyer; closing dims the key light to 70 percent", () => {
  const waiting = stageAt(scene({ phase: "waiting", sealedCount: 0 }), 0);
  assert.equal(waiting.stackCount, 0);
  assert.deepEqual(waiting.focus, ["buyer"]);
  assert.equal(waiting.lightOn, 1);
  assert.equal(stageAt(scene({ phase: "open" }), 0).lightOn, 1);
  assert.equal(stageAt(scene({ phase: "closing" }), 0).lightOn, 0.7);
  assert.equal(stageAt(five(), 0).lightOn, 1);
});

test("the fixed cast stands where the design puts it", () => {
  const s = stageAt(scene(), 0);
  assert.deepEqual([s.actors.buyer!.x, s.actors.buyer!.y, s.actors.buyer!.z, s.actors.buyer!.tier], [0, 0.44, -0.35, 2]);
  assert.deepEqual([s.actors.advocate!.x, s.actors.advocate!.y, s.actors.advocate!.z, s.actors.advocate!.tier], [-4.1, 0, 0.4, 0]);
  assert.deepEqual([s.actors.shield!.x, s.actors.shield!.y, s.actors.shield!.z], [4.1, 0, 0.4]);
  assert.deepEqual([s.actors.referee!.x, s.actors.referee!.y, s.actors.referee!.z], [0, 0.5, 0.35]);
  for (const k of ["buyer", "advocate", "shield", "referee"]) assert.equal(s.actors[k]!.visible, true, k);
});

test("after arrive every offer is on its horseshoe seat with its card held and the stack spent", () => {
  const s = stageAt(five(), ARRIVE);
  for (const [i, k] of OFFER_KEYS.entries()) {
    const p = s.actors[k]!;
    const seat = seatOf(5, i);
    assert.equal(p.visible, true, k);
    assert.equal(p.tier, 0);
    assert.equal(p.dim, false);
    assert.ok(Math.abs(radius(p) - 4.6) < 1e-9, `${k} radius ${radius(p)}`);
    assert.ok(Math.abs(p.x - seat.x) < 1e-9 && Math.abs(p.z - seat.z) < 1e-9);
    // facing the center: the forward vector (sin yaw, cos yaw) points at the origin
    assert.ok(Math.abs(Math.sin(p.yaw) * p.x + Math.cos(p.yaw) * p.z + 4.6) < 1e-9, `${k} faces the center`);
  }
  for (const id of ["a", "b", "c", "d", "e"]) assert.equal(s.cards[id], "held", id);
  assert.equal(s.stackCount, 0);
  // reading order follows the scene order, left to right on screen
  const xs = OFFER_KEYS.map((k) => s.actors[k]!.x);
  assert.deepEqual([...xs].sort((p, q) => p - q), xs);
  assert.ok(xs[0]! < 0 && xs[4]! > 0);
});

test("knocked offers dim, step back to radius 5.8, lower their heads, and drop their cards", () => {
  const gate = stageAt(five(), GATE);
  const d = gate.actors["offer:d"]!;
  assert.equal(d.dim, true);
  assert.ok(Math.abs(radius(d) - 5.8) < 1e-9);
  assert.ok(d.pitch > 0.2 && d.pitch < 0.22, "head down about 12 degrees");
  assert.equal(d.visible, true);
  assert.equal(gate.cards.d, "dropped");
  assert.equal(gate.marks.d, "blocked");
  for (const k of ["offer:a", "offer:b", "offer:c", "offer:e"]) assert.equal(gate.actors[k]!.dim, false, k);
  assert.equal(gate.cards.e, "held");
  assert.deepEqual(gate.focus, ["shield", "offer:d"]);
  assert.equal(gate.aim.shield, "offer:d");
  assert.equal(gate.aim.advocate, null);

  const adv = stageAt(five(), ADVOCATE);
  assert.equal(adv.actors["offer:e"]!.dim, true);
  assert.ok(Math.abs(radius(adv.actors["offer:e"]!) - 5.8) < 1e-9);
  assert.equal(adv.cards.e, "dropped");
  assert.equal(adv.marks.e, "vetoed");
  assert.equal(adv.marks.d, "blocked", "earlier knocks stay knocked");
  assert.equal(adv.cards.d, "dropped");
  assert.equal(adv.aim.advocate, "offer:e");
  assert.equal(adv.aim.shield, null, "the plate settles once the gate beat is over");
});

test("other refusals read as Refused", () => {
  const s = five({ beats: [beat("arrive"), beat("gate", { focus: ["referee", "offer:d"], knocked: [knock("d", "below_floor")] })] });
  assert.equal(stageAt(s, 2).marks.d, "refused");
  assert.equal(stageAt(s, 2).aim.shield, null, "the Shield only turns for its own blocks");
});

test("knockout advancers sit on tier 1 at radius 2.6; outranked offers dim in place with their cards", () => {
  const semi = stageAt(five(), SEMI);
  const seatC = seatOf(5, 2);
  for (const k of ["offer:a", "offer:b"]) {
    const p = semi.actors[k]!;
    assert.equal(p.tier, 1, k);
    assert.equal(p.y, 0.22);
    assert.ok(Math.abs(radius(p) - 2.6) < 1e-9, `${k} advanced radius`);
    assert.equal(p.dim, false);
  }
  const [pa, pb] = [semi.actors["offer:a"]!, semi.actors["offer:b"]!];
  assert.ok(Math.hypot(pa.x - pb.x, pa.z - pb.z) > 0.5, "advanced seats are distinct");
  assert.ok(pa.x < pb.x, "advanced seats keep the scene order");
  const c = semi.actors["offer:c"]!;
  assert.equal(c.dim, true);
  assert.equal(c.tier, 0);
  assert.ok(Math.abs(c.x - seatC.x) < 1e-9 && Math.abs(c.z - seatC.z) < 1e-9, "outranked stays on its seat");
  assert.equal(semi.cards.c, "held");
  assert.equal(semi.marks.c, "outranked");
  assert.equal(semi.cards.a, "held");

  const final = stageAt(five(), FINAL);
  assert.equal(final.actors["offer:a"]!.tier, 1);
  assert.equal(final.actors["offer:b"]!.tier, 1, "b advanced earlier, so it stays on tier 1 when outranked");
  assert.equal(final.actors["offer:b"]!.dim, true);
  assert.deepEqual([final.actors["offer:a"]!.x, final.actors["offer:a"]!.z], [pa.x, pa.z], "survivors do not reshuffle");
});

test("at the crown the winner stands on tier 2 beside the buyer, the spot narrows and everyone else dims", () => {
  const s = stageAt(five(), CROWN);
  const w = s.actors["offer:a"]!;
  assert.equal(s.crown, true);
  assert.deepEqual([w.x, w.y, w.z, w.tier, w.dim], [0.8, 0.44, -0.2, 2, false]);
  assert.equal(s.cards.a, "lifted");
  assert.equal(s.marks.a, "winner");
  for (const k of ["offer:b", "offer:c", "offer:d", "offer:e", "advocate", "shield"]) assert.equal(s.actors[k]!.dim, true, k);
  assert.equal(s.actors.buyer!.dim, false);
  assert.ok(s.focus.includes("offer:a"));
  assert.deepEqual(s.rest, ["offer:a", "buyer"]);
  assert.equal(s.cards.b, "held");
  assert.equal(s.cards.d, "dropped");
  assert.equal(stageAt(five(), FINAL).crown, false);
});

test("a closed round with no winner never crowns", () => {
  const s = five({ winnerBidId: null, beats: [beat("arrive"), beat("crown", { focus: [] })] });
  assert.equal(stageAt(s, 2).crown, false);
  assert.equal(stageAt(s, 2).actors.buyer!.dim, false);
});

test("an inconsistent round shows no offers and no crown, with the light on the table", () => {
  const s = stageAt(five({ phase: "inconsistent", beats: [], winnerBidId: null, problem: "rows disagree" }), 0);
  for (const k of OFFER_KEYS) assert.equal(s.actors[k]!.visible, false, k);
  for (const id of ["a", "b", "c", "d", "e"]) assert.equal(s.cards[id], "hidden", id);
  assert.equal(s.crown, false);
  assert.deepEqual(s.focus, ["referee"]);
  assert.equal(s.stackCount, 5);
});

test("11 offers get distinct seats on two staggered rows and never NaN", () => {
  const ids = Array.from({ length: 11 }, (_, i) => `o${i}`);
  const s = scene({
    phase: "closed", sealedCount: 11, winnerBidId: "o0",
    offers: ids.map((id, i) => offer(id, { rank: i + 1 })),
    beats: [beat("arrive"), beat("knockout", { advancing: ids.slice(0, 6), knocked: ids.slice(6).map((id) => knock(id, "outranked")) }), beat("crown", { focus: ["offer:o0"] })],
  });
  for (let b = 0; b <= 3; b++) {
    const st = stageAt(s, b);
    const seen = new Set<string>();
    for (const [k, p] of Object.entries(st.actors)) {
      for (const n of [p.x, p.y, p.z, p.yaw, p.pitch]) assert.ok(Number.isFinite(n), `${k} beat ${b}`);
      if (k.startsWith("offer:") && p.visible) seen.add(`${p.x.toFixed(4)},${p.z.toFixed(4)},${p.tier}`);
    }
    if (b >= 1) assert.equal(seen.size, 11, `beat ${b} seats`);
  }
  const radii = new Set(ids.map((id) => radius(stageAt(s, 1).actors[`offer:${id}`]!).toFixed(3)));
  assert.deepEqual([...radii].sort(), ["4.600", "5.200"]);
  assert.equal(new Set(Array.from({ length: 7 }, (_, i) => radius(seatOf(7, i)).toFixed(3))).size, 1, "up to 7 offers use one row");
});

test("stageAt is deterministic and clamps the beat", () => {
  const sc = five();
  for (let b = 0; b <= 6; b++) assert.equal(JSON.stringify(stageAt(sc, b)), JSON.stringify(stageAt(sc, b)));
  assert.equal(JSON.stringify(stageAt(sc, 99)), JSON.stringify(stageAt(sc, 6)));
  assert.equal(JSON.stringify(stageAt(sc, -3)), JSON.stringify(stageAt(sc, 0)));
  assert.equal(JSON.stringify(stageAt(sc, 2.7)), JSON.stringify(stageAt(sc, 2)));
});

test("a single offer sits in the middle seat", () => {
  const p = stageAt(scene({ phase: "closed", offers: [offer("solo", { rank: 1 })], beats: [beat("arrive")], winnerBidId: "solo" }), 1).actors["offer:solo"]!;
  assert.ok(Math.abs(p.x) < 1e-9 && Math.abs(p.z + 4.6) < 1e-9);
});

test("a beat with no focus falls back to the light a viewer expects", () => {
  const arrive = stageAt(five(), ARRIVE);
  assert.deepEqual(arrive.focus, []);
  assert.deepEqual(arrive.rest, OFFER_KEYS);
  assert.deepEqual(stageAt(five(), 0).rest, ["buyer", "referee"]);
  assert.deepEqual(stageAt(five(), GATE).rest, ["offer:d"]);
});

test("looksFor is deterministic and gives each seller on stage its own color", async () => {
  const { looksFor } = await import("./arenaLayout.ts");
  const offers = ["a", "b", "c", "d", "e", "f", "g"].map((id) => ({ key: `offer:${id}`, sellerId: id }));
  const l = looksFor(offers);
  assert.equal(new Set(Object.values(l).map((x) => x.color)).size, 7);
  assert.equal(JSON.stringify(looksFor(offers)), JSON.stringify(l));
});
