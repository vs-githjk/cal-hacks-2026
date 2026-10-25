// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildAt, capPercent, partRows, planLines, SAMPLE_BUILD, showBuildPlan, stepsUpTo } from "./build.ts";

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

test("buildAt replays the build: parts lock as their step arrives, locked only at the end", () => {
  const start = buildAt(SAMPLE_BUILD, 1);
  assert.equal(start.status, "open");
  assert.equal(start.totalCents, 0);
  const clashAt = SAMPLE_BUILD.steps.findIndex((s) => s.kind === "clash") + 1;
  const mid = buildAt(SAMPLE_BUILD, clashAt);
  assert.deepEqual(Object.keys(mid.picks).sort(), ["cpu", "gpu"]);
  assert.equal(partRows(mid).find((r) => r.part === "motherboard")!.state, "open");
  const end = buildAt(SAMPLE_BUILD, SAMPLE_BUILD.steps.length);
  assert.equal(end.status, "locked");
  assert.equal(end.totalCents, SAMPLE_BUILD.totalCents);
  assert.deepEqual(end.sellers, SAMPLE_BUILD.sellers);
});

test("planLines keeps the plan and the re-plan, in order, and drops picks and plain knockouts", () => {
  assert.deepEqual(planLines(SAMPLE_BUILD).map((s) => s.kind), ["plan", "clash", "swap", "reallocate", "locked"]);
});

test("showBuildPlan: only when live or a ?sample preview", () => {
  assert.equal(showBuildPlan(false, ""), false);
  assert.equal(showBuildPlan(false, "?sample"), true);
  assert.equal(showBuildPlan(false, "?x=1&sample=1"), true);
  assert.equal(showBuildPlan(true, ""), true);
});

test("SAMPLE_BUILD never lets a MIRROR listing win; it is a comparison only", () => {
  const picks = Object.values(SAMPLE_BUILD.picks);
  assert.ok(picks.every((p) => p.origin === "SIM" && p.origin !== ("MIRROR" as string) && !p.seller.includes("Central Computers")));
  assert.ok(SAMPLE_BUILD.steps.every((s) => !s.line.includes("Central Computers")));
  assert.ok(SAMPLE_BUILD.comparisons!.some((c) => c.part === "gpu" && c.origin === "MIRROR"));
});

test("capPercent is 0 for no cap and caps at 100", () => {
  assert.equal(capPercent(100, 0), 0);
  assert.equal(capPercent(300, 200), 100);
  assert.equal(capPercent(100, 200), 50);
});
