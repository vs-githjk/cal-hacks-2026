// Rank sealed bids: landed price minus perks value, lowest first. Wrong spec disqualifies.
import type { Bid, BidLine, Result, SpecCard } from "./types";
import { round2 } from "./types";

export function checkLineSpec(line: BidLine, specCards: Map<string, SpecCard>): Result {
  const card = specCards.get(line.sku_spec);
  if (!card) return { ok: false, reasons: [`${line.sku_spec}: no spec card for this item`] };
  const offered = line.offered_spec ?? line.sku_spec;
  if (offered === card.sku_spec || card.allowed_substitutes.includes(offered)) return { ok: true };
  return { ok: false, reasons: [`${card.item_name}: offered ${offered}, spec is ${card.sku_spec} (not equivalent)`] };
}

/** Sum of line prices. Never trusts the supplier's stated total. */
export function landedPrice(bid: Pick<Bid, "lines">): number {
  return round2(bid.lines.reduce((s, l) => s + l.unit_price * l.quantity, 0));
}

export interface RankOptions {
  specCards: Map<string, SpecCard>;
  perksValue?: (bid: Bid) => number;
  verifiedClaims?: (bid: Bid) => number;
  /** Rejections from other checks (floor, recall, failed claim, Shield), by bid id. */
  rejections?: Map<string, string[]>;
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
      const r = checkLineSpec(line, opts.specCards);
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
