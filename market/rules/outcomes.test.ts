import { describe, expect, it } from "vitest";
import {
  BASELINE_ORDERING_MINUTES_PER_WEEK,
  creditsCaptured,
  hoursSaved,
  ourFee,
  recallsBlocked,
  savingsVsCheapestPerLine,
  savingsVsMarket,
} from "./outcomes";

const plan = (total: number, feasible = true) => ({
  total,
  feasible,
  allocations: [
    {
      supplier_id: "s1",
      bid_id: "b1",
      lines: [
        { sku_spec: "romaine", quantity: 2, unit_price: 40 },
        { sku_spec: "onion", quantity: 1, unit_price: 30 },
      ],
    },
  ],
});

describe("outcomes", () => {
  it("savings vs cheapest per line is the difference of totals, with the method stated", () => {
    const o = savingsVsCheapestPerLine(plan(110), plan(125, false), "simulated");
    expect(o.value).toBe(15);
    expect(o.source).toBe("simulated");
    expect(o.how_computed).toContain("$125.00");
    expect(o.how_computed).toContain("minimum");
  });

  it("savings vs market only counts lines that have a market price, and says how many", () => {
    const o = savingsVsMarket(plan(110), { romaine: { unit_price: 45, label: "USDA terminal market, Oct 23" } }, "live");
    expect(o.value).toBe(10);
    expect(o.how_computed).toContain("1 of 2 lines");
    expect(o.how_computed).toContain("USDA terminal market, Oct 23");
    expect(o.source).toBe("live");
  });

  it("savings vs market can be negative and is not clamped", () => {
    expect(savingsVsMarket(plan(110), { onion: { unit_price: 25, label: "x" } }, "mirror").value).toBe(-5);
  });

  it("credits captured sums the value of rejected lines from the order", () => {
    const o = creditsCaptured(
      [
        { result: "rejected", sku_spec: "romaine" },
        { result: "accepted", sku_spec: "onion" },
      ],
      plan(110),
      "simulated",
    );
    expect(o.value).toBe(80);
  });

  it("recalls blocked counts recall rejections", () => {
    expect(recallsBlocked(["recall: openFDA F-1234", "below floor", "recall: openFDA F-9"], "live").value).toBe(2);
  });

  it("hours saved uses the named baseline assumption and says so", () => {
    const o = hoursSaved(6);
    expect(o.value).toBe(Math.round(((BASELINE_ORDERING_MINUTES_PER_WEEK - 6) / 60) * 100) / 100);
    expect(o.how_computed).toContain("assumption");
    expect(o.source).toBe("simulated");
    expect(hoursSaved(10_000).value).toBe(0);
  });

  it("our fee is 15% of verified savings, capped at $299, never negative", () => {
    expect(ourFee(1000).value).toBe(150);
    expect(ourFee(5000).value).toBe(299);
    expect(ourFee(-50).value).toBe(0);
  });
});
