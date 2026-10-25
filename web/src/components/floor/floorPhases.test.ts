import test from "node:test";
import assert from "node:assert/strict";
import { SAMPLES } from "../../lib/arenaFixture.ts";
import type { ArenaRows, RoundRow } from "../../lib/arenaScene.ts";
import { hudText, planFromRows, planMs, reasonKind } from "./floorPhases.ts";

const EMPTY: ArenaRows = { rounds: [], needs: [], results: [], events: [] };
const ASCII_DASH = /[–—]/;

test("an empty market plays the SIM reference scenario", () => {
  const p = planFromRows(EMPTY);
  assert.equal(p.sample, true);
  assert.equal(p.origin, "SIM");
  assert.ok(p.phases.length > 10);
  assert.equal(p.phases.at(-1)!.kind, "end");
  assert.equal(p.phases.at(-1)!.end?.title, "DEAL");
});

test("sealed phases never carry a price; reveal does", () => {
  const p = planFromRows(SAMPLES.gpu, { sample: true });
  const sealed = p.phases.filter((ph) => ph.kind === "sealed");
  assert.ok(sealed.length >= 1);
  for (const ph of sealed) for (const s of ph.sellers) { assert.equal(s.price, null); assert.equal(s.tag, "SEALED"); }
  const reveal = p.phases.find((ph) => ph.kind === "reveal")!;
  assert.ok(reveal.sellers.every((s) => typeof s.price === "number"));
});

test("an open round holds on sealed envelopes with no price anywhere", () => {
  const p = planFromRows(SAMPLES["gpu-open"], { sample: true });
  assert.equal(p.phases.length, 1);
  assert.equal(p.phases[0]!.hold, true);
  assert.ok(p.phases[0]!.sellers.every((s) => s.price === null && s.tag === "SEALED"));
  assert.ok(!JSON.stringify(p).match(/\$\d/));
});

test("a closing round (closed, no result rows yet) shows no price", () => {
  const closing: ArenaRows = { ...SAMPLES.gpu, results: [], events: SAMPLES.gpu.events.filter((e) => e.kind !== "auction_closed") };
  const p = planFromRows(closing, { sample: true });
  assert.equal(p.phases[0]!.hold, true);
  assert.ok(p.phases[0]!.sellers.every((s) => s.price === null));
});

test("each eliminated seller is dashed at and eaten, with a reason", () => {
  const p = planFromRows(SAMPLES.gpu, { sample: true });
  const eaten = p.phases.at(-1)!.sellers.filter((s) => s.status === "eaten");
  assert.equal(eaten.length, p.phases.filter((ph) => ph.kind === "chomp").length);
  assert.ok(eaten.length >= 3);
  for (const s of eaten) assert.ok(s.reason && /^(EATEN|BLOCKED)/.test(s.tag));
  const kinds = p.phases.map((ph) => ph.kind);
  assert.ok(kinds.indexOf("dash") < kinds.indexOf("chomp"));
});

test("the Shield block, the failed fit and the price reasons all appear in the reference scenario", () => {
  const p = planFromRows(SAMPLES.gpu, { sample: true });
  const reasons = new Set(p.phases.at(-1)!.sellers.map((s) => s.reason));
  assert.ok(reasons.has("shield") && reasons.has("failed_fit") && reasons.has("price"));
  const sh = p.phases.find((ph) => ph.kind === "shield")!;
  assert.ok(sh.shield);
  assert.ok(sh.sellers.some((s) => s.statusLine === "SMELL TEST FAILED"));
  assert.ok(p.phases.some((ph) => ph.kind === "injection" && ph.sellers.some((s) => s.injection)));
});

