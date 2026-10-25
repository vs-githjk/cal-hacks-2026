// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { reachableFrom, safeUrl } from "./url.ts";
import { SELLER_KIT_URL } from "./sellerKit.ts";
import { HYPHENATE_URL } from "./hyphenate.ts";

test("safeUrl returns null for a bare scheme, an empty string and plain text, never throws", () => {
  for (const bad of ["https://", "http://", "", "   ", "not a url", "https:// spaced.example", "sim:fixture"]) assert.equal(safeUrl(bad), null, bad);
});

test("safeUrl refuses non-web schemes", () => {
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl("data:text/html,hi"), null);
});

test("safeUrl keeps a real http or https URL", () => {
  assert.equal(safeUrl("https://www.bestbuy.com/site/x?sku=1"), "https://www.bestbuy.com/site/x?sku=1");
  assert.equal(safeUrl("http://127.0.0.1:8765/shady-sam-gpu-5070ti-lies.html"), "http://127.0.0.1:8765/shady-sam-gpu-5070ti-lies.html");
});

test("reachableFrom: a loopback API seen from a deployed page is null, so the page never fetches 127.0.0.1 (#398)", () => {
  for (const api of ["http://127.0.0.1:8791", "http://localhost:8789/v1/hyphenate", "http://[::1]:8791"])
    assert.equal(reachableFrom(api, "tech-bazaar-app.vercel.app"), null, api);
});

test("reachableFrom: a loopback API from a loopback page, or a real API from anywhere, is kept without a trailing slash", () => {
  assert.equal(reachableFrom("http://127.0.0.1:8791", "localhost"), "http://127.0.0.1:8791");
  assert.equal(reachableFrom("http://localhost:8789/v1/hyphenate/", "127.0.0.1"), "http://localhost:8789/v1/hyphenate");
  assert.equal(reachableFrom("https://kit.example/", "tech-bazaar-app.vercel.app"), "https://kit.example");
});

test("reachableFrom: an empty or unparseable API is null, never throws", () => {
  for (const bad of ["", "not a url", "https://"]) assert.equal(reachableFrom(bad, "localhost"), null, bad);
});

test("the Seller Kit and Hyphenate defaults are loopback, so a deployed page with no env set reaches neither", () => {
  assert.equal(reachableFrom(SELLER_KIT_URL, "tech-bazaar-app.vercel.app"), null);
  assert.equal(reachableFrom(HYPHENATE_URL, "tech-bazaar-app.vercel.app"), null);
});
