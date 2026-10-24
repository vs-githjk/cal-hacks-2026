// Rank sealed bids: landed price minus perks value, lowest first. A line whose condition or
// variant differs from the goal disqualifies the bid. The fee is never read here.
import type { MarketConfig } from "../config";
import type { Bid, BidLine, NeedItem, Result } from "./types";
import { round2 } from "./types";
import { checkQuantity } from "./floor";

export function checkLineSpec(line: BidLine, needItems: Map<string, NeedItem>): Result {
  const item = needItems.get(line.sku_spec);
  if (!item) return { ok: false, reasons: [`${line.sku_spec}: not part of this goal`] };
  const reasons: string[] = [];
  const q = checkQuantity([line], new Map([[item.sku_spec, item.quantity]]));
  if (!q.ok) reasons.push(...q.reasons);
  const offered = line.offered_spec ?? line.sku_spec;
  if (offered !== item.sku_spec) reasons.push(`variant: offered ${offered}, goal asks for ${item.sku_spec}`);
  const cond = line.offered_condition ?? item.condition;
  if (cond !== item.condition) reasons.push(`condition: offered ${cond}, goal asks for ${item.condition}`);
  return reasons.length ? { ok: false, reasons } : { ok: true };
}

/** Sum of line prices. Never trusts the seller's stated total. */
export function landedPrice(bid: Pick<Bid, "lines">): number {
  return round2(bid.lines.reduce((s, l) => s + l.unit_price * l.quantity, 0));
}

export interface RankOptions {
  needItems: Map<string, NeedItem>;
  perksValue?: (bid: Bid) => number;
  verifiedClaims?: (bid: Bid) => number;
  /** Rejections from other checks (floor, CPSC recall, claim check, Shield), by bid id. */
  rejections?: Map<string, string[]>;
  /** Accepted so callers can pass the whole config; the fee in it is deliberately unused. */
  config?: MarketConfig;
}

export interface Ranked {
  bid: Bid;
  rank: number;
  landed: number;
  score: number;
  verified: number;
}

export function rankBids(bids: Bid[], opts: RankOptions): { ranked: Ranked[]; disqualified: { bid: Bid; reasons: string[] }[] } {
  const disqualified: { bid: Bid; reasons: string[] }[] = [];
  const eligible: Omit<Ranked, "rank">[] = [];
  for (const bid of bids) {
    const reasons = [...(opts.rejections?.get(bid.id) ?? [])];
    for (const line of bid.lines) {
      const r = checkLineSpec(line, opts.needItems);
      if (!r.ok) reasons.push(...r.reasons);
    }
    if (reasons.length) {
      disqualified.push({ bid, reasons });
      continue;
    }
    const landed = landedPrice(bid);
    eligible.push({ bid, landed, score: round2(landed - (opts.perksValue?.(bid) ?? 0)), verified: opts.verifiedClaims?.(bid) ?? 0 });
  }
  eligible.sort(
    (a, b) =>
      a.score - b.score ||
      b.verified - a.verified ||
      a.bid.sealed_at - b.bid.sealed_at ||
      (a.bid.id < b.bid.id ? -1 : a.bid.id > b.bid.id ? 1 : 0),
  );
  return { ranked: eligible.map((e, i) => ({ ...e, rank: i + 1 })), disqualified };
}
