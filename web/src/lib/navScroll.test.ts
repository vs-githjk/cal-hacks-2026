// Run with: npm test --prefix web (node --test, no extra dependency).
// #449 PL-23/RT-33: at 390 px the top nav scrolls sideways. These pick which edge shows a fade, and how far to scroll
// so the current page's link is not left clipped.
import { test } from "node:test";
import assert from "node:assert/strict";
import { navEdges, scrollToShow } from "./navScroll.ts";

test("navEdges: no overflow shows no fade", () => {
  assert.deepEqual(navEdges({ scrollLeft: 0, clientWidth: 320, scrollWidth: 320 }), { left: false, right: false });
  assert.deepEqual(navEdges({ scrollLeft: 0, clientWidth: 400, scrollWidth: 330 }), { left: false, right: false });
});

test("navEdges: overflowing to the right at the start shows the right fade only", () => {
  assert.deepEqual(navEdges({ scrollLeft: 0, clientWidth: 320, scrollWidth: 380 }), { left: false, right: true });
});

test("navEdges: in the middle both, at the end the left only (sub-pixel rounding is tolerated)", () => {
  assert.deepEqual(navEdges({ scrollLeft: 20, clientWidth: 320, scrollWidth: 380 }), { left: true, right: true });
  assert.deepEqual(navEdges({ scrollLeft: 60, clientWidth: 320, scrollWidth: 380 }), { left: true, right: false });
  assert.deepEqual(navEdges({ scrollLeft: 59.6, clientWidth: 320, scrollWidth: 380 }), { left: true, right: false });
  assert.deepEqual(navEdges({ scrollLeft: 0.4, clientWidth: 320, scrollWidth: 320 }), { left: false, right: false });
});

test("scrollToShow: leaves a visible link alone and brings a clipped one in with a little room", () => {
  const view = { scrollLeft: 0, clientWidth: 300 };
  assert.equal(scrollToShow(view, { offsetLeft: 100, offsetWidth: 60 }), 0);
  assert.equal(scrollToShow(view, { offsetLeft: 260, offsetWidth: 70 }), 330 - 300 + 8);   // clipped on the right
  assert.equal(scrollToShow({ scrollLeft: 120, clientWidth: 300 }, { offsetLeft: 90, offsetWidth: 60 }), 90 - 8);  // clipped on the left
  assert.equal(scrollToShow({ scrollLeft: 5, clientWidth: 300 }, { offsetLeft: 4, offsetWidth: 60 }), 0);          // never below 0
});
