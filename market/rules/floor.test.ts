import { describe, expect, it } from "vitest";
import { ANY_CONDITION, checkFloor, checkFloorByCondition, floorKey } from "./floor";

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

describe("floor per (seller, sku_spec, condition)", () => {
  const GPU = "gpu-rtx5070ti-retail";
  const floors = new Map([
    [floorKey(GPU, "new"), 290],
    [floorKey(GPU, "open-box"), 250],
  ]);
  const cond = (l: { offered_condition?: string }) => (l.offered_condition ?? "new") as "new";
  const L = (offered_condition: "new" | "open-box" | "refurbished", unit_price: number, quantity = 2) => ({ sku_spec: GPU, offered_condition, unit_price, quantity });

  it("checks each line against the floor for its own condition", () => {
    expect(checkFloorByCondition([L("new", 300), L("open-box", 260)], floors, cond)).toEqual({ ok: true, reasons: [], lineRejects: ["", ""] });
    expect(checkFloorByCondition([L("new", 260)], floors, cond).ok).toBe(false);
  });

  it("any line below its floor rejects the whole bid with the reason, so a seller cannot hide one", () => {
    const r = checkFloorByCondition([L("new", 300), L("open-box", 240)], floors, cond);
    expect(r.ok).toBe(false);
    expect(r.reasons.join(" ")).toMatch(/open-box.*below this seller's floor/);
  });

  it("a line with no floor set for its condition is rejected on its own; the bid stands", () => {
    const r = checkFloorByCondition([L("new", 300), L("refurbished", 220)], floors, cond);
    expect(r.ok).toBe(true);
    expect(r.lineRejects).toEqual(["", `no floor set for ${GPU} refurbished`]);
  });

  it("a floor for any condition (set_floor without a condition) applies when there is no exact one", () => {
    const any = new Map([[floorKey(GPU, ANY_CONDITION), 280], [floorKey(GPU, "open-box"), 250]]);
    expect(checkFloorByCondition([L("refurbished", 300)], any, cond).lineRejects).toEqual([""]);
    expect(checkFloorByCondition([L("refurbished", 270)], any, cond).ok).toBe(false);
    expect(checkFloorByCondition([L("open-box", 260)], any, cond).ok).toBe(true);
  });

  it("qty_available must be a finite number above 0: 0, -1, NaN and Infinity reject the bid", () => {
    for (const q of [0, -1, NaN, Infinity]) {
      const r = checkFloorByCondition([L("new", 300, q)], floors, cond);
      expect(r.ok, String(q)).toBe(false);
      expect(r.reasons.join(" ")).toMatch(/qty_available/);
    }
  });
});
