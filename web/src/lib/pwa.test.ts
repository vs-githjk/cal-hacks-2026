// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { badgeAction } from "./pwa.ts";

// The worker is plain JS in public/ so the browser can fetch it; its rules are exported for this test only.
const sw = createRequire(import.meta.url)("../../public/sw.js") as { cacheKind: (url: string, method: string, origin: string) => string | null; CACHE: string };
const O = "https://techbazaar.example";
const kind = (path: string, method = "GET", origin = O) => sw.cacheKind(`${origin}${path}`, method, O);

test("the worker caches the app shell and the offline page, and nothing else", () => {
  assert.equal(kind("/offline"), "shell");
  assert.equal(kind("/_next/static/chunks/main-abc123.js"), "shell");
  assert.equal(kind("/_next/static/css/app.css"), "shell");
  assert.equal(kind("/icons/icon-192.png"), "shell");
  assert.equal(kind("/manifest.webmanifest"), "shell");
});

test("market and agent data is never cached: /v1/*, anything JSON, API routes, image optimiser and data routes", () => {
  for (const p of ["/v1/memory", "/v1/agents", "/v1/agents?x=1", "/V1/memory", "/lot.json", "/sponsor-status.json", "/_next/data/build/buyer.json", "/api/anything", "/_next/image?url=%2Fx.png&w=64&q=75"]) {
    assert.equal(kind(p), null, p);
  }
});

test("pages with personal or live content are not cached either: only the offline page stands in for them", () => {
  for (const p of ["/", "/buyer", "/buyer/purchases", "/buyer/decisions", "/market", "/floor", "/seller/seller-a"]) assert.equal(kind(p), null, p);
});

test("only same-origin GET requests are ever considered", () => {
  assert.equal(kind("/_next/static/a.js", "POST"), null);
  assert.equal(kind("/_next/static/a.js", "GET", "https://elsewhere.example"), null);
  assert.equal(kind("/offline", "PUT"), null);
  assert.equal(kind("not a url"), null);
});

test("the cache is versioned so a new deploy never serves an old shell", () => {
  assert.match(sw.CACHE, /^tb-shell-v\d+$/);
});

test("the app badge shows how many approvals are waiting and clears at zero or on anything unreadable", () => {
  assert.deepEqual(badgeAction(3), { kind: "set", count: 3 });
  assert.deepEqual(badgeAction(1), { kind: "set", count: 1 });
  for (const bad of [0, -1, NaN, Infinity, 2.5, undefined as unknown as number]) assert.deepEqual(badgeAction(bad), { kind: "clear" }, String(bad));
});
