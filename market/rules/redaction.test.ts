import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { sellerView } from "./redaction";

const needArb = fc.record({
  id: fc.string(),
  buyer_id: fc.string(),
  items: fc.array(
    fc.record({
      sku_spec: fc.string(),
      condition: fc.constantFrom("new", "open-box", "refurbished", "used"),
      variant: fc.string(),
      quantity: fc.double({ noNaN: true }),
      unit: fc.string(),
    }),
  ),
  delivery_window: fc.string(),
  spend_limit: fc.double({ min: 1, max: 1e7, noNaN: true }),
  consent: fc.boolean(),
  auction_window_s: fc.integer(),
  origin: fc.constantFrom("LIVE", "SIM"),
  usage_history: fc.array(fc.double({ noNaN: true })),
  other_bids: fc.array(fc.string()),
});

describe("redaction", () => {
  it("keeps items, specs, delivery window and deadline", () => {
    const v = sellerView(
      {
        id: "n1",
        buyer_id: "r1",
        items: [{ sku_spec: "a", condition: "new", variant: "retail", quantity: 2, unit: "case" }],
        delivery_window: "Tue AM",
        spend_limit: 900,
        consent: true,
        auction_window_s: 15,
        origin: "SIM",
      },
      "2026-10-24T10:00:00Z",
    );
    expect(v).toEqual({
      need_id: "n1",
      items: [{ sku_spec: "a", condition: "new", variant: "retail", quantity: 2, unit: "case" }],
      delivery_window: "Tue AM",
      deadline: "2026-10-24T10:00:00Z",
    });
  });

  it("property: no seller view ever contains spend_limit, usage history, buyer or other bids", () => {
    fc.assert(
      fc.property(needArb, (need) => {
        const v = sellerView(need, "t");
        const text = JSON.stringify(v);
        return (
          !("spend_limit" in v) &&
          !text.includes("spend_limit") &&
          !text.includes("usage_history") &&
          !text.includes("other_bids") &&
          !text.includes("buyer_id") &&
          !text.includes("consent") &&
          v.items.every((i) => Object.keys(i).sort().join() === "condition,quantity,sku_spec,unit,variant")
        );
      }),
    );
  });
});
