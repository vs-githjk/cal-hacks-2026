// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { callLine, overAllowance, rulerLayout } from "./geometry.ts";

test("callLine draws the allowance to scale against the goal cap", () => {
  assert.equal(callLine(250, 1300)!.autoPct.toFixed(2), "19.23");
  assert.equal(callLine(0, 1300)!.autoPct, 0);
  assert.equal(callLine(1300, 1300)!.autoPct, 100);
  assert.equal(callLine(5000, 1300)!.autoPct, 100, "an allowance above the cap fills the line, never overflows");
});

test("callLine draws nothing for a cap or allowance it cannot trust", () => {
  for (const [a, c] of [[250, 0], [250, -1], [250, NaN], [250, Infinity], [NaN, 1300], [-5, 1300]] as const) assert.equal(callLine(a, c), null, `${a}/${c}`);
});

test("overAllowance is how far a bid is past the allowance, never negative", () => {
  assert.equal(overAllowance(1299.99, 250).toFixed(2), "1049.99");
  assert.equal(overAllowance(200, 250), 0);
  assert.equal(Number.isNaN(overAllowance(NaN, 250)), true);
});

const rows = [
  { label: "ASUS Prime OC", mm: 304 },
  { label: "4-slot cooler card", mm: 336 },
  { label: "MSI Gaming Trio OC", mm: 338 },
  { label: "Gigabyte Gaming OC", mm: 342 },
];

test("the ruler puts 305 mm at the same x for every row", () => {
  const l = rulerLayout(rows, 305);
  assert.ok(l.rows.every((r) => r.limitPct === l.limitPct));
  assert.equal(l.limitPct, ((305 - l.min) / (l.max - l.min)) * 100);
  // a different set of cards still draws the limit where its own axis says, and every row agrees
  const other = rulerLayout([{ label: "short card", mm: 250 }, { label: "long card", mm: 360 }], 305);
  assert.ok(other.rows.every((r) => r.limitPct === other.limitPct));
});

test("a row's bar position matches the axis, and fit is decided against the limit", () => {
  const l = rulerLayout(rows, 305);
  for (const r of l.rows) assert.equal(r.pct, ((r.mm - l.min) / (l.max - l.min)) * 100);
  assert.deepEqual(l.rows.map((r) => [r.fits, r.deltaMm]), [[true, 1], [false, 31], [false, 33], [false, 37]]);
  assert.equal(rulerLayout([{ label: "exact", mm: 305 }], 305).rows[0]!.fits, true, "exactly the limit fits with 0 spare");
});

test("the axis always contains the limit and every card", () => {
  const l = rulerLayout(rows, 305);
  assert.ok(l.min <= 304 && l.max >= 342 && l.min < 305 && l.max > 305);
  for (const r of l.rows) assert.ok(r.pct >= 0 && r.pct <= 100);
});

test("a card with no usable length is left out, never drawn at zero; no limit means no ruler", () => {
  const l = rulerLayout([...rows, { label: "bad", mm: NaN }, { label: "zero", mm: 0 }, { label: "neg", mm: -4 }], 305);
  assert.equal(l!.rows.length, 4);
  assert.equal(rulerLayout(rows, NaN), null);
  assert.equal(rulerLayout(rows, 0), null);
  assert.equal(rulerLayout([], 305), null);
});
