// Owner outcome numbers. Each returns its value, how it was computed, and the source badge.
// Savings against cheapest-per-line and against the market are separate numbers, never blended.
import type { Allocation, Outcome, Source } from "./types";
import { money, round2 } from "./types";

/** ASSUMPTION until a kitchen manager gives us their real number in an interview (docs/INTERVIEWS.md). */
export const BASELINE_ORDERING_MINUTES_PER_WEEK = 90;
export const FEE_RATE = 0.15;
export const FEE_CAP_PER_MONTH = 299;

type PlanLike = { total: number; feasible: boolean; allocations: Allocation[] };

const planLines = (p: PlanLike) => p.allocations.flatMap((a) => a.lines);

export function savingsVsCheapestPerLine(plan: PlanLike, naive: PlanLike, source: Source): Outcome {
  const value = round2(naive.total - plan.total);
  let how = `Cheapest bid on every line totals ${money(naive.total)}; this plan totals ${money(plan.total)}. Both include delivery fees and use the same sealed bids.`;
  if (!naive.feasible) how += " The cheapest-per-line plan breaks a supplier minimum, so it could not actually be placed.";
  return { value, how_computed: how, source };
}

export function savingsVsMarket(plan: PlanLike, baseline: Record<string, { unit_price: number; label: string }>, source: Source): Outcome {
  const lines = planLines(plan);
  const priced = lines.filter((l) => baseline[l.sku_spec]);
  const value = round2(priced.reduce((s, l) => s + (baseline[l.sku_spec]!.unit_price - l.unit_price) * l.quantity, 0));
  const labels = [...new Set(priced.map((l) => baseline[l.sku_spec]!.label))];
  return {
    value,
    how_computed:
      `For ${priced.length} of ${lines.length} lines with a market price (${labels.join("; ") || "none"}): market price minus winning price, times quantity. ` +
      `Lines without a market price are left out.`,
    source,
  };
}

export function creditsCaptured(events: { result: string; sku_spec: string }[], plan: PlanLike, source: Source): Outcome {
  const byLine = new Map(planLines(plan).map((l) => [l.sku_spec, l]));
  const rejected = events.filter((e) => e.result === "rejected");
  const value = round2(rejected.reduce((s, e) => s + (byLine.get(e.sku_spec) ? byLine.get(e.sku_spec)!.unit_price * byLine.get(e.sku_spec)!.quantity : 0), 0));
  return {
    value,
    how_computed: `${rejected.length} rejected line(s) at receiving, each credited at the ordered price times quantity.`,
    source,
  };
}

export function recallsBlocked(rejectionReasons: string[], source: Source): Outcome {
  const n = rejectionReasons.filter((r) => r.toLowerCase().startsWith("recall")).length;
  return { value: n, how_computed: `${n} bid line(s) matched an open openFDA food enforcement record and were not ordered.`, source };
}

export function hoursSaved(agentMinutes: number, baselineMinutes = BASELINE_ORDERING_MINUTES_PER_WEEK): Outcome {
  const value = round2(Math.max(0, baselineMinutes - agentMinutes) / 60);
  return {
    value,
    how_computed: `${baselineMinutes} minutes a week of manual ordering (an assumption until a kitchen manager gives us their number) minus ${round2(agentMinutes)} minutes of owner time in the agent's run log.`,
    source: "simulated",
  };
}

export function ourFee(verifiedSavingsThisMonth: number): Outcome {
  const value = round2(Math.min(FEE_CAP_PER_MONTH, Math.max(0, verifiedSavingsThisMonth) * FEE_RATE));
  return {
    value,
    how_computed: `${FEE_RATE * 100}% of ${money(Math.max(0, verifiedSavingsThisMonth))} verified savings this month, capped at ${money(FEE_CAP_PER_MONTH)}.`,
    source: "simulated",
  };
}
