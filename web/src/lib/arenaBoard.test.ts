import { test } from "node:test";
import assert from "node:assert/strict";
import { projectArenaScene } from "./arenaScene.ts";
import { boardAt } from "./arenaBoard.ts";
import { SAMPLES } from "./arenaFixture.ts";

const scene = projectArenaScene(SAMPLES.gpu, { sample: true });
const words: Record<string, string> = {
  shield_block: "Blocked by Shield",
  advocate_veto: "Vetoed by Advocate",
  claim_false: "Claim check failed",
};

test("beat 0 after close: sealed cards, nothing revealed", () => {
  assert.equal(scene.phase, "closed");
  const s = boardAt(scene, 0);
  assert.equal(s.track.length, scene.offers.length);
  assert.ok(s.track.every((c) => c.state === "sealed" && c.price === null && c.rank === null));
  assert.deepEqual(s.out, []);
  assert.deepEqual(s.lit, []);
  assert.equal(s.sealedCount, scene.offers.length);
  assert.equal(s.stillIn, null);
});

test("beat 1: offers open with prices; lit follows the first beat", () => {
  const s = boardAt(scene, 1);
  assert.ok(s.track.every((c) => c.state !== "sealed" && c.price !== null));
  const focus = scene.beats[0]!.focus;
  if (focus.includes("referee")) assert.ok(s.lit.includes("referee"));
  assert.equal(s.sealedCount, 0);
  assert.equal(s.stageName, scene.beats[0]!.name);
});

test("first knocking beat moves the offer to the Out rail with its reason", () => {
  const i = scene.beats.findIndex((b) => b.knocked.length > 0);
  assert.ok(i >= 0);
  const knock = scene.beats[i]!.knocked[0]!;
  const s = boardAt(scene, i + 1);
  const outCard = s.out.find((c) => c.bidId === knock.id);
  assert.ok(outCard);
  assert.ok(!s.track.some((c) => c.bidId === knock.id));
  const o = scene.offers.find((x) => x.bidId === knock.id)!;
  const expected = knock.reasonCode === "outranked" ? (o.rank ? `Ranked #${o.rank}` : "Outranked") : (words[knock.reasonCode] ?? "Refused by referee");
  assert.equal(outCard.reason, expected);
  assert.equal(outCard.reasonText, knock.reasonText);
  assert.equal(s.stillIn?.k, s.track.length);
  assert.equal(s.stillIn?.n, scene.offers.length);
});

test("final frame: winner first, ranks on survivors, buyer pays", () => {
  const s = boardAt(scene, scene.beats.length);
  assert.ok(s.winner);
  assert.equal(s.track[0]!.state, "winner");
  assert.equal(s.winner.bidId, scene.winnerBidId);
  assert.equal(s.track.filter((c) => c.state === "winner").length, 1);
  for (const c of s.track.slice(1)) {
    const o = scene.offers.find((x) => x.bidId === c.bidId)!;
    assert.equal(c.rank, o.outcome === "ranked" ? o.rank : null);
  }
  assert.ok(s.buyerLine.includes(s.winner.name) && s.buyerLine.includes(s.winner.price!));
});

test("open round: empty track, sealed envelopes, a sentence", () => {
  const open = projectArenaScene(SAMPLES["gpu-open"], { sample: true });
  assert.equal(open.phase, "open");
  const s = boardAt(open, 0);
  assert.deepEqual(s.track, []);
  assert.equal(s.sealedCount, open.sealedCount);
  assert.ok(s.buyerLine.length > 0);
});

test("beat beyond the end clamps to the final frame", () => {
  assert.deepEqual(boardAt(scene, scene.beats.length + 7), boardAt(scene, scene.beats.length));
});

test("an outranked knock reads Ranked #n, never Refused by referee", () => {
  const out = boardAt(scene, scene.beats.length).out;
  const outranked = scene.offers.filter((o) => o.knock?.reasonCode === "outranked");
  assert.ok(outranked.length > 0);
  for (const o of outranked) {
    const c = out.find((x) => x.bidId === o.bidId)!;
    assert.equal(c.reason, o.rank ? `Ranked #${o.rank}` : "Outranked");
  }
});

test("gpu final frame: Central is on the Out rail, vetoed, and no MIRROR card wins", () => {
  const s = boardAt(scene, scene.beats.length);
  const central = s.out.find((c) => c.sellerId === "seller_6");
  assert.ok(central);
  assert.equal(central.reason, "Vetoed by Advocate");
  assert.equal(central.origin, "MIRROR");
  assert.ok(![...s.track, ...s.out].some((c) => c.origin === "MIRROR" && c.state === "winner"));
});

test("ssd final frame: Seller D is out, refused by the referee", () => {
  const ssd = projectArenaScene(SAMPLES.ssd, { sample: true });
  const d = boardAt(ssd, ssd.beats.length).out.find((c) => c.sellerId === "seller-d");
  assert.ok(d);
  assert.equal(d.reason, "Refused by referee");
});

test("gpu final frame: Out cards carry the advocate's cited source, else the listing URL", () => {
  const out = boardAt(scene, scene.beats.length).out;
  const frankie = out.find((c) => c.sellerId === "seller_3");
  const knock = scene.offers.find((o) => o.sellerId === "seller_3")!.knock;
  assert.ok(frankie && knock?.sourceUrl);
  assert.equal(frankie.sourceUrl, knock.sourceUrl);
  const central = out.find((c) => c.sellerId === "seller_6");
  assert.ok(central?.sourceUrl?.startsWith("https://www.centralcomputer.com/"));
});
