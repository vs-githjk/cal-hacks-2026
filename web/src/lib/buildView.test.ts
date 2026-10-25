// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseBuildView, toBuildResult } from "./buildView.ts";
import { partRows, planLines } from "./build.ts";

const sample = JSON.parse(readFileSync(new URL("../../../contracts/samples/build-board.sample.json", import.meta.url), "utf8"));

test("Lane D's build sample parses, bad rows drop, and the panel reads parts, sellers, origins and the re-plan", () => {
  const bad = structuredClone(sample);
  bad.parts.push({ part: "gpu", label: "No champion", status: "locked", budget: 1 }, { part: "nic", label: "x", status: "planned", budget: 1 });
  bad.events.push({ at: "", kind: "vibes", text: "x", parts: [] });
  const v = parseBuildView(bad);
  assert.equal(v.rejected, 3);
  assert.equal(v.parts.length, 8);
  assert.throws(() => parseBuildView({ ...sample, budget: "2000" }));

  const b = toBuildResult(v);
  assert.equal(b.status, "locked");
  assert.deepEqual(b.owned, { psu: "750 W PSU", case: "Case (305 mm GPU room)" });
  assert.equal(b.totalCents, 196800);
  assert.equal(b.capCents, 200000);
  assert.equal(b.picks.gpu.origin, "MIRROR");
  assert.equal(b.picks.cpu.origin, "SIM");
  const rows = partRows(b);
  assert.deepEqual(rows.map((r) => r.part), ["gpu", "cpu", "motherboard", "memory", "storage", "cooler"]);
  assert.equal(rows.find((r) => r.part === "motherboard")!.state, "swapped");
  assert.equal(rows.find((r) => r.part === "gpu")!.seller, "Central Computers (SF)");
  assert.deepEqual(planLines(b).map((s) => s.kind), ["plan", "clash", "swap", "locked"]);
});
