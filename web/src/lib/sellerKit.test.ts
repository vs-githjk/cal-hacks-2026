// Run with: npm test --prefix web (node --test, no extra dependency).
// #398 item 3: the /sell result shows the Injection Screen's pass and the Seller Agent-Readiness Report per listing page.
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseCreated } from "./sellerKit.ts";

const base = { id: "corner-pc", name: "Corner PC", origin: "SIM", config_path: "/x/corner-pc.json", run_command: "run" };

test("parseCreated keeps the readiness report per listing page and the screen's pass", () => {
  const c = parseCreated({
    ...base,
    screen: { verdict: "pass", screener: "listing-injection-screen", rule_ids: [] },
    readiness: [{ url: "https://shop.example/gpu", status: "warns", summary: "An AI shopper cannot confirm the return policy.",
      findings: [{ severity: "warn", what_an_agent_sees: "No return policy on the page.", fix: "Add a return policy." }] }],
  })!;
  assert.equal(c.screen, "pass");
  assert.equal(c.readiness.length, 1);
  assert.equal(c.readiness[0]!.status, "warns");
  assert.equal(c.readiness[0]!.findings[0]!.fix, "Add a return policy.");
});

test("parseCreated drops a malformed readiness row and reads an unknown status as unreadable, never ready", () => {
  const c = parseCreated({ ...base, readiness: [{ url: "https://shop.example/a", status: "great", summary: "", findings: [] }, "junk", { status: "ready" }] })!;
  assert.deepEqual(c.readiness.map((r) => r.status), ["unreadable"]);
  assert.equal(c.screen, null);
});

test("an older kit answer with no report still parses, with no rows", () => {
  const c = parseCreated(base)!;
  assert.deepEqual(c.readiness, []);
});
