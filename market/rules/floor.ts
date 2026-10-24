// Floor price and quantity sanity: no line may be priced below the seller's floor for that item,
// and every quantity must be a finite number above 0.
import type { BidLine, Result } from "./types";
import { money } from "./types";

const positive = (x: number) => Number.isFinite(x) && x > 0;

export function checkFloor(bid: { lines: BidLine[] }, floors: Record<string, number>): Result {
  const reasons: string[] = [];
  for (const line of bid.lines) {
    if (!positive(line.quantity)) reasons.push(`${line.sku_spec}: quantity ${line.quantity} is not a number above 0`);
    if (!positive(line.unit_price)) {
      reasons.push(`${line.sku_spec}: price ${line.unit_price} is not a positive number`);
      continue;
    }
    const floor = floors[line.sku_spec];
    if (floor !== undefined && line.unit_price < floor) {
      reasons.push(`${line.sku_spec}: ${money(line.unit_price)} is below this seller's floor of ${money(floor)}`);
    }
  }
  return reasons.length ? { ok: false, reasons } : { ok: true };
}

/** Every line's quantity is finite, above 0 and equal to what the need asked for. */
export function checkQuantity(lines: { sku_spec: string; quantity: number }[], needQty: Map<string, number>): Result {
  const reasons: string[] = [];
  for (const l of lines) {
    const want = needQty.get(l.sku_spec);
    if (want === undefined) reasons.push(`${l.sku_spec}: not part of this need`);
    else if (!positive(l.quantity)) reasons.push(`${l.sku_spec}: quantity ${l.quantity} is not a number above 0`);
    else if (l.quantity !== want) reasons.push(`${l.sku_spec}: quantity ${l.quantity}, the need asks for ${want}`);
  }
  return reasons.length ? { ok: false, reasons } : { ok: true };
}
