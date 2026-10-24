// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { commas, formatMoney } from "./money.ts";

test("commas groups whole numbers by thousands, with no Intl", () => {
  assert.equal(commas(0), "0");
  assert.equal(commas(999), "999");
  assert.equal(commas(1000), "1,000");
  assert.equal(commas(1234567), "1,234,567");
  assert.equal(commas(-1234567), "-1,234,567");
});

test("formatMoney matches the old en-US currency output: no cents for whole dollars, two digits otherwise", () => {
  assert.equal(formatMoney(0), "$0");
  assert.equal(formatMoney(1000), "$1,000");
  assert.equal(formatMoney(1234567.89), "$1,234,567.89");
  assert.equal(formatMoney(12.5), "$12.50");
  assert.equal(formatMoney(0.07), "$0.07");
  assert.equal(formatMoney(999.999), "$1,000.00");
});

test("formatMoney puts the minus before the dollar sign for negatives", () => {
  assert.equal(formatMoney(-1000), "-$1,000");
  assert.equal(formatMoney(-1234567.89), "-$1,234,567.89");
  assert.equal(formatMoney(-0.5), "-$0.50");
});
