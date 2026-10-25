// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { AGENTS } from "./agents.ts";
import { advance, displayNameFor, edgeForAgent, type EdgeId } from "./wire.ts";

const row = (id: number, agentName: string) => ({ id: BigInt(id), agentName });

test("every registered agent lights the edge of its role", () => {
  const want: Record<string, EdgeId> = {
    shield: "shield-buyer",
    buyer: "buyer-advocate",
    advocate: "buyer-advocate",
    seller1: "sellers-shield",
    seller2: "sellers-shield",
    seller3: "sellers-shield",
  };
  assert.equal(AGENTS.length, Object.keys(want).length);
  for (const a of AGENTS) assert.equal(edgeForAgent(a.name), want[a.key], a.name);
  assert.equal(edgeForAgent("  smell test client "), "shield-buyer", "trimmed, case-insensitive");
});

test("the demo bridge names and the pre-rename names map, and any other name lights nothing", () => {
  assert.equal(edgeForAgent("Bazaar Advocate"), "buyer-advocate");
  assert.equal(edgeForAgent("Bazaar Shield"), "shield-buyer");
  assert.equal(edgeForAgent("Tech Bazaar Buyer"), "buyer-advocate", "demo/bridge.py still emits the old buyer name (#448)");
  assert.equal(edgeForAgent("Shield Client"), "shield-buyer");
  assert.equal(edgeForAgent("Quality Advocate"), "buyer-advocate");
  for (const bad of ["Bazaar Caller", "Market Pulse", "Central Comp MIRROR", "", "   ", "Some New Store"]) {
    assert.equal(edgeForAgent(bad), null, JSON.stringify(bad));
  }
});

test("an old or bridge name displays as the registry's current name; a stranger's name shows as is", () => {
  assert.equal(displayNameFor("Tech Bazaar Buyer"), "Fish Market Buyer");
  assert.equal(displayNameFor("bazaar shield"), "Smell Test Client");
  assert.equal(displayNameFor("Byte Bros Outlet"), "Byte Bros Outlet");
  assert.equal(displayNameFor("Some New Store"), "Some New Store");
});

test("rows already there at the first ready call never pulse", () => {
  const first = advance(null, [row(1, "Shield Client"), row(2, "Quality Advocate")], true);
  assert.deepEqual(first.fresh, []);
  assert.equal(first.seen, 2n);
});

test("nothing is recorded or pulsed until the table is ready", () => {
  const early = advance(null, [row(1, "Shield Client")], false);
  assert.equal(early.seen, null);
  assert.deepEqual(early.fresh, []);
  assert.deepEqual(advance(4n, [row(9, "x")], false), { seen: 4n, fresh: [] });
});

test("an empty table that is ready, then its first row, lights it", () => {
  const empty = advance(null, [], true);
  assert.equal(empty.seen, 0n);
  assert.deepEqual(empty.fresh, []);
  const next = advance(0n, [row(1, "Byte Bros Outlet")], true);
  assert.deepEqual(next.fresh.map((r) => r.id), [1n]);
  assert.equal(next.seen, 1n);
});

test("only a row newer than the last one seen pulses, once, whatever order the table lists them in", () => {
  const a = advance(2n, [row(3, "Byte Bros Outlet"), row(1, "Shield Client"), row(2, "Quality Advocate")], true);
  assert.deepEqual(a.fresh.map((r) => r.id), [3n]);
  assert.equal(a.seen, 3n);
  const again = advance(a.seen, [row(3, "Byte Bros Outlet"), row(1, "Shield Client")], true);
  assert.deepEqual(again.fresh, [], "the same rows never pulse twice");
  assert.deepEqual(advance(3n, [row(5, "x"), row(4, "y")], true).fresh.map((r) => r.id), [4n, 5n], "several new rows pulse in id order");
});

test("a table that empties and refills does not replay history", () => {
  assert.deepEqual(advance(7n, [], true).fresh, []);
  assert.equal(advance(7n, [], true).seen, 7n, "the high-water mark is kept");
  assert.deepEqual(advance(7n, [row(4, "a")], true).fresh, []);
});
