// Run with: npm test --prefix web (node --test, no extra dependency).
// #449 PL-24: the home page must not promise more than the README does. Inside the allowance a deal can pay without a
// call; above it only the phone call approves. A claim is checked against the seller's own listing page when it can be read.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), "utf8");
const home = read("../components/Explainer.tsx") + read("../app/page.tsx");
const buyer = read("../components/buyer.tsx");

test("the home page no longer says nothing is paid without a spoken approval", () => {
  assert.ok(!/nothing is paid without your spoken approval/i.test(home));
  assert.ok(!/every claim is checked against the live listing/i.test(home));
});

test("the home page says the allowance can pay on its own and that above it only the call approves", () => {
  assert.ok(!/only your spoken code pays/i.test(home));
  assert.match(home, /inside the allowance you set, a deal can pay on its own/i);
  assert.match(home, /above it, only your phone call approves/i);
});

test("the home page says claims are checked against the seller's listing page when it can be read", () => {
  assert.match(home, /checked against the seller&apos;s own listing page when it can be read/i);
});

test("no other home or receipt line says nothing is paid before a spoken word, approval or matching condition", () => {
  assert.ok(!/until you say the word/i.test(home));
  assert.ok(!/nothing is paid until the condition matches/i.test(home));
  assert.ok(!/nothing is paid until you approve\./i.test(buyer));
  assert.ok(!/nothing is paid without your (spoken|phone) approval/i.test(buyer));
});

test("the home copy has no em or en dashes", () => {
  assert.ok(!/[\u2014\u2013]/.test(home));
});
