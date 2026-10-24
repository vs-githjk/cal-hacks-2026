import { describe, expect, it } from "vitest";
import { priceLossReports } from "./loss-report";
import type { Ranked } from "./scoring";
import type { Bid } from "./types";

const ranked = (seller_id: string, score: number, rank: number, id = `${seller_id}-${rank}`): Ranked => ({
  bid: { id, seller_id, need_id: "need", persona: "seller", lines: [], total_landed_price: score, perks: [], claims: [],
    floor_check_passed: true, mirror_snapshot_id: "", decision_trace: "", expires_at: "", origin: "SIM", source: "private", sealed_at: 0 } as Bid,
  rank, landed: score, score, verified: 0, picked: [], complete: true, missing: [],
});

describe("priceLossReports", () => {
  it("bands strict positive score gaps and emits one report per losing seller", () => {
    const final = [ranked("winner", 100, 1), ranked("winner", 130, 2), ranked("s5", 105, 3), ranked("s10", 110, 4), ranked("s20", 120, 5), ranked("s21", 121, 6), ranked("s5", 130, 7)];
    const evidence = new Map(final.map((x) => [x.bid.id, { origin: "SIM", pickedListingUrls: ["https://shop.example/item?q=x#offer"] }]));
    expect(priceLossReports("round/1", final, evidence).map(({ sellerId, gapBand }) => [sellerId, gapBand])).toEqual([
      ["s5", "within5"], ["s10", "within10"], ["s20", "within20"], ["s21", "over20"],
    ]);
    expect(priceLossReports("round/1", final, evidence)[0]).toMatchObject({
      id: "loss:round%2F1:s5", sourceUrl: "https://shop.example/item?q=x#offer", reason: "price", won: false,
    });
    expect(JSON.stringify(priceLossReports("round/1", final, evidence))).not.toMatch(/100|105|110|120|121/);
  });

  it("skips nonfinite or nonpositive winners, incomplete bids, nonlosers, and unsafe evidence", () => {
    expect(priceLossReports("r", [ranked("w", Infinity, 1), ranked("l", 120, 2)], new Map())).toEqual([]);
    const rows = [ranked("w", 100, 1), ranked("equal", 100, 2), { ...ranked("partial", 120, 3), complete: false }, ranked("unsafe", 120, 4)];
    const evidence = new Map([["unsafe-4", { origin: "SIM", pickedListingUrls: ["https://user:pass@shop.example/a\n"] }]]);
    expect(priceLossReports("r", rows, evidence)).toEqual([]);
  });

  it("skips unsupported canonical origins instead of coercing them to SIM", () => {
    const rows = [ranked("w", 100, 1), ranked("l", 105, 2)];
    const evidence = new Map([["l-2", { origin: "UNKNOWN", pickedListingUrls: ["https://shop.example/l"] }]]);
    expect(priceLossReports("r", rows, evidence)).toEqual([]);
  });

  it("falls back to legacy listing URLs only when provenance has no listing URL", () => {
    const final = [ranked("w", 100, 1), ranked("legacy", 105, 2), ranked("bad", 110, 3)];
    const evidence = new Map([
      ["legacy-2", { origin: "SIM", pickedListingUrls: ["https://shop.example/legacy"] }],
      ["bad-3", { origin: "SIM", pickedListingUrls: ["javascript:alert(1)"] }],
    ]);
    expect(priceLossReports("r", final, evidence).map((x) => [x.sellerId, x.sourceUrl])).toEqual([["legacy", "https://shop.example/legacy"]]);
  });
});
