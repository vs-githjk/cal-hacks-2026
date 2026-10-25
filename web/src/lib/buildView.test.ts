// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fetchBuild, parseBuildView, toBuildResult } from "./buildView.ts";
import { partRows, planLines } from "./build.ts";
import { feedBase } from "./agentFeed.ts";

const sample = JSON.parse(readFileSync(new URL("../../../contracts/samples/build-board.sample.json", import.meta.url), "utf8"));

test("Lane D's build sample parses, bad rows drop, and the panel reads parts, sellers, origins and the re-plan", () => {
  const bad = structuredClone(sample);
  bad.parts.push({ part: "gpu", label: "No champion", status: "locked", budget: 1 }, { part: "nic", label: "x", status: "planned", budget: 1 });
  bad.events.push({ at: "", kind: "vibes", text: "x", parts: [] });
  const v = parseBuildView(bad);
  assert.equal(v.rejected, 3);
  assert.equal(v.parts.length, 8);
  assert.throws(() => parseBuildView({ ...sample, budget: "2000" }));

  const dropped = toBuildResult(v);
  assert.equal(dropped.status, "open");
  assert.equal(dropped.rejected, 3);
  const b = toBuildResult(parseBuildView(sample));
  assert.equal(b.status, "locked");
  assert.deepEqual(b.owned, { psu: "750 W PSU", case: "Case (305 mm GPU room)" });
  assert.equal(b.totalCents, 196800);
  assert.equal(b.capCents, 200000);
  assert.equal(b.picks.gpu.origin, "SIM");
  assert.equal(b.picks.cpu.origin, "SIM");
  const rows = partRows(b);
  assert.deepEqual(rows.map((r) => r.part), ["gpu", "cpu", "motherboard", "memory", "storage", "cooler"]);
  assert.equal(rows.find((r) => r.part === "motherboard")!.state, "swapped");
  assert.equal(rows.find((r) => r.part === "gpu")!.seller, "Micro Center");
  assert.deepEqual(planLines(b).map((s) => s.kind), ["plan", "clash", "swap", "locked"]);
});

test("the build feed address: none on a deployed host, local only on loopback", () => {
  assert.equal(feedBase(undefined, "tech-bazaar.example.com"), null);
  assert.ok(feedBase(undefined, "localhost")!.includes("127.0.0.1"));
});

test("approval null is not rejected", () => {
  const v = parseBuildView({ ...structuredClone(sample), approval: null });
  assert.equal(v.rejected, 0);
  assert.equal(v.approval, null);
});

test("a MIRROR champion is kept as a normal row; checks and approval carry; a planned part reads Planned", () => {
  const m = structuredClone(sample);
  m.parts.find((p: { part: string }) => p.part === "gpu").champion.origin = "MIRROR";
  const v = parseBuildView(m);
  assert.equal(v.rejected, 0);
  assert.ok(v.parts.some((p) => p.part === "gpu"));
  assert.equal(toBuildResult(v).picks.gpu.origin, "MIRROR");

  const b = toBuildResult(parseBuildView(sample));
  assert.equal(b.checks!.length, 5);
  assert.ok(b.checks!.some((c) => c.a === "motherboard" || c.b === "motherboard"));
  assert.equal(b.approval!.state, "calling");

  const p = structuredClone(sample);
  const cpu = p.parts.find((x: { part: string }) => x.part === "cpu");
  cpu.status = "planned";
  delete cpu.champion;
  assert.equal(partRows(toBuildResult(parseBuildView(p))).find((r) => r.part === "cpu")!.name, "Planned");
});

test("a failed part with no champion says the round ended, with the feed's reason when given", () => {
  const f = structuredClone(sample);
  const cpu = f.parts.find((x: { part: string }) => x.part === "cpu");
  cpu.status = "failed";
  delete cpu.champion;
  const note = () => partRows(toBuildResult(parseBuildView(f))).find((r) => r.part === "cpu")!.note;
  assert.equal(note(), "Round ended with no eligible bid");
  assert.notEqual(note(), "Waiting for its round");
  cpu.reason = "Every bid failed the socket check";
  assert.equal(note(), "Every bid failed the socket check");
});

test("fetchBuild: 404 means no live build, a posted build is parsed", async () => {
  const real = globalThis.fetch;
  try {
    globalThis.fetch = (async () => new Response("", { status: 404 })) as typeof fetch;
    assert.equal(await fetchBuild("http://feed"), null);
    globalThis.fetch = (async () => Response.json(sample)) as typeof fetch;
    assert.equal((await fetchBuild("http://feed"))!.goalId, "goal-build-1");
    globalThis.fetch = (async () => new Response("", { status: 500 })) as typeof fetch;
    await assert.rejects(fetchBuild("http://feed"));
  } finally {
    globalThis.fetch = real;
  }
});

// web/src/lib/fixtures/build-feed.served.json is a real `python3 demo/build.py --dry-run --out-dir` view run through the feed's
// buyer_view() (scripts/agent_feed.py GET /v1/build); scripts/tests/test_agent_feed.py pins it to what the feed serves.
test("the live build the agent feed serves parses with nothing dropped and replaces the SIM sample in the panel", async () => {
  const served = JSON.parse(readFileSync(new URL("./fixtures/build-feed.served.json", import.meta.url), "utf8"));
  assert.equal(JSON.stringify(served).includes("mandate"), false);
  const real = globalThis.fetch;
  try {
    let url = "";
    globalThis.fetch = (async (u: string) => { url = u; return Response.json(served); }) as typeof fetch;
    const view = (await fetchBuild("http://127.0.0.1:8790"))!;
    assert.equal(url, "http://127.0.0.1:8790/v1/build");
    assert.equal(view.rejected, 0);
    assert.equal(view.goalId, served.goalId);
    const b = toBuildResult(view);
    assert.equal(b.rejected, 0);
    assert.ok(Object.keys(b.picks).length > 0, "the panel shows the live picks");
    assert.ok(Object.values(b.picks).every((p) => ["LIVE", "MIRROR", "SIM"].includes(p.origin as string)));
    assert.equal(b.capCents, Math.round(served.budget * 100));
  } finally {
    globalThis.fetch = real;
  }
});
