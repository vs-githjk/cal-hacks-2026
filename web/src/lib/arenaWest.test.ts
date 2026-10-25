import { test } from "node:test";
import assert from "node:assert/strict";
import { westLayout } from "./arenaWest.ts";

const each = (fn: (n: number, o: number, p: boolean) => void) => {
  for (const p of [false, true]) for (let n = 0; n <= 8; n++) for (let o = 0; o <= 8; o++) fn(n, o, p);
};

test("sellers are inside the ring and below its center", () => {
  each((n, o, p) => {
    const l = westLayout(n, o, p);
    assert.equal(l.sellers.length, n);
    for (const s of l.sellers) {
      const e = ((s.x - l.ring.cx) / l.ring.rx) ** 2 + ((s.y - l.ring.cy) / l.ring.ry) ** 2;
      assert.ok(e <= 1, `outside ring n=${n} p=${p}`);
      assert.ok(s.y > l.ring.cy, `not below center n=${n} p=${p}`);
    }
  });
});

test("sellers run left to right with room between them", () => {
  each((n, o, p) => {
    const l = westLayout(n, o, p);
    for (let i = 1; i < l.sellers.length; i++) {
      const gap = l.sellers[i].x - l.sellers[i - 1].x;
      assert.ok(gap >= (p ? 70 : 110) * l.scale, `gap ${gap} n=${n} p=${p}`);
    }
  });
});

test("cards and outs stay inside the viewBox with a 40 margin", () => {
  each((n, o, p) => {
    const l = westLayout(n, o, p);
    assert.equal(l.outs.length, o);
    for (const c of [...l.cards, ...l.outs]) {
      assert.ok(c.x >= 40 && c.x <= l.w - 40 && c.y >= 40 && c.y <= l.h - 40, `out of box n=${n} o=${o} p=${p}`);
    }
  });
});

test("n and outs are clamped", () => {
  const l = westLayout(12, 12, false);
  assert.equal(l.sellers.length, 8);
  assert.equal(l.cards.length, 8);
  assert.equal(l.outs.length, 8);
  assert.equal(westLayout(-3, -1, true).sellers.length, 0);
});

test("layout is deterministic", () => {
  assert.deepEqual(westLayout(5, 3, false), westLayout(5, 3, false));
  assert.deepEqual(westLayout(7, 8, true), westLayout(7, 8, true));
});

test("scale values", () => {
  assert.equal(westLayout(3, 0, false).scale, 1);
  assert.equal(westLayout(6, 0, false).scale, 0.85);
  assert.equal(westLayout(3, 0, true).scale, 0.8);
  assert.equal(westLayout(6, 0, true).scale, 0.7);
});
