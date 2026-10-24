// Buyer outcome numbers. Each returns its value, how it was computed, and the origin badge.
// Savings against cheapest-per-line and against the market are separate numbers, never blended,
// and SIM numbers are never added to LIVE or MIRROR ones. The seller fee lives in fees.ts.
import type { Allocation, Origin, Outcome } from "./types";
import { money, round2 } from "./types";

/** ASSUMPTION until a buyer gives us their real number in an interview (docs/INTERVIEWS.md). */
export const BASELINE_HUNT_MINUTES = 90;

type PlanLike = { total: number; feasible: boolean; allocations: Allocation[] };

const planLines = (p: PlanLike) => p.allocations.flatMap((a) => a.lines);

export function savingsVsCheapestPerLine(plan: PlanLike, naive: PlanLike, origin: Origin): Outcome {
  const value = round2(naive.total - plan.total);
  let how = `Cheapest bid on every line totals ${money(naive.total)}; this plan totals ${money(plan.total)}. Both include delivery fees and use the same sealed bids.`;
  if (!naive.feasible) how += " The cheapest-per-line plan breaks a seller minimum, so it could not actually be placed.";
  return { value, how_computed: how, origin };
}

export function savingsVsMarket(plan: PlanLike, baseline: Record<string, { unit_price: number; label: string }>, origin: Origin): Outcome {
  const lines = planLines(plan);
  const priced = lines.filter((l) => baseline[l.sku_spec]);
  const value = round2(priced.reduce((s, l) => s + (baseline[l.sku_spec]!.unit_price - l.unit_price) * l.quantity, 0));
  const labels = [...new Set(priced.map((l) => baseline[l.sku_spec]!.label))];
  return {
    value,
    how_computed:
      `For ${priced.length} of ${lines.length} lines with a dated market price (${labels.join("; ") || "none"}): market price minus winning price, times quantity. ` +
      `Lines without a market price are left out.`,
    origin,
  };
}

export function creditsCaptured(events: { result: string; sku_spec: string }[], plan: PlanLike, origin: Origin): Outcome {
  const byLine = new Map(planLines(plan).map((l) => [l.sku_spec, l]));
  const rejected = events.filter((e) => e.result === "rejected");
  const value = round2(
    rejected.reduce((s, e) => {
      const l = byLine.get(e.sku_spec);
      return s + (l ? l.unit_price * l.quantity : 0);
    }, 0),
  );
  return {
    value,
    how_computed: `${rejected.length} line(s) failed the receiving check, each credited at the ordered price times quantity.`,
    origin,
  };
}

export function recallsBlocked(rejectionReasons: string[], origin: Origin): Outcome {
  const n = rejectionReasons.filter((r) => r.toLowerCase().startsWith("recall")).length;
  return { value: n, how_computed: `${n} bid line(s) matched a CPSC recall (CPSC recalls API) and were not bought.`, origin };
}

export function hoursSaved(agentMinutes: number, baselineMinutes = BASELINE_HUNT_MINUTES): Outcome {
  const value = round2(Math.max(0, baselineMinutes - agentMinutes) / 60);
  return {
    value,
    how_computed: `${baselineMinutes} minutes of hunting and comparing listings by hand (an assumption until a buyer gives us their number) minus ${round2(agentMinutes)} minutes of buyer time in the agent's log.`,
    origin: "SIM",
  };
}
