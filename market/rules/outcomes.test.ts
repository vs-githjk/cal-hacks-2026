import { describe, expect, it } from "vitest";
import {
  BASELINE_HUNT_MINUTES,
  creditsCaptured,
  hoursSaved,
  recallsBlocked,
  savingsVsCheapestPerLine,
  savingsVsMarket,
} from "./outcomes";

// SIM fixture: a GPU and a PSU from Seller A.
const plan = (total: number, feasible = true) => ({
  total,
  feasible,
  allocations: [
    {
      seller_id: "seller-a",
      bid_id: "b1",
      lines: [
        { sku_spec: "gpu-rtx5070ti-retail", quantity: 1, unit_price: 760 },
        { sku_spec: "psu-850w-atx3", quantity: 1, unit_price: 110 },
      ],
    },
  ],
});

describe("outcomes", () => {
  it("savings vs cheapest per line is the difference of totals, with the method stated", () => {
    const o = savingsVsCheapestPerLine(plan(870), plan(885, false), "SIM");
    expect(o.value).toBe(15);
    expect(o.origin).toBe("SIM");
    expect(o.how_computed).toContain("$885.00");
    expect(o.how_computed).toContain("minimum");
  });

  it("savings vs market only counts lines that have a market price, and says how many", () => {
    const o = savingsVsMarket(plan(870), { "gpu-rtx5070ti-retail": { unit_price: 800, label: "eBay sold, Oct 23" } }, "MIRROR");
    expect(o.value).toBe(40);
    expect(o.how_computed).toContain("1 of 2 lines");
    expect(o.how_computed).toContain("eBay sold, Oct 23");
    expect(o.origin).toBe("MIRROR");
  });

  it("savings vs market can be negative and is not clamped", () => {
    expect(savingsVsMarket(plan(870), { "psu-850w-atx3": { unit_price: 100, label: "x" } }, "MIRROR").value).toBe(-10);
  });

  it("credits captured sums the value of lines that failed the receiving check", () => {
    const o = creditsCaptured(
      [
        { result: "rejected", sku_spec: "gpu-rtx5070ti-retail" },
        { result: "accepted", sku_spec: "psu-850w-atx3" },
      ],
      plan(870),
      "SIM",
    );
    expect(o.value).toBe(760);
  });

  it("recalls blocked counts CPSC recall rejections and names CPSC", () => {
    const o = recallsBlocked(["recall: CPSC 26-101", "below floor", "recall: CPSC 26-202"], "LIVE");
    expect(o.value).toBe(2);
    expect(o.how_computed).toContain("CPSC");
  });

  it("hours saved uses the named baseline assumption and says so", () => {
    const o = hoursSaved(6);
    expect(o.value).toBe(Math.round(((BASELINE_HUNT_MINUTES - 6) / 60) * 100) / 100);
    expect(o.how_computed).toContain("assumption");
    expect(o.origin).toBe("SIM");
    expect(hoursSaved(10_000).value).toBe(0);
  });
});
