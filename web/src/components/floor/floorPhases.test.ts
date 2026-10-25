import test from "node:test";
import assert from "node:assert/strict";
import { REFERENCE, floorScript, phaseAt, type FloorScript } from "./floorPhases.ts";
import { SAMPLES } from "../../lib/arenaFixture.ts";
import { projectArenaScene } from "../../lib/arenaScene.ts";

const firstReveal = (s: FloorScript) => s.phases.findIndex((p) => p.kind === "reveal");
const noEarlyPrice = (s: FloorScript) => {
  const r = firstReveal(s);
  const end = r < 0 ? s.phases.length : r;
  for (const p of s.phases.slice(0, end)) for (const v of Object.values(p.sellers)) assert.equal(v.price, null);
};
const endState = (s: FloorScript) => s.phases[s.phases.length - 1]!.sellers;

test("REFERENCE shape", () => {
  assert.equal(REFERENCE.duration, 24);
  assert.equal(REFERENCE.sim, true);
  const ats = REFERENCE.phases.map((p) => p.at);
  assert.deepEqual(ats, [...ats].sort((a, b) => a - b));
  for (const p of REFERENCE.phases) assert.deepEqual(Object.keys(p.sellers).sort(), ["s1", "s2", "s3", "s4"]);
  assert.ok(firstReveal(REFERENCE) > 0);
  noEarlyPrice(REFERENCE);
});

test("REFERENCE outcomes", () => {
  const end = endState(REFERENCE);
  assert.equal(end.s2!.reason, "shield_block");
  assert.equal(end.s1!.reason, "highest_price");
  assert.equal(end.s3!.reason, "failed_fit");
  assert.equal(end.s4!.state, "winner");
  const deals = REFERENCE.phases.filter((p) => p.deal);
  assert.ok(deals[0]!.deal!.approvedByPhone);
  const paid = REFERENCE.phases.filter((p) => p.deal?.stripeTest);
  assert.ok(paid.length > 0 && paid[0]!.at > deals[0]!.at);
  assert.equal(REFERENCE.phases[REFERENCE.phases.length - 1]!.kind, "paid");
  assert.equal(REFERENCE.sellers.find((s) => s.id === "s3")!.origin, "MIRROR");
  assert.equal(end.s3!.checkedAgo, 42);
  assert.equal(end.s1!.checkedAgo, null);
});

test("no usable rows gives REFERENCE", () => {
  assert.equal(floorScript(null), REFERENCE);
  assert.equal(floorScript(undefined), REFERENCE);
  assert.equal(floorScript({ rounds: [], needs: [], results: [], events: [] }), REFERENCE);
});

test("floorScript(SAMPLES.gpu) follows the scene", () => {
  const s = floorScript(SAMPLES.gpu);
  const scene = projectArenaScene(SAMPLES.gpu);
  assert.equal(s.sim, true);
  assert.equal(s.sellers.length, scene.offers.length);
  noEarlyPrice(s);
  assert.ok(firstReveal(s) > 0);
  const end = endState(s);
  assert.equal(end[scene.winnerBidId!]!.state, "winner");
  assert.equal(s.sellers.find((x) => x.id === scene.winnerBidId)!.name, scene.offers.find((o) => o.bidId === scene.winnerBidId)!.name);
  for (const [id, v] of Object.entries(end)) if (id !== scene.winnerBidId) {
    assert.equal(v.state, "eaten");
    assert.ok(v.reason);
  }
  assert.ok(Object.values(end).some((v) => v.reason === "shield_block"));
  assert.ok(Object.values(end).some((v) => v.reason === "advocate_veto"));
  assert.equal(s.duration, s.phases[s.phases.length - 1]!.at + 6);
  assert.equal(s.phases[0]!.at, 0);
  assert.equal(s.phases[1]!.at, 3);
  assert.equal(s.phases[s.phases.length - 1]!.kind, "deal");
});

