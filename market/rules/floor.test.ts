import { describe, expect, it } from "vitest";
import { checkFloor, checkQuantity } from "./floor";

// SIM fixture: a GPU and a PSU.
const lines = [
  { sku_spec: "psu-850w-atx3", unit_price: 110, quantity: 1 },
  { sku_spec: "gpu-rtx5070ti-retail", unit_price: 760, quantity: 1 },
];

describe("floor", () => {
  it("passes when every line is at or above the floor", () => {
    expect(checkFloor({ lines }, { "psu-850w-atx3": 110, "gpu-rtx5070ti-retail": 700 })).toEqual({ ok: true });
  });

  it("rejects a line below the floor with a reason naming the line", () => {
    const r = checkFloor({ lines }, { "psu-850w-atx3": 120, "gpu-rtx5070ti-retail": 700 });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reasons[0]).toContain("psu-850w-atx3");
  });

  it("lists every offending line", () => {
    const r = checkFloor({ lines }, { "psu-850w-atx3": 120, "gpu-rtx5070ti-retail": 800 });
    expect(r.ok === false && r.reasons.length).toBe(2);
  });

  it("rejects non-positive or non-finite prices even with no floor set", () => {
    expect(checkFloor({ lines: [{ sku_spec: "case-atx-mid", unit_price: 0, quantity: 1 }] }, {}).ok).toBe(false);
    expect(checkFloor({ lines: [{ sku_spec: "case-atx-mid", unit_price: NaN, quantity: 1 }] }, {}).ok).toBe(false);
  });

  it("rejects a quantity that is not a finite number above 0", () => {
    for (const q of [0, -1, NaN, Infinity, -Infinity]) {
      expect(checkFloor({ lines: [{ sku_spec: "case-atx-mid", unit_price: 90, quantity: q }] }, {}).ok, String(q)).toBe(false);
    }
  });
});

describe("checkQuantity", () => {
  const need = new Map([["gpu-rtx5070ti-retail", 1], ["psu-850w-atx3", 2]]);
  it("accepts quantities equal to the need line", () => {
    expect(checkQuantity([{ sku_spec: "gpu-rtx5070ti-retail", quantity: 1 }, { sku_spec: "psu-850w-atx3", quantity: 2 }], need)).toEqual({ ok: true });
  });
  it("rejects 0, -1, NaN and Infinity with a reason", () => {
    for (const q of [0, -1, NaN, Infinity]) {
      const r = checkQuantity([{ sku_spec: "gpu-rtx5070ti-retail", quantity: q }], need);
      expect(r.ok, String(q)).toBe(false);
      if (!r.ok) expect(r.reasons[0]).toMatch(/quantity/);
    }
  });
  it("rejects a quantity that differs from the need line", () => {
    const r = checkQuantity([{ sku_spec: "psu-850w-atx3", quantity: 1 }], need);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reasons[0]).toContain("asks for 2");
  });
  it("rejects a line the need does not have", () => {
    expect(checkQuantity([{ sku_spec: "case-atx-mid", quantity: 1 }], need).ok).toBe(false);
  });
});
