// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { advance, edgeForAgent } from "./wire.ts";

const row = (id: number, agentName: string) => ({ id: BigInt(id), agentName });

test("an agent event lights the edge of the role it names, and an unknown name lights nothing", () => {
  assert.equal(edgeForAgent("Tech Bazaar Buyer"), "buyer-advocate");
  assert.equal(edgeForAgent("Quality Advocate"), "buyer-advocate");
  assert.equal(edgeForAgent("Shield Client"), "shield-buyer");
  assert.equal(edgeForAgent("Byte Bros Outlet"), "sellers-shield", "any other named agent is a seller");
  for (const bad of ["", "   "]) assert.equal(edgeForAgent(bad), null, JSON.stringify(bad));
});

test("rows already there when the page loads never pulse", () => {
  const first = advance(null, [row(1, "Shield Client"), row(2, "Quality Advocate")]);
  assert.deepEqual(first.fresh, []);
  assert.equal(first.seen, 2n);
});

test("only a row newer than the last one seen pulses, once, whatever order the table lists them in", () => {
  const a = advance(2n, [row(3, "Byte Bros Outlet"), row(1, "Shield Client"), row(2, "Quality Advocate")]);
  assert.deepEqual(a.fresh.map((r) => r.id), [3n]);
  assert.equal(a.seen, 3n);
  const again = advance(a.seen, [row(3, "Byte Bros Outlet"), row(1, "Shield Client")]);
  assert.deepEqual(again.fresh, [], "the same rows never pulse twice");
  assert.deepEqual(advance(3n, [row(5, "x"), row(4, "y")]).fresh.map((r) => r.id), [4n, 5n], "several new rows pulse in id order");
});

test("a table that empties and refills does not replay history", () => {
  assert.deepEqual(advance(7n, []).fresh, []);
  assert.equal(advance(7n, []).seen, 7n, "the high-water mark is kept");
  assert.deepEqual(advance(7n, [row(4, "a")]).fresh, []);
});
