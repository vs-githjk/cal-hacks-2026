// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { clearCorner, cornerRect } from "./agents.ts";

const VIEW = { w: 1280, h: 800 };
const TILE = { w: 220, h: 120 };
// The /buyer hero card sits top right at 1280.
const HERO = { left: 760, top: 140, right: 1264, bottom: 420 };

test("a corner that does not touch the hero is kept", () => {
  assert.equal(clearCorner("br", TILE, VIEW, HERO), "br");
});

test("a corner over the hero moves to one that does not overlap, never back and forth", () => {
  const hero = { left: 1000, top: 60, right: 1280, bottom: 800 }; // a tall hero down the whole right side
  const c = clearCorner("tr", TILE, VIEW, hero);
  assert.ok(c === "tl" || c === "bl", `got ${c}`);
  assert.equal(clearCorner(c, TILE, VIEW, hero), c, "stable: a second check keeps the same corner");
});

test("when every corner overlaps, the current one stays (no loop)", () => {
  const all = { left: 0, top: 0, right: 1280, bottom: 800 };
  assert.equal(clearCorner("br", TILE, VIEW, all), "br");
});

test("cornerRect places the tile 16 px from the sides, below the header and above the footer", () => {
  assert.deepEqual(cornerRect("tl", TILE, VIEW), { left: 16, top: 76, right: 236, bottom: 196 });
  assert.deepEqual(cornerRect("br", TILE, VIEW), { left: 1044, top: 632, right: 1264, bottom: 752 });
});
