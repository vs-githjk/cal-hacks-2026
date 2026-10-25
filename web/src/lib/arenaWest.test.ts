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
      assert.ok(gap >= (p ? 65 : 100), `gap ${gap} n=${n} p=${p}`);
    }
  });
});

test("cards stay inside the viewBox with a 40 margin, outs with a 30 margin", () => {
  each((n, o, p) => {
    const l = westLayout(n, o, p);
    assert.equal(l.outs.length, o);
    for (const c of l.cards) assert.ok(c.x >= 40 && c.x <= l.w - 40 && c.y >= 40 && c.y <= l.h - 40, `card out of box n=${n} p=${p}`);
    for (const c of l.outs) assert.ok(c.x >= 30 && c.x <= l.w - 30 && c.y >= 30 && c.y <= l.h - 30, `out of box o=${o} p=${p}`);
  });
});

test("no out point is inside the ring ellipse", () => {
  each((n, o, p) => {
    const l = westLayout(n, o, p);
    for (const c of l.outs) {
      const e = ((c.x - l.ring.cx) / l.ring.rx) ** 2 + ((c.y - l.ring.cy) / l.ring.ry) ** 2;
      assert.ok(e > 1, `out inside ring o=${o} p=${p}`);
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
  assert.equal(westLayout(3, 0, false).scale, 1.7);
  assert.equal(westLayout(6, 0, false).scale, 1.3);
  assert.equal(westLayout(3, 0, true).scale, 1.1);
  assert.equal(westLayout(6, 0, true).scale, 0.9);
});

const rect = (x: number, y: number, hw: number, hh: number) => ({ l: x - hw, r: x + hw, t: y - hh, b: y + hh });
const overlap = (a: ReturnType<typeof rect>, b: ReturnType<typeof rect>, m: number) => a.l < b.r + m && b.l < a.r + m && a.t < b.b + m && b.t < a.b + m;
const cardBox = (c: { x: number; y: number; scale: number }) => rect(c.x, c.y, 36 * c.scale, 24 * c.scale);

function eachCards(fn: (l: ReturnType<typeof westLayout>, n: number, p: boolean) => void) {
  for (const p of [false, true]) for (let n = 1; n <= 8; n++) fn(westLayout(n, 0, p), n, p);
}

test("price cards never overlap each other", () => {
  eachCards((l, n, p) => {
    assert.equal(l.cards.length, n);
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) assert.ok(!overlap(cardBox(l.cards[i]), cardBox(l.cards[j]), 4), `cards ${i},${j} n=${n} p=${p}`);
  });
});

test("each card is nearer its own seller than any other", () => {
  eachCards((l, n, p) => {
    l.cards.forEach((c, i) => {
      const d = (s: { x: number; y: number }) => Math.hypot(c.x - s.x, c.y - s.y);
      l.sellers.forEach((s, j) => { if (j !== i) assert.ok(d(l.sellers[i]) < d(s), `card ${i} vs seller ${j} n=${n} p=${p}`); });
    });
  });
});

test("no card covers another seller's figure", () => {
  eachCards((l, n, p) => {
    l.cards.forEach((c, i) => l.sellers.forEach((s, j) => {
      if (j === i) return;
      const fig = { l: s.x - 35 * l.scale, r: s.x + 35 * l.scale, t: s.y - 132 * l.scale, b: s.y };
      assert.ok(!overlap(cardBox(c), fig, 0), `card ${i} on figure ${j} n=${n} p=${p}`);
    }));
  });
});

test("cards are inside the viewBox, tilted a little, scaled within bounds", () => {
  eachCards((l, n, p) => {
    for (const c of l.cards) {
      const b = cardBox(c);
      assert.ok(b.l >= 0 && b.r <= l.w && b.t >= 0 && b.b <= l.h, `card outside n=${n} p=${p}`);
      assert.ok(Math.abs(c.rot) <= 10 && c.scale > 0 && c.scale <= (p ? 1.5 : 1.8), `rot/scale n=${n} p=${p}`);
    }
  });
});
