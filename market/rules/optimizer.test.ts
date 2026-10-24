import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { offersFromBids, planOrder, type Offer, type PlanInput } from "./optimizer";
import type { SupplierTerms } from "./types";

const terms = (supplier_id: string, min: number, fee = 0, free_over = 0): SupplierTerms => ({
  supplier_id,
  min_order_value: min,
  delivery_fee: fee,
  free_delivery_over: free_over,
  cutoff_time: "16:00",
  delivery_days: ["Tue"],
  source: "simulated",
});
const offer = (supplier_id: string, sku_spec: string, unit_price: number, quantity = 1): Offer => ({
  supplier_id,
  bid_id: `bid-${supplier_id}`,
  sku_spec,
  unit_price,
  quantity,
});
const need = (skus: string[]) => ({
  id: "n1",
  items: skus.map((s) => ({ sku_spec: s, grade: "", pack_size: "", quantity: 1, unit: "case" })),
});

describe("planOrder", () => {
  // Sysco is cheapest on chicken and cream but only reaches $120, under its $150 minimum.
  // Valley is cheapest on onions. Moving onions to Sysco costs $2 more but clears the minimum.
  const input: PlanInput = {
    need: need(["chicken", "cream", "onion", "romaine"]),
    offers: [
      offer("sysco", "chicken", 80),
      offer("sysco", "cream", 40),
      offer("sysco", "onion", 32),
      offer("valley", "chicken", 95),
      offer("valley", "cream", 50),
      offer("valley", "onion", 30),
      offer("valley", "romaine", 45),
    ],
    terms: [terms("sysco", 150), terms("valley", 40, 12.4, 200)],
    names: { suppliers: { sysco: "Sysco", valley: "Valley Produce" }, items: { onion: "onions" } },
  };

  it("cheapest per line ignores minimums and reports the plan as infeasible", () => {
    const p = planOrder(input, "cheapest_per_line");
    expect(p.feasible).toBe(false);
    expect(p.subtotal).toBe(195);
    expect(p.fees).toBe(12.4);
    expect(p.explanation.join(" ")).toContain("$150.00 minimum");
  });

  it("optimizer moves a line so every minimum is met", () => {
    const p = planOrder(input, "optimizer");
    expect(p.feasible).toBe(true);
    const sysco = p.allocations.find((a) => a.supplier_id === "sysco")!;
    expect(sysco.lines.map((l) => l.sku_spec).sort()).toEqual(["chicken", "cream", "onion"]);
    expect(p.total).toBe(197 + 12.4);
    expect(p.explanation.join(" ")).toContain("Moved onions from Valley Produce to Sysco");
  });

  it("consolidates to one supplier when a delivery fee outweighs the price gap", () => {
    const p = planOrder(
      {
        need: need(["a", "b"]),
        offers: [offer("x", "a", 10), offer("x", "b", 12), offer("y", "b", 10)],
        terms: [terms("x", 0), terms("y", 0, 15, 100)],
      },
      "optimizer",
    );
    expect(p.allocations.map((a) => a.supplier_id)).toEqual(["x"]);
    expect(p.total).toBe(22);
  });

  it("lists lines nobody bid on as uncovered", () => {
    const p = planOrder({ need: need(["a", "z"]), offers: [offer("x", "a", 10)], terms: [] }, "optimizer");
    expect(p.uncovered).toEqual(["z"]);
    expect(p.explanation.join(" ")).toContain("No eligible bid");
  });

  it("offersFromBids keeps the cheapest eligible line per supplier and drops short quantities", () => {
    const offers = offersFromBids(
      [
        { id: "b1", supplier_id: "x", lines: [{ sku_spec: "a", unit_price: 10, quantity: 2 }] },
        { id: "b2", supplier_id: "x", lines: [{ sku_spec: "a", unit_price: 9, quantity: 2 }] },
        { id: "b3", supplier_id: "y", lines: [{ sku_spec: "a", unit_price: 5, quantity: 1 }] },
        { id: "b4", supplier_id: "z", lines: [{ sku_spec: "a", unit_price: 1, quantity: 2 }] },
      ],
      { id: "n", items: [{ sku_spec: "a", grade: "", pack_size: "", quantity: 2, unit: "" }] },
      (bidId) => bidId !== "b4",
    );
    expect(offers).toEqual([{ supplier_id: "x", bid_id: "b2", sku_spec: "a", unit_price: 9, quantity: 2 }]);
  });
});

