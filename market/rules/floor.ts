// Floor price: no line may be priced below the seller's floor for that item.
import type { BidLine, Result } from "./types";
import { money } from "./types";

export function checkFloor(bid: { lines: BidLine[] }, floors: Record<string, number>): Result {
  const reasons: string[] = [];
  for (const line of bid.lines) {
    if (!Number.isFinite(line.unit_price) || line.unit_price <= 0) {
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
