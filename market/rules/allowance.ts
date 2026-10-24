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

export function raiseOnCleanReceiving(a: Allowance, now_ms: number): Allowance {
  const step = Math.min(a.ladder_step + 1, ALLOWANCE_LADDER.length - 1);
  return { ...a, ladder_step: step, ...stepLimits(step), spent_this_period: spentNow(a, now_ms), updated_at: now_ms };
}

/** Nobody who requests a payment can approve it. An empty requester means a consumer's own buy. */
export function requesterMayApprove(requested_by: string, approved_by: string): Result {
  if (requested_by && requested_by === approved_by) return { ok: false, reasons: ["the requester cannot approve their own purchase"] };
  return { ok: true };
}
