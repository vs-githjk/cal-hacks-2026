import test from "node:test";
import assert from "node:assert/strict";
import { SIM_RUN, floorScript, phaseAt, type FloorScript } from "./floorPhases.ts";
import { SAMPLES } from "../../lib/arenaFixture.ts";
import { projectArenaScene } from "../../lib/arenaScene.ts";

const firstReveal = (s: FloorScript) => s.phases.findIndex((p) => p.kind === "reveal");
const noEarlyPrice = (s: FloorScript) => {
  const r = firstReveal(s);
  const end = r < 0 ? s.phases.length : r;
  for (const p of s.phases.slice(0, end)) for (const v of Object.values(p.sellers)) assert.equal(v.price, null);
};
const endState = (s: FloorScript) => s.phases[s.phases.length - 1]!.sellers;

test("no usable rows gives SIM_RUN, which is the gpu sample's script", () => {
  assert.equal(floorScript(null), SIM_RUN);
  assert.equal(floorScript(undefined), SIM_RUN);
  assert.equal(floorScript({ rounds: [], needs: [], results: [], events: [] }), SIM_RUN);
  assert.deepEqual(SIM_RUN.sellers.map((x) => x.name), floorScript(SAMPLES.gpu).sellers.map((x) => x.name));
  assert.deepEqual(SIM_RUN, floorScript(SAMPLES.gpu));
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
  assert.equal(s.phases[s.phases.length - 1]!.kind, "think");
  assert.equal(s.phases[s.phases.length - 2]!.kind, "deal");
  assert.ok(s.phases[s.phases.length - 1]!.deal, "the deal card stays up during the summary");
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

test("a closing round stays sealed with the waiting call, never SIM_RUN", () => {
  const open = SAMPLES["gpu-open"];
  const s = floorScript({ ...open, rounds: open.rounds.map((r) => ({ ...r, state: "closed" })) });
  assert.notEqual(s, SIM_RUN);
  assert.equal(s.sellers.length, 3);
  for (const p of s.phases) for (const v of Object.values(p.sellers)) assert.equal(v.price, null);
  assert.equal(s.phases[0]!.callText, "Round closed. Waiting for the referee's result.");
});

test("a closed round with no offers says no offer passed", () => {
  const open = SAMPLES["gpu-open"];
  const closedEvent = { ...SAMPLES.gpu.events.find((e) => e.kind === "auction_closed")!, refId: open.rounds[0]!.id, sellerId: "" };
  const s = floorScript({ ...open, rounds: open.rounds.map((r) => ({ ...r, state: "closed" })), results: [], events: [closedEvent] });
  assert.notEqual(s, SIM_RUN);
  assert.equal(s.phases[0]!.callText, "Round closed. No offer passed the checks.");
  for (const v of Object.values(s.phases[0]!.sellers)) assert.equal(v.price, null);
});

test("phaseAt wraps and clamps", () => {
  const d = SIM_RUN.duration;
  const mid = SIM_RUN.phases[2]!.at + 0.1;
  assert.equal(phaseAt(SIM_RUN, 0), SIM_RUN.phases[0]);
  assert.equal(phaseAt(SIM_RUN, mid), SIM_RUN.phases[2]);
  assert.equal(phaseAt(SIM_RUN, d + mid), phaseAt(SIM_RUN, mid));
  assert.equal(phaseAt(SIM_RUN, d - 0.01), SIM_RUN.phases[SIM_RUN.phases.length - 1]);
  assert.equal(phaseAt(SIM_RUN, -5), SIM_RUN.phases[0]);
  assert.equal(phaseAt(SIM_RUN, Number.NaN), SIM_RUN.phases[0]);
});

test("an outranked offer is not called the highest price (gpu sample)", () => {
  const s = floorScript(SAMPLES.gpu);
  const renew = s.sellers.find((x) => /ReNew/i.test(x.name))!;
  assert.ok(renew);
  const end = endState(s)[renew.id]!;
  assert.equal(end.reason, "outranked");
  assert.match(end.ledger, /^Outranked · /);
  for (const p of s.phases) if (p.callText && p.callText.includes(renew.name)) assert.ok(!/Highest price/.test(p.callText), p.callText);
  const call = s.phases.find((p) => p.kind === "call" && p.callText?.includes("ahead"));
  assert.ok(call, "an outranked call carries the referee's reason text");
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

const holds = (s: FloorScript) => s.phases.map((p, i) => ({ p, hold: (s.phases[i + 1]?.at ?? s.duration) - p.at })).filter((x) => x.p.kind === "think");

test("real rounds get the buyer, shield, advocate and summary beats within ceilings", () => {
  const s = floorScript(SAMPLES.gpu);
  const beats = holds(s);
  const who = beats.map((b) => b.p.think!.who);
  assert.equal(who[0], "buyer");
  assert.ok(who.includes("shield") && who.includes("advocate"));
  assert.equal(who[who.length - 1], "buyer");
  for (const b of beats) {
    const ceil = b.p.think!.who === "shield" ? 1.2 : b.p === beats[beats.length - 1]!.p ? 6 : 2.5; // the summary is the last phase: 5 s beat plus the 1 s tail before the loop restarts
    assert.ok(b.hold <= ceil + 1e-9, `${b.p.think!.who} holds ${b.hold}`);
  }
  noEarlyPrice(s);
  const adv = s.phases.findIndex((p) => p.think?.who === "advocate");
  assert.equal(s.phases[adv + 1]!.kind, "think");
  assert.equal(s.phases[adv + 2]!.kind, "eat");
});

test("floorScript sellers carry the offer's sellerId as agent", () => {
  const s = floorScript(SAMPLES.gpu);
  assert.ok(s.sellers.length > 0);
  assert.ok(s.sellers.every((x) => typeof x.agent === "string" && x.agent.length > 0));
});
