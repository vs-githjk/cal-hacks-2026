import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { authorizePayment, findDuplicate, needsApproval } from "./approval";

describe("approval before payment", () => {
  it("allows payment within the limit once the limit is checked", () => {
    expect(authorizePayment({ amount: 500, limit_checked: true, approval_id: "" }, 900).ok).toBe(true);
  });

  it("refuses payment when the limit was never checked", () => {
    const r = authorizePayment({ amount: 10, limit_checked: false, approval_id: "a1" }, 900);
    expect(r.ok).toBe(false);
  });

  it("refuses payment over the limit without an approval", () => {
    const r = authorizePayment({ amount: 1000, limit_checked: true, approval_id: "" }, 900);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reasons[0]).toContain("approval");
  });

  it("allows payment over the limit with an approval", () => {
    expect(authorizePayment({ amount: 1000, limit_checked: true, approval_id: "a1" }, 900).ok).toBe(true);
  });

  it("refuses non-positive or non-finite amounts", () => {
    expect(authorizePayment({ amount: 0, limit_checked: true, approval_id: "a" }, 900).ok).toBe(false);
    expect(authorizePayment({ amount: NaN, limit_checked: true, approval_id: "a" }, 900).ok).toBe(false);
  });

  it("needsApproval is true exactly when amount exceeds the limit", () => {
    expect(needsApproval(901, 900)).toBe(true);
    expect(needsApproval(900, 900)).toBe(false);
  });

  it("property: no unapproved payment ever exceeds the spend limit", () => {
    fc.assert(
      fc.property(fc.double({ min: 0, max: 1e6, noNaN: true }), fc.double({ min: 0, max: 1e6, noNaN: true }), fc.boolean(), (amount, limit, checked) => {
        const r = authorizePayment({ amount, limit_checked: checked, approval_id: "" }, limit);
        return !r.ok || (checked && amount <= limit);
      }),
    );
  });
});

describe("idempotency", () => {
  it("finds an existing order with the same key", () => {
    const orders = [{ id: "o1", idempotency_key: "k1" }];
    expect(findDuplicate(orders, "k1")?.id).toBe("o1");
    expect(findDuplicate(orders, "k2")).toBeUndefined();
  });
  it("treats an empty key as missing, never as a match", () => {
    expect(findDuplicate([{ id: "o1", idempotency_key: "" }], "")).toBeUndefined();
  });
});
