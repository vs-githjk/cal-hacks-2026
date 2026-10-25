import { test } from "node:test";
import assert from "node:assert/strict";
import { roman } from "./roman.ts";

test("roman converts integers 1..3999", () => {
  assert.equal(roman(1), "I");
  assert.equal(roman(4), "IV");
  assert.equal(roman(6), "VI");
  assert.equal(roman(9), "IX");
  assert.equal(roman(14), "XIV");
  assert.equal(roman(1999), "MCMXCIX");
});

test("roman rejects out of range and non-integers", () => {
  assert.throws(() => roman(0), RangeError);
  assert.throws(() => roman(4000), RangeError);
  assert.throws(() => roman(1.5), RangeError);
});
