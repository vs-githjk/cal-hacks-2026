// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { partRows, SAMPLE_BUILD, stepsUpTo } from "./build.ts";

test("partRows lists the six parts in plan order with the swapped board marked", () => {
  const rows = partRows(SAMPLE_BUILD);
  assert.deepEqual(rows.map((r) => r.part), ["gpu", "cpu", "motherboard", "memory", "storage", "cooler"]);
  const board = rows.find((r) => r.part === "motherboard")!;
  assert.equal(board.state, "swapped");
  assert.equal(board.price, 189);
  assert.equal(rows.find((r) => r.part === "gpu")!.state, "locked");
});

test("a part with no pick stays open, and overBy is in dollars", () => {
  const b = { ...SAMPLE_BUILD, picks: { ...SAMPLE_BUILD.picks, cooler: undefined as never } };
  delete (b.picks as Record<string, unknown>).cooler;
  assert.equal(partRows(b).find((r) => r.part === "cooler")!.state, "open");
  const over = partRows({ ...SAMPLE_BUILD, budgets: { ...SAMPLE_BUILD.budgets, motherboard: 18000 } }).find((r) => r.part === "motherboard")!;
  assert.equal(over.overBy, 9);
});

test("stepsUpTo always keeps the plan line and stops at the end", () => {
  assert.equal(stepsUpTo(SAMPLE_BUILD, 0)[0].kind, "plan");
  assert.equal(stepsUpTo(SAMPLE_BUILD, 999).at(-1)!.kind, "locked");
  assert.ok(SAMPLE_BUILD.steps.every((s) => !/[–—]/.test(s.line)));
});
