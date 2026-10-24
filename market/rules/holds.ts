// Stock holds: the last unit goes to the first round that wins it. A round's winning line holds its
// units for the approval call; a later round cannot award a unit that is held or sold. Pure rules,
// the reducers in spacetimedb/src/market.ts keep the rows.

/** The approval code lifetime (pay/approval.py CODE_TTL_SECONDS = 120). A hold lasts as long as the call can run. */
export const HOLD_TTL_MS = 120_000;

/** The reason a later round's line is skipped. Shown as is on the market screen. */
export const SOLD_OUT_REASON = 'sold out to an earlier round';

export type HoldState = 'held' | 'sold' | 'released';

export interface HoldLike {
  sellerId: string;
  skuSpec: string;
  condition: string;
  qty: number;
  state: HoldState;
  expiresAtMs: number;
}

/** Held and not yet expired, or sold. Released and expired holds free their units. */
export function holdIsActive(h: HoldLike, nowMs: number): boolean {
  return h.state === 'sold' || (h.state === 'held' && h.expiresAtMs > nowMs);
}

/** Stock the seller still has on one (sku, condition) line: its stated stock minus every active hold. */
export function availableStock(stock: number, holds: HoldLike[], sellerId: string, skuSpec: string, condition: string, nowMs: number): number {
  const taken = holds
    .filter((h) => h.sellerId === sellerId && h.skuSpec === skuSpec && h.condition === condition && holdIsActive(h, nowMs))
    .reduce((s, h) => s + h.qty, 0);
  return stock - taken;
}

/**
 * Per bid line: '' when the line still has enough stock for the need, else SOLD_OUT_REASON. `condition` on a
 * line is the effective one (the offered condition, else the one the need asked for).
 */
export function soldOutReasons(
  lines: { skuSpec: string; condition: string; quantity: number }[],
  holds: HoldLike[],
  sellerId: string,
  nowMs: number,
  needQty: (skuSpec: string) => number,
): string[] {
  return lines.map((l) =>
    availableStock(l.quantity, holds, sellerId, l.skuSpec, l.condition, nowMs) < needQty(l.skuSpec) ? SOLD_OUT_REASON : '',
  );
}