test("the referee calls every round and the winner is checked, grows and takes the ring", () => {
  const p = planFromRows(SAMPLES.gpu, { sample: true });
  const calls = p.phases.filter((ph) => ph.kind === "referee");
  assert.equal(calls.length, p.phases[0]!.rounds);
  assert.ok(calls.every((c) => c.call && c.refereeArms));
  const win = p.phases.find((ph) => ph.kind === "winner")!;
  const w = win.sellers.find((s) => s.key === p.winnerKey)!;
  assert.equal(w.scale, 1.12);
  assert.equal(w.ring, true);
  assert.equal(w.tint, "mint");
  assert.equal(w.statusLine, "WINNER");
  const kinds = p.phases.map((ph) => ph.kind);
  assert.ok(kinds.lastIndexOf("check") < kinds.indexOf("winner") && kinds.indexOf("winner") < kinds.indexOf("end"));
  assert.equal(p.phases.find((ph) => ph.kind === "check" && ph.sellers.some((s) => s.status === "fit_ok")) !== undefined, true);
});

test("indexes run in order, HUD says round x of y, the part and the sellers", () => {
  const p = planFromRows(SAMPLES.ssd, { sample: true });
  p.phases.forEach((ph, i) => assert.equal(ph.index, i));
  assert.match(hudText(p.phases[0]!.hud), /^Round 1 of 2 · .*SSD.* · 3 sellers · sealed$/);
  assert.match(hudText(p.phases[2]!.hud), /revealed$/);
  assert.match(hudText(p.phases.at(-1)!.hud), /^Deal · .* · \$119\.99$/);
  assert.ok(planMs(p) > 10_000);
});

test("copy has no raw ids, no dashes, no loopback or example.com", () => {
  for (const name of ["gpu", "ssd"] as const) {
    const p = planFromRows(SAMPLES[name], { sample: true });
    const text = p.phases.flatMap((ph) => [hudText(ph.hud), ph.call, ph.pip, ph.end?.line, ...ph.sellers.flatMap((s) => [s.name, s.tag, s.statusLine])]).filter(Boolean).join("\n");
    assert.doesNotMatch(text, /bid-round|seller_\d|seller-[abc]|127\.0\.0\.1|example\.com|round-sample/);
    assert.doesNotMatch(text, ASCII_DASH);
  }
});

test("a live closed round with one ranked offer crowns it without any eliminations", () => {
  const rows: ArenaRows = {
    rounds: SAMPLES.ssd.rounds as RoundRow[], needs: [], events: SAMPLES.ssd.events,
    results: SAMPLES.ssd.results.filter((r) => r.rank === 1),
  };
  const p = planFromRows(rows);
  assert.equal(p.sample, false);
  assert.notEqual(p.origin, "");
  assert.equal(p.phases.at(-1)!.end?.title, "DEAL");
});

test("reason mapping", () => {
  assert.equal(reasonKind("shield_block"), "shield");
  assert.equal(reasonKind("advocate_veto"), "failed_fit");
  assert.equal(reasonKind("outranked"), "price");
  assert.equal(reasonKind("below_floor"), "price");
});

test("the reference run: the 4 current sellers, true labels, Byte Bros wins at $1,299.99, the MIRROR store is refused", () => {
  const p = planFromRows(EMPTY);
  const last = p.phases.at(-1)!;
  assert.equal(p.sellerCount, 4);
  assert.deepEqual(last.sellers.map((s) => s.name).sort(), ["Byte Bros Outlet", "Central Comp", "FlashDeal Frankie", "ReNew Refurb"]);
  assert.equal(last.end?.price, "$1,299.99");
  assert.equal(p.winnerKey, last.sellers.find((s) => s.name === "Byte Bros Outlet")!.key);
  const central = last.sellers.find((s) => s.name === "Central Comp")!;
  assert.equal(central.origin, "MIRROR");
  assert.equal(central.status, "eaten");
  assert.equal(central.reason, "refused");
  assert.ok(last.sellers.filter((s) => s.origin === "SIM").length === 3);
  const text = JSON.stringify(p, (_, v) => (typeof v === "bigint" ? String(v) : v));
  assert.doesNotMatch(text, /Silicon|Bay Area|127\.0\.0\.1|localhost|example\.com|Shield/);
  assert.equal(p.phases[0]!.hud.rounds, 3);
});
