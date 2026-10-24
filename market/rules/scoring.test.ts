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
  it("rejects qty_available of 0, -1, NaN or Infinity; more stock than the need is fine", () => {
    for (const q of [0, -1, NaN, Infinity]) {
      const r = checkLineSpec({ sku_spec: GPU, unit_price: 1, quantity: q }, items);
      expect(r.ok, String(q)).toBe(false);
      if (!r.ok) expect(r.reasons.join(" ")).toMatch(/qty_available/);
    }
    expect(checkLineSpec({ sku_spec: GPU, unit_price: 1, quantity: 2 }, items).ok).toBe(true);
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

  it("counts flat shipping once on the selected alternative and in the cap and score", () => {
    const needQty: NeedItem = { ...need, quantity: 2, allowed_conditions: ["new", "open-box"] };
    const needItems = new Map([[GPU, needQty]]);
    const bid = mk("seller-a", 1, { lines: [
      { sku_spec: GPU, offered_condition: "new", unit_price: 100, quantity: 2, shipping: 5 },
      { sku_spec: GPU, offered_condition: "open-box", unit_price: 95, quantity: 2, shipping: 20 },
    ] });
    const ranked = rankBids([bid], { needItems, spendLimit: 205 });
    expect(ranked.ranked[0]!.picked).toEqual([0]);
    expect(ranked.ranked[0]!.landed).toBe(205);
    expect(rankBids([bid], { needItems, spendLimit: 204 }).ranked).toHaveLength(0);
  });

  it("disqualifies a bid that omits any requested SKU", () => {
    const psu = "psu-850w-gold";
    const needWithPsu = new Map([...items, [psu, { sku_spec: psu, condition: "new", variant: "retail", quantity: 1, unit: "each" } as NeedItem]]);
    const gpuOnly = mk("seller-a", 780);
    const complete = mk("seller-b", 900, { lines: [
      { sku_spec: GPU, unit_price: 780, quantity: 1 },
      { sku_spec: psu, unit_price: 120, quantity: 1 },
    ] });
    const r = rankBids([gpuOnly, complete], { needItems: needWithPsu });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([complete.id]);
    expect(r.disqualified.find((x) => x.bid.id === gpuOnly.id)?.reasons.join(" ")).toMatch(/psu-850w-gold.*does not cover/);
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

// ---- Seller model (LOCKED Fri 22:36): condition lines are ALTERNATIVES per SKU, allowed_conditions, the cap ----
const openOk: NeedItem = { ...need, allowed_conditions: ["new", "open-box"] };
const itemsOk = new Map([[GPU, openOk]]);
const ln = (price: number, cond?: "new" | "open-box" | "refurbished") => ({
  sku_spec: GPU, unit_price: price, quantity: 1, ...(cond ? { offered_condition: cond } : {}),
});

describe("allowed_conditions", () => {
  it("checkLineSpec accepts an open-box line when the need allows new or open-box", () => {
    expect(checkLineSpec(ln(1, "open-box"), itemsOk).ok).toBe(true);
    expect(checkLineSpec(ln(1, "new"), itemsOk).ok).toBe(true);
  });
  it("still rejects a condition outside the allowed set and names the allowed ones", () => {
    const r = checkLineSpec(ln(1, "refurbished"), itemsOk);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reasons[0]).toMatch(/refurbished.*new or open-box/);
  });
  it("an empty or missing allowed_conditions means only the need's own condition", () => {
    expect(checkLineSpec(ln(1, "open-box"), new Map([[GPU, { ...need, allowed_conditions: [] }]])).ok).toBe(false);
    expect(checkLineSpec(ln(1, "open-box"), items).ok).toBe(false);
  });
  it("rankBids ranks an open-box bid when it is allowed", () => {
    const eb = mk("ebay", 1239, { lines: [ln(1239, "open-box")] });
    const r = rankBids([eb], { needItems: itemsOk });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([eb.id]);
  });
});

describe("a bid's lines for one SKU are alternatives", () => {
  it("picks the cheapest allowed line and never sums them", () => {
    const gg = mk("gadget", 0, { lines: [ln(320, "new"), ln(300, "open-box")] });
    const r = rankBids([gg], { needItems: itemsOk });
    expect(r.ranked[0]!.landed).toBe(300);
    expect(r.ranked[0]!.picked).toEqual([1]);
  });
  it("two new lines [300, 320] rank at 300, not 620", () => {
    const gg = mk("gadget", 0, { lines: [ln(300), ln(320)] });
    expect(rankBids([gg], { needItems: items }).ranked[0]!.landed).toBe(300);
  });
  it("skips a cheaper line whose condition is not allowed and picks the cheapest allowed one", () => {
    const gg = mk("gadget", 0, { lines: [ln(200, "refurbished"), ln(320, "new"), ln(300, "open-box")] });
    const r = rankBids([gg], { needItems: itemsOk });
    expect(r.ranked[0]!.landed).toBe(300);
    expect(r.ranked[0]!.picked).toEqual([2]);
  });
  it("is out only when no line is allowed, with the reasons of the cheapest line", () => {
    const gg = mk("gadget", 0, { lines: [ln(250, "refurbished"), ln(260, "refurbished")] });
    const r = rankBids([gg], { needItems: itemsOk });
    expect(r.ranked).toEqual([]);
    expect(r.disqualified[0]!.reasons[0]).toMatch(/refurbished/);
    expect(r.disqualified[0]!.landed).toBe(250);
  });
  it("ranks the bid on the picked line against other bids", () => {
    const gg = mk("gadget", 0, { lines: [ln(900, "new"), ln(700, "open-box")] });
    const other = mk("other", 750);
    const r = rankBids([other, gg], { needItems: itemsOk });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([gg.id, other.id]);
  });
});

describe("spend limit", () => {
  it("drops a bid over the cap with the reason over_cap, and never states the cap", () => {
    const over = mk("ebay", 1489);
    const under = mk("best", 1249);
    const r = rankBids([over, under], { needItems: items, spendLimit: 1300 });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([under.id]);
    expect(r.disqualified[0]!.bid.id).toBe(over.id);
    expect(r.disqualified[0]!.reasons[0]).toMatch(/^over_cap/);
    expect(r.disqualified[0]!.reasons.join(" ")).not.toContain("1300");
    expect(r.disqualified[0]!.landed).toBe(1489);
  });
  it("a bid exactly at the cap stays in; no spendLimit means no cap", () => {
    expect(rankBids([mk("a", 1300)], { needItems: items, spendLimit: 1300 }).ranked).toHaveLength(1);
    expect(rankBids([mk("a", 99999)], { needItems: items }).ranked).toHaveLength(1);
  });
  it("judges the cap on the picked line: an over-cap alternative does not sink the bid", () => {
    const gg = mk("gadget", 0, { lines: [ln(1315, "new"), ln(1247, "open-box")] });
    expect(rankBids([gg], { needItems: itemsOk, spendLimit: 1300 }).ranked[0]!.landed).toBe(1247);
  });
});

describe("quality-adjusted price", () => {
  const quality = {
    condition_adj: { new: 0, "open-box": 0.04, refurbished: 0.08, used: 0.15, unknown: 0 },
    no_returns_adj: 0.02,
    min_returns_days: 30,
  };
  it("an open-box line must beat a new line by more than its condition discount, and no returns costs 2 percent", () => {
    const bestBuy = mk("best-buy", 1250); // new, no returns perk: 1275
    const ebay = mk("ebay", 1240, { lines: [ln(1240, "open-box")] }); // open-box, no returns: 1240 * 1.06 = 1314.4
    const fair = mk("fair", 1289, { perks: ["30-day returns"] }); // 1289
    const r = rankBids([ebay, fair, bestBuy], { needItems: itemsOk, quality });
    expect(r.ranked.map((x) => x.bid.seller_id)).toEqual(["best-buy", "fair", "ebay"]);
    expect(r.ranked[0]!.score).toBe(1275);
    expect(r.ranked[2]!.score).toBe(1314.4);
    expect(r.ranked[2]!.landed).toBe(1240); // landed stays the plain price
  });
  it("without quality weights the plain landed price ranks (unchanged behaviour)", () => {
    const ebay = mk("ebay", 1240, { lines: [ln(1240, "open-box")] });
    const bestBuy = mk("best-buy", 1250);
    expect(rankBids([bestBuy, ebay], { needItems: itemsOk }).ranked[0]!.bid.seller_id).toBe("ebay");
  });
});

describe("a line's quantity is stock available (qty_available)", () => {
  const two: NeedItem = { ...need, quantity: 2 };
  const items2 = new Map([[GPU, two]]);
  it("4 in stock for a need of 1 is eligible and costs 1 times the price", () => {
    const r = rankBids([mk("seller-a", 300, { lines: [{ sku_spec: GPU, unit_price: 300, quantity: 4 }] })], { needItems: items });
    expect(r.ranked[0]!.landed).toBe(300);
  });
  it("a line with less stock than the need is not eligible; a line with enough is picked and priced per need quantity", () => {
    const b = mk("seller-a", 0, { lines: [{ sku_spec: GPU, unit_price: 250, quantity: 1 }, { sku_spec: GPU, unit_price: 310, quantity: 4 }] });
    expect(rankBids([b], { needItems: items2 }).ranked[0]!.landed).toBe(620);
  });
  it("when no line has enough stock the bid is out, with a reason naming qty_available", () => {
    const r = rankBids([mk("seller-a", 250, { lines: [{ sku_spec: GPU, unit_price: 250, quantity: 1 }] })], { needItems: items2 });
    expect(r.ranked).toHaveLength(0);
    expect(r.disqualified[0]!.reasons.join(" ")).toMatch(/qty_available 1 is below the 2 needed/);
  });
  it("a line rejected by the floor check (no floor set) is not eligible; the next allowed line is picked", () => {
    const b = mk("seller-a", 0, { lines: [{ sku_spec: GPU, unit_price: 200, quantity: 1 }, { sku_spec: GPU, unit_price: 300, quantity: 1 }] });
    const r = rankBids([b], { needItems: items, lineRejects: new Map([[b.id, [`no floor set for ${GPU} new`, ""]]]) });
    expect(r.ranked[0]!.landed).toBe(300);
    const only = mk("seller-b", 0, { lines: [{ sku_spec: GPU, unit_price: 200, quantity: 1 }] });
    const r2 = rankBids([only], { needItems: items, lineRejects: new Map([[only.id, ["no floor set for x"]]]) });
    expect(r2.disqualified[0]!.reasons.join(" ")).toMatch(/no floor set/);
  });
});