const instance = fc
  .record({
    nSup: fc.integer({ min: 1, max: 5 }),
    nLines: fc.integer({ min: 1, max: 8 }),
    seed: fc.array(fc.tuple(fc.boolean(), fc.integer({ min: 1, max: 200 })), { minLength: 40, maxLength: 40 }),
    mins: fc.array(fc.integer({ min: 0, max: 300 }), { minLength: 5, maxLength: 5 }),
    fees: fc.array(fc.integer({ min: 0, max: 30 }), { minLength: 5, maxLength: 5 }),
    freeOver: fc.array(fc.integer({ min: 0, max: 500 }), { minLength: 5, maxLength: 5 }),
  })
  .map(({ nSup, nLines, seed, mins, fees, freeOver }): PlanInput => {
    const sups = Array.from({ length: nSup }, (_, i) => `s${i}`);
    const skus = Array.from({ length: nLines }, (_, i) => `k${i}`);
    const offers: Offer[] = [];
    sups.forEach((s, i) =>
      skus.forEach((k, j) => {
        const [has, price] = seed[(i * 8 + j) % 40]!;
        if (has) offers.push(offer(s, k, price));
      }),
    );
    return { need: need(skus), offers, terms: sups.map((s, i) => terms(s, mins[i]!, fees[i]!, freeOver[i]!)) };
  });

describe("planOrder properties", () => {
  it("optimizer total is never above a feasible cheapest-per-line total", () => {
    fc.assert(
      fc.property(instance, (inp) => {
        const naive = planOrder(inp, "cheapest_per_line");
        const opt = planOrder(inp, "optimizer");
        return !naive.feasible || opt.total <= naive.total + 1e-9;
      }),
      { numRuns: 300 },
    );
  });

  it("every allocation of a feasible plan meets its supplier minimum", () => {
    fc.assert(
      fc.property(instance, (inp) => {
        const p = planOrder(inp, "optimizer");
        if (!p.feasible) return true;
        return p.allocations.every((a) => {
          const min = inp.terms.find((t) => t.supplier_id === a.supplier_id)?.min_order_value ?? 0;
          return a.lines.reduce((s, l) => s + l.unit_price * l.quantity, 0) >= min - 1e-9;
        });
      }),
      { numRuns: 300 },
    );
  });

  it("every coverable line is allocated exactly once, in both modes", () => {
    fc.assert(
      fc.property(instance, fc.constantFrom("optimizer", "cheapest_per_line" as const), (inp, mode) => {
        const p = planOrder(inp, mode);
        const coverable = new Set(inp.offers.map((o) => o.sku_spec));
        const allocated = p.allocations.flatMap((a) => a.lines.map((l) => l.sku_spec));
        return (
          allocated.length === coverable.size &&
          new Set(allocated).size === allocated.length &&
          allocated.every((s) => coverable.has(s)) &&
          p.uncovered.every((s) => !coverable.has(s))
        );
      }),
      { numRuns: 300 },
    );
  });

  it("same input gives the same output, whatever the offer order", () => {
    fc.assert(
      fc.property(instance, (inp) => {
        const a = planOrder(inp, "optimizer");
        const b = planOrder(inp, "optimizer");
        const c = planOrder({ ...inp, offers: [...inp.offers].reverse() }, "optimizer");
        return JSON.stringify(a) === JSON.stringify(b) && JSON.stringify(a) === JSON.stringify(c);
      }),
      { numRuns: 200 },
    );
  });
});
