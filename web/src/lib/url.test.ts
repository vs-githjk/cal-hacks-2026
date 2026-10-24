// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { safeUrl } from "./url.ts";

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
