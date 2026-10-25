// Run with: npm test --prefix web (node --test, no extra dependency).
// #412 item 3c: the readiness summary the Seller Kit returns with a written shop.
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseCreated } from "./sellerKit.ts";

const base = { id: "corner-pc", name: "Corner PC", origin: "SIM", config_path: "/x/corner-pc.json", run_command: "run" };

test("parseCreated keeps the readiness line and one row per listing page", () => {
  const c = parseCreated({
    ...base,
    readiness: {
      line: "Readiness (LIVE page reads): 1 warns",
      listings: [{ sku: "rtx 5070 ti", url: "https://shop.example-store.net/p", status: "warns", summary: "WARNS: 2 warning(s)" }],
    },
  });
  assert.equal(c?.readiness?.line, "Readiness (LIVE page reads): 1 warns");
  assert.deepEqual(c?.readiness?.listings[0], { sku: "rtx 5070 ti", url: "https://shop.example-store.net/p", status: "warns", summary: "WARNS: 2 warning(s)" });
});

test("a shop with no readiness (an older Seller Kit) still parses, and a malformed readiness is dropped, never invented", () => {
  assert.equal(parseCreated(base)?.readiness, undefined);
  assert.equal(parseCreated({ ...base, readiness: "fine" })?.readiness, undefined);
  const c = parseCreated({ ...base, readiness: { line: "Readiness: not checked (no listing page given)", listings: [{ sku: 1 }, null, "x"] } });
  assert.equal(c?.readiness?.line, "Readiness: not checked (no listing page given)");
  assert.deepEqual(c?.readiness?.listings, []);
});
