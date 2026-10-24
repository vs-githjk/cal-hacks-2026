// The allowance ladder: what the agent may spend without calling the buyer. Field names follow
// D's contracts/Allowance.schema.json. Starts at $0, so a new buyer's first buy always calls.
import { ALLOWANCE_LADDER } from "../config";
import type { Result } from "./types";
import { money, round2 } from "./types";

export type Period = "week" | "month";

export interface Allowance {
  buyer_id: string;
  currency: "USD";
  per_purchase_limit: number;
  period_limit: number;
  period: Period;
  spent_this_period: number;
  ladder_step: number;
  /** Epoch ms of the last change; also marks which period spent_this_period belongs to. */
  updated_at: number;
}

const DAY = 24 * 3600_000;

/** Weeks start Monday 00:00 UTC; months are calendar months in UTC. */
export function periodKey(period: Period, at_ms: number): string {
  const d = new Date(at_ms);
  if (period === "month") return `${d.getUTCFullYear()}-${d.getUTCMonth() + 1}`;
  const mondayMs = at_ms - ((d.getUTCDay() + 6) % 7) * DAY;
  const m = new Date(mondayMs);
  return `w${m.getUTCFullYear()}-${m.getUTCMonth() + 1}-${m.getUTCDate()}`;
}

function stepLimits(step: number) {
  const s = ALLOWANCE_LADDER[Math.min(step, ALLOWANCE_LADDER.length - 1)]!;
  return { per_purchase_limit: s.per_purchase, period_limit: s.per_period };
}

export function newAllowance(buyer_id: string, now_ms: number, period: Period = "week"): Allowance {
  return { buyer_id, currency: "USD", ...stepLimits(0), period, spent_this_period: 0, ladder_step: 0, updated_at: now_ms };
}

/** Spending counted in the current period only. */
function spentNow(a: Allowance, now_ms: number) {
  return periodKey(a.period, a.updated_at) === periodKey(a.period, now_ms) ? a.spent_this_period : 0;
}

export function decide(a: Allowance, amount: number, now_ms: number): { path: "auto" | "call"; reason: string } {
  if (!(Number.isFinite(amount) && amount > 0)) return { path: "call", reason: "amount is not a positive number" };
  if (a.per_purchase_limit <= 0) return { path: "call", reason: "allowance is $0, so this buy needs your call" };
  if (amount > a.per_purchase_limit) {
    return { path: "call", reason: `${money(amount)} is above your ${money(a.per_purchase_limit)} allowance per buy` };
  }
  const spent = spentNow(a, now_ms);
  if (spent + amount > a.period_limit) {
    return { path: "call", reason: `this buy would take you past your ${money(a.period_limit)} allowance this ${a.period}` };
  }
  return { path: "auto", reason: `${money(amount)} is within your allowance` };
}

export function recordAutoSpend(a: Allowance, amount: number, now_ms: number): Allowance {
  return { ...a, spent_this_period: round2(spentNow(a, now_ms) + amount), updated_at: now_ms };
}

/** One step up. A limit that was set by hand above the next step is kept: a clean delivery never lowers it. */
export function raiseOnCleanReceiving(a: Allowance, now_ms: number): Allowance {
  const step = Math.min(a.ladder_step + 1, ALLOWANCE_LADDER.length - 1);
  const next = stepLimits(step);
  return {
    ...a, ladder_step: step,
    per_purchase_limit: Math.max(a.per_purchase_limit, next.per_purchase_limit),
    period_limit: Math.max(a.period_limit, next.period_limit),
    spent_this_period: spentNow(a, now_ms), updated_at: now_ms,
  };
}

export interface AllowanceRequest { per_purchase_limit: number; period_limit: number; period: Period }
export type SetAllowanceResult = { ok: true; allowance: Allowance } | { ok: false; reasons: string[] };

/**
 * set_allowance. The referee (the demo operator) may set any limits up to the ladder's top step.
 * The buyer may only tighten their own: a raise comes from clean deliveries, so a stolen or
 * confused session cannot talk a fresh $0 allowance into auto-spending. The step shown is the
 * highest ladder step whose limits the new numbers reach; spending this period is kept.
 */
export function setAllowance(a: Allowance, req: AllowanceRequest, by: "buyer" | "referee", now_ms: number): SetAllowanceResult {
  const top = ALLOWANCE_LADDER[ALLOWANCE_LADDER.length - 1]!;
  const reasons: string[] = [];
  const { per_purchase_limit: per, period_limit: lim, period } = req;
  if (period !== "week" && period !== "month") reasons.push("period must be week or month");
  if (!(Number.isFinite(per) && per >= 0)) reasons.push("per_purchase_limit must be a number of at least 0");
  if (!(Number.isFinite(lim) && lim >= 0)) reasons.push("period_limit must be a number of at least 0");
  if (reasons.length === 0) {
    if (per > lim) reasons.push("per_purchase_limit cannot be above period_limit");
    if (per > top.per_purchase || lim > top.per_period) {
      reasons.push(`limits cannot go above the top step (${money(top.per_purchase)} per buy, ${money(top.per_period)} per period)`);
    }
    if (by === "buyer") {
      if (per > a.per_purchase_limit || lim > a.period_limit) reasons.push("a buyer can lower their allowance; it goes up with clean deliveries");
      if (period !== a.period) reasons.push("a buyer cannot change the period");
    }
  }
  if (reasons.length > 0) return { ok: false, reasons };
  let step = 0;
  ALLOWANCE_LADDER.forEach((s, i) => { if (per >= s.per_purchase && lim >= s.per_period) step = i; });
  return {
    ok: true,
    allowance: { ...a, per_purchase_limit: round2(per), period_limit: round2(lim), period, ladder_step: step, spent_this_period: spentNow(a, now_ms), updated_at: now_ms },
  };
}

/** Nobody who requests a payment can approve it. An empty requester means a consumer's own buy. */
export function requesterMayApprove(requested_by: string, approved_by: string): Result {
  if (requested_by && requested_by === approved_by) return { ok: false, reasons: ["the requester cannot approve their own purchase"] };
  return { ok: true };
}