test("floorScript(gpu-open) never shows a price", () => {
  const s = floorScript(SAMPLES["gpu-open"]);
  assert.ok(s.phases.length >= 1);
  for (const p of s.phases) {
    assert.equal(p.kind, "sealed");
    for (const v of Object.values(p.sellers)) assert.equal(v.price, null);
  }
  assert.equal(s.sellers.length, 3);
});

test("a closing round stays sealed with the waiting call, never REFERENCE", () => {
  const open = SAMPLES["gpu-open"];
  const s = floorScript({ ...open, rounds: open.rounds.map((r) => ({ ...r, state: "closed" })) });
  assert.notEqual(s, REFERENCE);
  assert.equal(s.sellers.length, 3);
  for (const p of s.phases) for (const v of Object.values(p.sellers)) assert.equal(v.price, null);
  assert.equal(s.phases[0]!.callText, "Round closed. Waiting for the referee's result.");
});

test("a closed round with no offers says no offer passed", () => {
  const open = SAMPLES["gpu-open"];
  const closedEvent = { ...SAMPLES.gpu.events.find((e) => e.kind === "auction_closed")!, refId: open.rounds[0]!.id, sellerId: "" };
  const s = floorScript({ ...open, rounds: open.rounds.map((r) => ({ ...r, state: "closed" })), results: [], events: [closedEvent] });
  assert.notEqual(s, REFERENCE);
  assert.equal(s.phases[0]!.callText, "Round closed. No offer passed the checks.");
  for (const v of Object.values(s.phases[0]!.sellers)) assert.equal(v.price, null);
});

test("phaseAt wraps and clamps", () => {
  assert.equal(phaseAt(REFERENCE, 0), REFERENCE.phases[0]);
  assert.equal(phaseAt(REFERENCE, 4), REFERENCE.phases.find((p) => p.at === 3.6));
  assert.equal(phaseAt(REFERENCE, 24 + 4), phaseAt(REFERENCE, 4));
  assert.equal(phaseAt(REFERENCE, 23.99).kind, "paid");
  assert.equal(phaseAt(REFERENCE, -5), REFERENCE.phases[0]);
  assert.equal(phaseAt(REFERENCE, Number.NaN), REFERENCE.phases[0]);
});

test("an outranked offer is not called the highest price (gpu sample), and REFERENCE keeps its true highest-price call", () => {
  const s = floorScript(SAMPLES.gpu);
  const renew = s.sellers.find((x) => /ReNew/i.test(x.name))!;
  assert.ok(renew);
  const end = endState(s)[renew.id]!;
  assert.equal(end.reason, "outranked");
  assert.match(end.ledger, /^Outranked · /);
  for (const p of s.phases) if (p.callText && p.callText.includes(renew.name)) assert.ok(!/Highest price/.test(p.callText), p.callText);
  const call = s.phases.find((p) => p.kind === "call" && p.callText?.includes("ahead"));
  assert.ok(call, "an outranked call carries the referee's reason text");
  const ref = REFERENCE.phases.find((p) => p.kind === "call")!;
  assert.equal(ref.callText, "Highest price is out: $1,329.00, Seller 1");
  assert.equal(endState(REFERENCE).s1!.reason, "highest_price");
});

test("highest_price is used only when the eaten offer is strictly the priciest still in", () => {
  for (const sample of Object.values(SAMPLES)) {
    const s = floorScript(sample);
    const price = new Map<string, number>();
    for (const p of s.phases) for (const [id, v] of Object.entries(p.sellers)) if (v.price != null) price.set(id, v.price);
    const out = new Set<string>();
    for (const p of s.phases) {
      if (p.kind !== "eat") continue;
      for (const [id, v] of Object.entries(p.sellers)) {
        if (v.state !== "eaten" || out.has(id)) continue;
        if (v.reason === "highest_price") for (const [oid, ov] of Object.entries(p.sellers)) if (oid !== id && !out.has(oid) && ov.state !== "eaten") assert.ok(price.get(oid)! < price.get(id)!, `${id} vs ${oid}`);
        out.add(id);
      }
    }
  }
});
