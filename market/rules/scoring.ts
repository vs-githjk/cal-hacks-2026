// Rank sealed bids on quality-adjusted landed price, lowest first. A bid's lines for one SKU are
// ALTERNATIVES (new, open-box, ...): the cheapest line whose condition the buyer allows is the one
// that ranks, never a sum. A bid over the spend limit is out ("over_cap"). The fee is never read here.
import type { MarketConfig, QualityWeights } from "../config";
import type { Bid, BidLine, Condition, NeedItem, Result } from "./types";
import { money, round2 } from "./types";

/** Conditions the buyer accepts for an item: allowed_conditions, else just the one it asks for. */
export function allowedConditions(item: NeedItem): Condition[] {
  return item.allowed_conditions?.length ? item.allowed_conditions : [item.condition];
}

export function checkLineSpec(line: BidLine, needItems: Map<string, NeedItem>): Result {
  const item = needItems.get(line.sku_spec);
  if (!item) return { ok: false, reasons: [`${line.sku_spec}: not part of this goal`] };
  const reasons: string[] = [];
  const cond0 = line.offered_condition ?? item.condition;
  // A line's quantity is the stock it offers (qty_available): enough for the need, never summed.
  if (!(Number.isFinite(line.quantity) && line.quantity > 0)) reasons.push(`${cond0} qty_available ${line.quantity} is not a number above 0`);
  else if (line.quantity < item.quantity) reasons.push(`${cond0} qty_available ${line.quantity} is below the ${item.quantity} needed`);
  const offered = line.offered_spec ?? line.sku_spec;
  if (offered !== item.sku_spec) reasons.push(`variant: offered ${offered}, goal asks for ${item.sku_spec}`);
  const cond = line.offered_condition ?? item.condition;
  const allowed = allowedConditions(item);
  if (!allowed.includes(cond)) reasons.push(`condition: offered ${cond}, goal asks for ${allowed.join(" or ")}`);
  return reasons.length ? { ok: false, reasons } : { ok: true };
}

export interface RankOptions {
  needItems: Map<string, NeedItem>;
  perksValue?: (bid: Bid) => number;
  verifiedClaims?: (bid: Bid) => number;
  /** Rejections from other checks (floor, CPSC recall, claim check, Shield, advocate veto), by bid id. */
  rejections?: Map<string, string[]>;
  /** The buyer's cap. A bid whose picked lines cost more is out with reason over_cap. Never shown to sellers. */
  spendLimit?: number;
  /** Quality weights (condition, returns). Absent: the plain landed price ranks. */
  quality?: QualityWeights;
  /** Per-line rejections from the floor check (no floor set for that condition), by bid id. */
  lineRejects?: Map<string, string[]>;
  /** Accepted so callers can pass the whole config; the fee in it is deliberately unused. */
  config?: MarketConfig;
}

export interface Ranked {
  bid: Bid;
  rank: number;
  /** Plain price of the picked lines (no quality adjustment). */
  landed: number;
  /** Quality-adjusted landed price less perks value: what the ranking sorts on. */
  score: number;
  verified: number;
  /** Indexes into bid.lines of the picked (cheapest allowed) line per SKU. */
  picked: number[];
}

export interface Disqualified {
  bid: Bid;
  reasons: string[];
  /** Cheapest line per SKU, for display; 0 when no line has a usable price. */
  landed: number;
}

/** What a line costs for this need: unit price times the NEED quantity (the line's quantity is stock). */
const needQty = (l: BidLine, needItems: Map<string, NeedItem>) => needItems.get(l.sku_spec)?.quantity ?? l.quantity;
const costFor = (needItems: Map<string, NeedItem>) => (l: BidLine) => {
  const c = l.unit_price * needQty(l, needItems);
  return Number.isFinite(c) ? c : Infinity;
};

/** Per SKU: the cheapest allowed line (first on a tie), or the reasons the cheapest line failed. */
function pickLines(bid: Bid, needItems: Map<string, NeedItem>, lineRejects: string[] = []) {
  const cost = costFor(needItems);
  const bySku = new Map<string, number[]>();
  bid.lines.forEach((l, i) => bySku.set(l.sku_spec, [...(bySku.get(l.sku_spec) ?? []), i]));
  const picked: number[] = [];
  const reasons: string[] = [];
  const cheapestAny: number[] = [];
  for (const idx of bySku.values()) {
    const checked = idx.map((i) => ({
      i,
      r: lineRejects[i] ? ({ ok: false, reasons: [lineRejects[i]!] } as Result) : checkLineSpec(bid.lines[i]!, needItems),
    }));
    const cheaper = <T extends { i: number }>(a: T, b: T): T => (cost(bid.lines[b.i]!) < cost(bid.lines[a.i]!) ? b : a);
    cheapestAny.push(checked.reduce(cheaper).i);
    const ok = checked.filter((c) => c.r.ok);
    if (ok.length) picked.push(ok.reduce(cheaper).i);
    else {
      const r = checked.reduce(cheaper).r;
      if (!r.ok) reasons.push(...r.reasons);
    }
  }
  return { picked, reasons: [...new Set(reasons)], cheapestAny };
}

const returnsDays = (perks: string[]) => Math.max(0, ...perks.map((p) => Number(/(\d+)[- ]day returns?/i.exec(p)?.[1] ?? 0)));

function qualityAdjusted(bid: Bid, picked: BidLine[], needItems: Map<string, NeedItem>, w: QualityWeights): number {
  const returns = returnsDays(bid.perks) >= w.min_returns_days ? 0 : w.no_returns_adj;
  return picked.reduce((s, l) => {
    const cond = l.offered_condition ?? needItems.get(l.sku_spec)?.condition ?? "new";
    return s + l.unit_price * needQty(l, needItems) * (1 + (w.condition_adj[cond] ?? 0) + returns);
  }, 0);
}

export function rankBids(bids: Bid[], opts: RankOptions): { ranked: Ranked[]; disqualified: Disqualified[] } {
  const disqualified: Disqualified[] = [];
  const eligible: Omit<Ranked, "rank">[] = [];
  for (const bid of bids) {
    const reasons = [...(opts.rejections?.get(bid.id) ?? [])];
    const { picked, reasons: lineReasons, cheapestAny } = pickLines(bid, opts.needItems, opts.lineRejects?.get(bid.id));
    const cost = costFor(opts.needItems);
    reasons.push(...lineReasons);
    const pickedLines = picked.map((i) => bid.lines[i]!);
    const landed = round2(pickedLines.reduce((s, l) => s + cost(l), 0));
    if (!lineReasons.length && opts.spendLimit !== undefined && landed > opts.spendLimit + 1e-9) {
      reasons.push(`over_cap: landed ${money(landed)} is over the goal cap`);
    }
    if (reasons.length) {
      const shown = cheapestAny.reduce((s, i) => s + cost(bid.lines[i]!), 0);
      disqualified.push({ bid, reasons, landed: round2(Number.isFinite(shown) ? shown : 0) });
      continue;
    }
    const adjusted = opts.quality ? qualityAdjusted(bid, pickedLines, opts.needItems, opts.quality) : landed;
    eligible.push({ bid, landed, score: round2(adjusted - (opts.perksValue?.(bid) ?? 0)), verified: opts.verifiedClaims?.(bid) ?? 0, picked });
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
