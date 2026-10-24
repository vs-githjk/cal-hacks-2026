import { describe, expect, it } from 'vitest';
import { HOLD_TTL_MS, SOLD_OUT_REASON, availableStock, holdIsActive, soldOutReasons, type HoldLike } from './holds';

const NOW = 1_000_000;
const hold = (over: Partial<HoldLike> = {}): HoldLike => ({
  sellerId: 'seller-a', skuSpec: 'gpu', condition: 'new', qty: 1, state: 'held', expiresAtMs: NOW + 60_000, ...over,
});

describe('hold lifetime', () => {
  it('is the 2 minute approval code lifetime', () => {
    expect(HOLD_TTL_MS).toBe(120_000);
  });

  it('a held unit is active until it expires; a sold unit stays out for good; a released unit is free', () => {
    expect(holdIsActive(hold(), NOW)).toBe(true);
    expect(holdIsActive(hold({ expiresAtMs: NOW }), NOW)).toBe(false); // expiry instant releases
    expect(holdIsActive(hold({ state: 'sold', expiresAtMs: NOW - 1 }), NOW)).toBe(true);
    expect(holdIsActive(hold({ state: 'released' }), NOW)).toBe(false);
  });
});

describe('availableStock', () => {
  it('is the line stock minus active holds on the same seller, sku and condition only', () => {
    const holds = [
      hold({ qty: 2 }),
      hold({ state: 'sold', qty: 1 }),
      hold({ state: 'released', qty: 5 }),
      hold({ expiresAtMs: NOW - 1, qty: 5 }),
      hold({ condition: 'open-box', qty: 9 }),
      hold({ sellerId: 'seller-b', qty: 9 }),
      hold({ skuSpec: 'cpu', qty: 9 }),
    ];
    expect(availableStock(5, holds, 'seller-a', 'gpu', 'new', NOW)).toBe(2);
    expect(availableStock(5, holds, 'seller-a', 'gpu', 'open-box', NOW)).toBe(-4);
  });
});

describe('soldOutReasons', () => {
  const lines = [
    { skuSpec: 'gpu', condition: 'new', quantity: 1 },
    { skuSpec: 'gpu', condition: 'open-box', quantity: 3 },
  ];
  const need = () => 1;

  it('marks only the line whose remaining stock is below the need', () => {
    const holds = [hold({ qty: 1 }), hold({ condition: 'open-box', qty: 1 })];
    expect(soldOutReasons(lines, holds, 'seller-a', NOW, need)).toEqual([SOLD_OUT_REASON, '']);
  });

  it('a seller with spare stock is not skipped while a unit is held', () => {
    expect(soldOutReasons([{ skuSpec: 'gpu', condition: 'new', quantity: 3 }], [hold()], 'seller-a', NOW, need)).toEqual(['']);
  });

  it('stock below the need with no holds is not sold out: the real quantity reason is left to the line check', () => {
    expect(soldOutReasons([{ skuSpec: 'gpu', condition: 'new', quantity: 1 }], [], 'seller-a', NOW, () => 2)).toEqual(['']);
    expect(soldOutReasons([{ skuSpec: 'gpu', condition: 'new', quantity: 0 }], [hold()], 'seller-a', NOW, need)).toEqual(['']);
  });

  it('holds that cause the shortfall still mark the line (stock covers the need, the rest is held)', () => {
    expect(soldOutReasons([{ skuSpec: 'gpu', condition: 'new', quantity: 2 }], [hold()], 'seller-a', NOW, () => 2)).toEqual([SOLD_OUT_REASON]);
  });

  it('with no holds nothing is sold out, and the reason is the plain words the screen shows', () => {
    expect(soldOutReasons(lines, [], 'seller-a', NOW, need)).toEqual(['', '']);
    expect(SOLD_OUT_REASON).toBe('sold out to an earlier round');
  });
});
