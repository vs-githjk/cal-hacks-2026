// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { agentFor, bubblesFrom } from "./arenaAgents.ts";
import { AGENTS } from "./agents.ts";
import { projectArenaScene, offerKey } from "./arenaScene.ts";
import { SAMPLES, SAMPLE_AGENT_LINES } from "./arenaFixture.ts";

const scene = projectArenaScene(SAMPLES.gpu, { sample: true });
const addr = (key: string) => AGENTS.find((a) => a.key === key)!.address;
const ts = (ms: number) => ({ microsSinceUnixEpoch: BigInt(ms) * 1000n });
const row = (key: string, text: string, atMs: number, id = 1n) => ({ id, address: addr(key), text, ts: ts(atMs) });
const NOW = 1_000_000;

test("buyer, advocate and shield map to their Fetch.ai agents by key", () => {
  assert.equal(agentFor("buyer", scene)!.name, "Tech Bazaar Buyer");
  assert.equal(agentFor("advocate", scene)!.handle, "@techbazaaradvocate");
  assert.equal(agentFor("shield", scene)!.key, "shield");
  assert.equal(agentFor("referee", scene), null);
});

test("an offer maps by exact sellerId: seller_N is the agent seller N, never by name", () => {
  const by = (sellerId: string) => scene.offers.find((o) => o.sellerId === sellerId)!;
  assert.equal(agentFor(by("seller_1").key, scene)!.key, "seller1");
  assert.equal(agentFor(by("seller_2").key, scene)!.name, "Silicon Sally's Surplus");
  assert.equal(agentFor(by("seller_3").key, scene)!.name, "FlashDeal Frankie");
  assert.equal(agentFor(by("seller_6").key, scene), null); // MIRROR store, no Agentverse entry
  assert.equal(agentFor(by("seller_5").key, scene), null);
  assert.equal(agentFor(offerKey("not-a-bid"), scene), null);
  const ssd = projectArenaScene(SAMPLES.ssd);
  assert.ok(ssd.offers.every((o) => agentFor(o.key, ssd) === null));
  // a seller whose NAME matches an agent but whose id does not is not that agent
  const fake = { ...scene, offers: scene.offers.map((o, i) => (i === 0 ? { ...o, sellerId: "byte-bros", name: "Byte Bros Outlet" } : o)) };
  assert.equal(agentFor(fake.offers[0]!.key, fake), null);
  // seller_10 is not seller_1
  const ten = { ...scene, offers: scene.offers.map((o, i) => (i === 0 ? { ...o, sellerId: "seller_10" } : o)) };
  assert.equal(agentFor(ten.offers[0]!.key, ten), null);
});

test("bubbles: newest row per actor within 8 s, by exact address", () => {
  const winner = scene.offers.find((o) => o.sellerId === "seller_1")!.key;
  const b = bubblesFrom(
    [
      row("buyer", "old but fresh enough", NOW - 7000, 1n),
      row("buyer", "newest buyer line", NOW - 2000, 2n),
      row("advocate", "too old", NOW - 9000, 3n),
      row("seller1", "Sealed bid sent.", NOW - 1000, 4n),
      { id: 5n, address: "agent1qunknown", text: "stranger", ts: ts(NOW - 100) },
    ],
    NOW,
    scene,
  );
  assert.deepEqual(b, { buyer: "newest buyer line", [winner]: "Sealed bid sent." });
});

test("bubbles: a seller agent with no offer in the scene gets no bubble", () => {
  const open = projectArenaScene(SAMPLES["gpu-open"]);
  assert.deepEqual(bubblesFrom([row("seller1", "hi", NOW - 500)], NOW, open), {});
});

test("bubble text is trimmed, capped at 90 characters, and has no em or en dashes", () => {
  const long = "x".repeat(200);
  const b = bubblesFrom([row("buyer", `  ${long}  `, NOW - 100), row("advocate", "Veto — listed new – page says refurbished", NOW - 100), row("shield", "   ", NOW - 100)], NOW, scene);
  assert.equal(b.buyer!.length, 90);
  assert.ok(b.buyer!.endsWith("…"));
  assert.equal(b.advocate, "Veto, listed new, page says refurbished");
  assert.ok(!("shield" in b));
});

test("the gpu sample uses the real Fetch seller agents with the same outcomes", () => {
  const names = Object.fromEntries(scene.offers.map((o) => [o.sellerId, [o.name, o.outcome, o.condition, o.landed]]));
  assert.deepEqual(names, {
    seller_1: ["Byte Bros Outlet", "winner", "new", 1299.99],
    seller_5: ["ReNew Refurb", "ranked", "refurbished", 1247.02],
    seller_2: ["Silicon Sally's Surplus", "knocked", "open-box", 1150],
    seller_3: ["FlashDeal Frankie", "knocked", "new", 1199],
    seller_6: ["Central Computers", "knocked", "new", 1349.99],
  });
  assert.deepEqual(scene.offers.map((o) => o.knock?.reasonCode), [undefined, "outranked", "shield_block", "advocate_veto", "advocate_veto"]);
  assert.ok(scene.offers.find((o) => o.sellerId === "seller_3")!.sourceUrl);
  const open = projectArenaScene(SAMPLES["gpu-open"]);
  assert.equal(open.phase, "open");
});

test("sample agent lines are SIM voices for the scene's actors, with no budget and no dashes", () => {
  for (const [name, sample] of [["gpu", SAMPLES.gpu], ["ssd", SAMPLES.ssd]] as const) {
    const s = projectArenaScene(sample);
    const lines = SAMPLE_AGENT_LINES[name];
    const keys = new Set<string>(["buyer", "advocate", "shield", ...s.offers.map((o) => o.key)]);
    for (const k of Object.keys(lines)) assert.ok(keys.has(k), `${name}: ${k}`);
    for (const k of ["buyer", "advocate", "shield", ...s.offers.map((o) => o.key)]) assert.ok((lines[k]?.length ?? 0) > 0, `${name} has a line for ${k}`);
    const text = JSON.stringify(lines);
    assert.doesNotMatch(text, /budget|ceiling|approval code|[‒-―]/i);
    for (const l of Object.values(lines).flat()) assert.ok(l!.length <= 90, l);
  }
});
