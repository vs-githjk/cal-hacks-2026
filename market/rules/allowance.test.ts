import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { ALLOWANCE_LADDER } from "../config";
import { decide, newAllowance, periodKey, raiseOnCleanReceiving, recordAutoSpend, requesterMayApprove, setAllowance } from "./allowance";

const MON = Date.parse("2026-10-19T12:00:00Z");
const DAY = 24 * 3600_000;

describe("allowance ladder", () => {
  it("starts at $0, so the first buy always needs the call", () => {
    const a = newAllowance("vidyut", MON);
    expect(a).toMatchObject({ per_purchase_limit: 0, period_limit: 0, spent_this_period: 0, ladder_step: 0, currency: "USD", period: "week" });
    const d = decide(a, 1, MON);
    expect(d.path).toBe("call");
    expect(d.reason).toMatch(/allowance/);
  });

  it("one clean receiving check raises the ladder one step", () => {
    const a = raiseOnCleanReceiving(newAllowance("vidyut", MON), MON);
    expect(a.ladder_step).toBe(1);
    expect(a.per_purchase_limit).toBe(ALLOWANCE_LADDER[1]!.per_purchase);
    expect(a.period_limit).toBe(ALLOWANCE_LADDER[1]!.per_period);
  });

  it("the ladder stops at its top step", () => {
    let a = newAllowance("vidyut", MON);
    for (let i = 0; i < ALLOWANCE_LADDER.length + 3; i++) a = raiseOnCleanReceiving(a, MON);
    expect(a.ladder_step).toBe(ALLOWANCE_LADDER.length - 1);
  });

  it("inside the allowance a buy auto-approves; above it, or above the period limit, it calls", () => {
    const a = raiseOnCleanReceiving(newAllowance("vidyut", MON), MON);
    const per = a.per_purchase_limit;
    expect(decide(a, per, MON).path).toBe("auto");
    expect(decide(a, per + 0.01, MON).path).toBe("call");
    const spent = { ...a, spent_this_period: a.period_limit - per + 1 };
    expect(decide(spent, per, MON).path).toBe("call");
  });

  it("a non-positive or non-finite amount never auto-approves", () => {
    const a = raiseOnCleanReceiving(raiseOnCleanReceiving(newAllowance("vidyut", MON), MON), MON);
    for (const x of [0, -5, NaN, Infinity]) expect(decide(a, x, MON).path).toBe("call");
  });

  it("spending accrues within a week and resets in the next week", () => {
    let a = raiseOnCleanReceiving(newAllowance("vidyut", MON), MON);
    a = recordAutoSpend(a, 20, MON + DAY);
    expect(a.spent_this_period).toBe(20);
    expect(periodKey("week", MON)).toBe(periodKey("week", MON + 6 * DAY));
    const nextWeek = MON + 7 * DAY;
    expect(decide(a, a.per_purchase_limit, nextWeek).path).toBe("auto");
    expect(recordAutoSpend(a, 5, nextWeek).spent_this_period).toBe(5);
  });

  it("property: an auto-approved buy never exceeds the per-purchase or the period limit", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 6 }), fc.double({ min: -10, max: 2000, noNaN: true }), fc.double({ min: 0, max: 3000, noNaN: true }), (steps, amount, spent) => {
        let a = newAllowance("vidyut", MON);
        for (let i = 0; i < steps; i++) a = raiseOnCleanReceiving(a, MON);
        a = { ...a, spent_this_period: spent };
        const d = decide(a, amount, MON);
        return d.path === "call" || (amount > 0 && amount <= a.per_purchase_limit && spent + amount <= a.period_limit);
      }),
    );
  });
});

describe("requester is never the approver", () => {
  it("refuses an approver who requested the purchase", () => {
    expect(requesterMayApprove("seat-3", "seat-3").ok).toBe(false);
  });
  it("allows a different approver, and a consumer buy with no separate requester", () => {
    expect(requesterMayApprove("seat-3", "lab-admin").ok).toBe(true);
    expect(requesterMayApprove("", "vidyut").ok).toBe(true);
  });
});

describe("setAllowance (the buyer may only tighten; the referee sets up to the ladder's top)", () => {
  const top = ALLOWANCE_LADDER[ALLOWANCE_LADDER.length - 1]!;
  const fresh = newAllowance("vidyut", MON);
  const req = (per: number, period: number, p: "week" | "month" = "week") => ({ per_purchase_limit: per, period_limit: period, period: p });

  it("the referee can set Vidyut's demo allowance; the step is the highest ladder step it reaches", () => {
    const r = setAllowance(fresh, req(250, 500), "referee", MON);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.allowance).toMatchObject({ per_purchase_limit: 250, period_limit: 500, ladder_step: 2, period: "week", updated_at: MON });
  });

  it("refuses negative, non-finite, per-buy above the period limit, an unknown period, and anything above the ladder's top", () => {
    for (const bad of [req(-1, 100), req(NaN, 100), req(10, Infinity), req(200, 100), req(10, 100, "year" as never), req(top.per_purchase + 1, top.per_period), req(10, top.per_period + 1)]) {
      const r = setAllowance(fresh, bad, "referee", MON);
      expect(r.ok).toBe(false);
    }
  });

  it("the buyer can lower a limit but never raise one, and cannot change the period (a fresh $0 allowance stays $0)", () => {
    const a = raiseOnCleanReceiving(raiseOnCleanReceiving(fresh, MON), MON);
    const lower = setAllowance(a, req(40, 100), "buyer", MON);
    expect(lower.ok).toBe(true);
    if (lower.ok) expect(lower.allowance).toMatchObject({ per_purchase_limit: 40, period_limit: 100, ladder_step: 0 });
    expect(setAllowance(a, req(a.per_purchase_limit + 1, a.period_limit), "buyer", MON).ok).toBe(false);
    expect(setAllowance(a, req(a.per_purchase_limit, a.period_limit + 1), "buyer", MON).ok).toBe(false);
    expect(setAllowance(a, req(a.per_purchase_limit, a.period_limit, "month"), "buyer", MON).ok).toBe(false);
    expect(setAllowance(fresh, req(50, 150), "buyer", MON).ok).toBe(false);
  });

  it("keeps what was already spent this period", () => {
    const a = recordAutoSpend(raiseOnCleanReceiving(fresh, MON), 20, MON);
    const r = setAllowance(a, req(30, 100), "buyer", MON + DAY);
    expect(r.ok && r.allowance.spent_this_period).toBe(20);
  });

  it("a clean receiving step after a custom set never lowers a limit", () => {
    const set = setAllowance(fresh, req(250, 500), "referee", MON);
    if (!set.ok) throw new Error("setup");
    const next = raiseOnCleanReceiving(set.allowance, MON);
    expect(next.ladder_step).toBe(3);
    expect(next.per_purchase_limit).toBe(Math.max(250, ALLOWANCE_LADDER[3]!.per_purchase));
    expect(next.period_limit).toBe(Math.max(500, ALLOWANCE_LADDER[3]!.per_period));
    const hi = setAllowance(fresh, req(top.per_purchase, 1000), "referee", MON);
    if (!hi.ok) throw new Error("setup");
    expect(raiseOnCleanReceiving(hi.allowance, MON).per_purchase_limit).toBe(top.per_purchase);
  });
});
