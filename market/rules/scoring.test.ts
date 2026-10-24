import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { checkLineSpec, rankBids } from "./scoring";
import type { Bid, NeedItem } from "./types";
import { MARKET_CONFIG } from "../config";

// SIM fixture: one GPU with three SKUs.
const GPU = "gpu-rtx5070ti-retail";
const GPU_OEM = "gpu-rtx5070ti-oem";
const need: NeedItem = { sku_spec: GPU, condition: "new", variant: "retail", quantity: 1, unit: "each" };
const items = new Map([[GPU, need]]);

let seq = 0;
const mk = (seller: string, price: number, extra: Partial<Bid> = {}): Bid => ({
  id: `b${++seq}`,
  need_id: "n1",
  seller_id: seller,
  persona: seller,
  lines: [{ sku_spec: GPU, unit_price: price, quantity: 1 }],
  total_landed_price: price,
  perks: [],
  claims: [],
  floor_check_passed: true,
  mirror_snapshot_id: "",
  decision_trace: "",
  expires_at: "",
  origin: "SIM",
  source: "sim:fixture",
  sealed_at: seq,
  ...extra,
});

describe("checkLineSpec", () => {
  it("accepts the exact SKU and condition", () => {
    expect(checkLineSpec({ sku_spec: GPU, unit_price: 1, quantity: 1 }, items).ok).toBe(true);
    expect(checkLineSpec({ sku_spec: GPU, offered_condition: "new", unit_price: 1, quantity: 1 }, items).ok).toBe(true);
  });
  it("rejects a different condition and names both", () => {
    const r = checkLineSpec({ sku_spec: GPU, offered_condition: "open-box", unit_price: 1, quantity: 1 }, items);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reasons[0]).toMatch(/open-box.*new/);
  });
  it("rejects a different variant (OEM for retail)", () => {
    const r = checkLineSpec({ sku_spec: GPU, offered_spec: GPU_OEM, unit_price: 1, quantity: 1 }, items);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reasons[0]).toContain(GPU_OEM);
  });
  it("rejects a quantity of 0, -1, NaN, Infinity or one that differs from the goal line", () => {
    for (const q of [0, -1, NaN, Infinity, 2]) {
      const r = checkLineSpec({ sku_spec: GPU, unit_price: 1, quantity: q }, items);
      expect(r.ok, String(q)).toBe(false);
      if (!r.ok) expect(r.reasons.join(" ")).toMatch(/quantity/);
    }
  });
  it("rejects a line the goal did not ask for", () => {
    expect(checkLineSpec({ sku_spec: "cpu-x", unit_price: 1, quantity: 1 }, items).ok).toBe(false);
  });
});

describe("rankBids", () => {
  it("ranks by landed price minus perks value, lowest first", () => {
    const a = mk("seller-a", 780);
    const b = mk("seller-b", 760);
    const c = mk("seller-c", 770, { perks: ["free_shipping"] });
    const r = rankBids([a, b, c], { needItems: items, perksValue: (bid) => (bid.perks.length ? 15 : 0) });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([c.id, b.id, a.id]);
    expect(r.ranked[0]!.rank).toBe(1);
  });

  it("disqualifies the cheapest bid when it is open-box against a new goal", () => {
    const trap = mk("seller-b", 699, { lines: [{ sku_spec: GPU, offered_condition: "open-box", unit_price: 699, quantity: 1 }] });
    const good = mk("seller-a", 780);
    const r = rankBids([trap, good], { needItems: items });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([good.id]);
    expect(r.disqualified[0]!.bid.id).toBe(trap.id);
  });

  it("a zero or negative quantity bid cannot rank first; a valid bid still ranks", () => {
    const zero = mk("seller-b", 700, { lines: [{ sku_spec: GPU, unit_price: 700, quantity: 0 }] });
    const neg = mk("seller-c", 700, { lines: [{ sku_spec: GPU, unit_price: 700, quantity: -1 }] });
    const good = mk("seller-a", 780);
    const r = rankBids([zero, neg, good], { needItems: items });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([good.id]);
    expect(r.disqualified.map((d) => d.bid.id).sort()).toEqual([zero.id, neg.id].sort());
  });

  it("applies rejections from other checks (floor, CPSC recall, claim check, Shield)", () => {
    const a = mk("seller-a", 700);
    const b = mk("seller-b", 720);
    const r = rankBids([a, b], { needItems: items, rejections: new Map([[a.id, ["recall: CPSC 26-001"]]]) });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([b.id]);
    expect(r.disqualified[0]!.reasons).toEqual(["recall: CPSC 26-001"]);
  });

  it("breaks ties by more verified claims, then earlier sealed time", () => {
    const early = mk("seller-a", 750);
    const late = mk("seller-b", 750);
    const verified = mk("seller-c", 750);
    const r = rankBids([late, early, verified], { needItems: items, verifiedClaims: (bid) => (bid.id === verified.id ? 2 : 0) });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([verified.id, early.id, late.id]);
  });

  it("computes landed price from the lines, not the seller's stated total", () => {
    const claimsLow = mk("seller-a", 780, { total_landed_price: 1 });
    const honest = mk("seller-b", 760);
    const r = rankBids([claimsLow, honest], { needItems: items });
    expect(r.ranked[0]!.bid.id).toBe(honest.id);
    expect(r.ranked[1]!.landed).toBe(780);
  });

  // Invariant 8: the fee is flat and never feeds ranking.
  it("INVARIANT fee-never-ranks: changing the fee changes no ranking", () => {
    fc.assert(
      fc.property(
        fc.array(fc.integer({ min: 100, max: 2000 }), { minLength: 1, maxLength: 8 }),
        fc.record({ rate: fc.double({ min: 0, max: 0.5, noNaN: true }), min: fc.integer({ min: 0, max: 50 }), cap: fc.integer({ min: 0, max: 500 }) }),
        (prices, fee) => {
          const bids = prices.map((p, i) => mk(`seller-${i}`, p));
          const base = rankBids(bids, { needItems: items, config: MARKET_CONFIG });
          const changed = rankBids(bids, {
            needItems: items,
            config: { ...MARKET_CONFIG, seller_fee: { ...MARKET_CONFIG.seller_fee, rate: fee.rate, min: fee.min, cap_per_item: fee.cap } },
          });
          return JSON.stringify(base) === JSON.stringify(changed);
        },
      ),
    );
  });
});
