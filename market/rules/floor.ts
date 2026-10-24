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

export const floorKey = (sku_spec: string, condition: string) => `${sku_spec}|${condition}`;

export interface FloorCheck {
  /** False rejects the whole bid: a line below its floor, or a bad price or qty_available. */
  ok: boolean;
  reasons: string[];
  /** Per line: "" when the line may be picked, else why not (a missing floor for its condition). */
  lineRejects: string[];
}

/**
 * Floors per (seller, sku_spec, condition), checked for one seller's bid. A line's quantity is the
 * stock it offers (qty_available) and must be a finite number above 0.
 */
export function checkFloorByCondition(lines: BidLine[], floors: Map<string, number>, conditionOf: (l: BidLine) => string): FloorCheck {
  const reasons: string[] = [];
  const lineRejects = lines.map((line) => {
    const tag = `${line.sku_spec} ${conditionOf(line)}`;
    if (!positive(line.quantity)) reasons.push(`${tag}: qty_available ${line.quantity} is not a number above 0`);
    if (!positive(line.unit_price)) {
      reasons.push(`${tag}: price ${line.unit_price} is not a positive number`);
      return "";
    }
    const floor = floors.get(floorKey(line.sku_spec, conditionOf(line)));
    if (floor === undefined) return `no floor set for ${tag}`;
    if (line.unit_price < floor) reasons.push(`${tag}: ${money(line.unit_price)} is below this seller's floor of ${money(floor)}`);
    return "";
  });
  return { ok: reasons.length === 0, reasons, lineRejects };
}
