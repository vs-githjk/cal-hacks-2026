import { describe, expect, it } from "vitest";
import { checkLineSpec, rankBids } from "./scoring";
import type { Bid, SpecCard } from "./types";

const card = (sku: string, subs: string[] = []): SpecCard => ({
  id: `spec-${sku}`,
  sku_spec: sku,
  item_name: sku,
  grade: "U.S. No. 1",
  pack_size: "50 lb",
  case_count: 1,
  unit: "sack",
  allowed_substitutes: subs,
  photo_checks: [],
  source: "simulated",
});
const cards = new Map([["onion-50lb", card("onion-50lb", ["onion-50lb-alt"])]]);

let seq = 0;
const mk = (supplier: string, price: number, extra: Partial<Bid> = {}): Bid => ({
  id: `b${++seq}`,
  need_id: "n1",
  supplier_id: supplier,
  persona: supplier,
  lines: [{ sku_spec: "onion-50lb", unit_price: price, quantity: 2 }],
  total_landed_price: price * 2,
  perks: [],
  claims: [],
  floor_check_passed: true,
  mirror_snapshot_id: "",
  decision_trace: "",
  expires_at: "",
  source: "simulated",
  sealed_at: seq,
  ...extra,
});

describe("checkLineSpec", () => {
  it("accepts the exact spec and listed substitutes", () => {
    expect(checkLineSpec({ sku_spec: "onion-50lb", unit_price: 1, quantity: 1 }, cards).ok).toBe(true);
    expect(checkLineSpec({ sku_spec: "onion-50lb", offered_spec: "onion-50lb-alt", unit_price: 1, quantity: 1 }, cards).ok).toBe(true);
  });
  it("rejects an offered spec that is not the spec or a listed substitute", () => {
    const r = checkLineSpec({ sku_spec: "onion-50lb", offered_spec: "onion-40lb", unit_price: 1, quantity: 1 }, cards);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reasons[0]).toContain("onion-40lb");
  });
  it("rejects a line for an item with no spec card", () => {
    expect(checkLineSpec({ sku_spec: "mystery", unit_price: 1, quantity: 1 }, cards).ok).toBe(false);
  });
});

describe("rankBids", () => {
  it("ranks by landed price minus perks value, lowest first", () => {
    const a = mk("s1", 30);
    const b = mk("s2", 25);
    const c = mk("s3", 28, { perks: ["free_delivery"] });
    const r = rankBids([a, b, c], { specCards: cards, perksValue: (bid) => (bid.perks.length ? 10 : 0) });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([c.id, b.id, a.id]);
    expect(r.ranked[0]!.rank).toBe(1);
  });

  it("disqualifies a bid with any wrong-spec line and keeps the reason", () => {
    const bad = mk("s1", 10, { lines: [{ sku_spec: "onion-50lb", offered_spec: "onion-40lb", unit_price: 10, quantity: 2 }] });
    const good = mk("s2", 30);
    const r = rankBids([bad, good], { specCards: cards });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([good.id]);
    expect(r.disqualified[0]!.bid.id).toBe(bad.id);
    expect(r.disqualified[0]!.reasons.join(" ")).toContain("onion-40lb");
  });

  it("applies extra rejections (floor, recall, failed claim) from other checks", () => {
    const a = mk("s1", 10);
    const b = mk("s2", 20);
    const r = rankBids([a, b], { specCards: cards, rejections: new Map([[a.id, ["recall: matches openFDA record"]]]) });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([b.id]);
    expect(r.disqualified[0]!.reasons).toEqual(["recall: matches openFDA record"]);
  });

  it("breaks ties by more verified claims, then earlier sealed time", () => {
    const early = mk("s1", 20);
    const late = mk("s2", 20);
    const verified = mk("s3", 20);
    const r = rankBids([late, early, verified], {
      specCards: cards,
      verifiedClaims: (bid) => (bid.id === verified.id ? 2 : 0),
    });
    expect(r.ranked.map((x) => x.bid.id)).toEqual([verified.id, early.id, late.id]);
  });

  it("computes landed price from the lines, not the supplier's stated total", () => {
    const liar = mk("s1", 30, { total_landed_price: 1 });
    const honest = mk("s2", 25);
    const r = rankBids([liar, honest], { specCards: cards });
    expect(r.ranked[0]!.bid.id).toBe(honest.id);
    expect(r.ranked[1]!.landed).toBe(60);
  });
});
