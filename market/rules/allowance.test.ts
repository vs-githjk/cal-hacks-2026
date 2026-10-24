import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { ALLOWANCE_LADDER } from "../config";
import { decide, newAllowance, periodKey, raiseOnCleanReceiving, recordAutoSpend, requesterMayApprove } from "./allowance";

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
