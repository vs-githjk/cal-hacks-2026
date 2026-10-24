// web/src/lib/arenaFixture.ts
// SIM sample rounds for the 3D arena, in the exact shapes the market writes (round, seller_needs, round_result, floor_event),
// so the scene projects them the same way it projects live rows. Every origin is SIM; nothing here is a real seller's price.
// Sellers and names come from market/spacetimedb/src/demo.ts. Reasons follow close_round: "below this seller floor",
// "Bazaar Shield <result>: <rule ids>", "Advocate veto (<rule>: <detail>) [source: <url>]".
import type { ArenaRows, EventRow, NeedRow, ResultRow, RoundRow } from "./arenaScene.ts";

const OPENED_MS = Date.UTC(2026, 9, 24, 17, 0, 0);
const WINDOW_S = 90;
const ts = (ms: number) => ({ microsSinceUnixEpoch: BigInt(ms) * BigInt(1000) });

interface SellerSpec {
  sellerId: string;
  name: string;
  rank: number; // 0 when the referee did not rank it
  landed: number;
  unitPrice: number;
  offeredSpec: string;
  condition: string;
  reasons?: string[];
  source?: string;
  belowFloor?: boolean; // the market logs bid_rejected, not bid_sealed, and writes no checks
  shield?: "allow" | "block";
  advocate?: string; // the advocate_card label: "Advocate: buy", "Advocate: caution" or "Advocate veto (<rule>)"
}

/** One closed round: opened, a bid event per seller, the checks, then the close events, with ids and times in the order the market writes them. */
function closedRound(roundId: string, needId: string, skuSpec: string, sellers: SellerSpec[]): ArenaRows {
  const bidId = (s: SellerSpec) => `bid-${roundId}-${s.sellerId}`;
  const rounds: RoundRow[] = [{
    id: roundId, needId, openedAt: ts(OPENED_MS), deadline: ts(OPENED_MS + WINDOW_S * 1000), state: "closed", sealedCount: sellers.length,
    closedAt: ts(OPENED_MS + WINDOW_S * 1000), origin: "SIM",
  }];
  const results: ResultRow[] = sellers.map((s, i): ResultRow => ({
    id: BigInt(i + 1), roundId, bidId: bidId(s), sellerId: s.sellerId, persona: s.name, rank: s.rank, landed: s.landed, reasons: s.reasons ?? [],
    lines: [{ skuSpec, offeredSpec: s.offeredSpec, offeredCondition: s.condition, unitPrice: s.unitPrice, quantity: 1 }],
    origin: "SIM", source: s.source ?? "",
  }));

  const events: EventRow[] = [];
  const push = (kind: string, refTable: string, refId: string, sellerId: string, label: string, atS: number) =>
    events.push({ id: BigInt(events.length + 1), kind, refTable, refId, sellerId, label, origin: "SIM", at: ts(OPENED_MS + Math.round(atS * 1000)) });
  push("round_opened", "round", roundId, "", `Sealed round open for ${WINDOW_S} s`, 0);
  sellers.forEach((s, i) => {
    const at = 10 + i * 12;
    if (s.belowFloor) return push("bid_rejected", "bid", bidId(s), s.sellerId, "Bid rejected: below this seller floor", at);
    push("bid_sealed", "bid", bidId(s), s.sellerId, "A sealed bid arrived", at);
    if (s.shield) push("verdict", "bid_check", bidId(s), "", `Bazaar Shield: ${s.shield}`, at + 2);
    if (s.advocate) push("advocate_card", "bid_check", bidId(s), "", s.advocate, at + 4);
  });
  const winner = sellers.find((s) => s.rank === 1);
  if (winner) push("stock_held", "stock_hold", bidId(winner), winner.sellerId, "A unit is held for the round winner during the approval call", WINDOW_S);
  const ranked = sellers.filter((s) => s.rank > 0).length;
  push("auction_closed", "round", roundId, winner?.sellerId ?? "", winner ? `Round closed: ${ranked} ranked, ${sellers.length - ranked} out` : "Round closed: no eligible bid", WINDOW_S);
  return { rounds, needs: [], results, events };
}

const GPU = "rtx 5070 ti";
const GPU_VETO = "Advocate veto (fit.gpu_length: The card is 336 mm; your case allows 305 mm) [source: https://bargainbin.example.test/rtx-5070-ti-specs]";

const gpu = closedRound("round-sample-gpu", "need-sample-gpu", GPU, [
  { sellerId: "fair-price-pc", name: "Fair Price PC (SIM)", rank: 1, landed: 1299.99, unitPrice: 1279.99, offeredSpec: "asus prime rtx 5070 ti oc", condition: "new", shield: "allow", advocate: "Advocate: buy" },
  { sellerId: "gadget-grove", name: "Gadget Grove (Vedant)", rank: 2, landed: 1247.02, unitPrice: 1229.02, offeredSpec: "rtx 5070 ti", condition: "open-box", shield: "allow", advocate: "Advocate: caution" },
  {
    sellerId: "bargain-bin", name: "Bargain Bin Hardware (SIM)", rank: 0, landed: 1199, unitPrice: 1179, offeredSpec: "rtx 5070 ti", condition: "new",
    reasons: [GPU_VETO], source: "https://bargainbin.example.test/rtx-5070-ti", shield: "allow", advocate: "Advocate veto (fit.gpu_length)",
  },
  {
    sellerId: "renew-refurb", name: "ReNew Refurb (SIM)", rank: 0, landed: 1150, unitPrice: 1130, offeredSpec: "rtx 5070 ti", condition: "open-box",
    reasons: ["Bazaar Shield block: shield.override.instruction, shield.payee.swap"], shield: "block",
  },
  { sellerId: "lowball", name: "Lowball Direct (SIM)", rank: 0, landed: 1090, unitPrice: 1075, offeredSpec: "rtx 5070 ti", condition: "new", reasons: ["below this seller floor"], belowFloor: true },
]);

/** The same request while the sealed window is still running: three sealed bids, no prices, no results. */
const gpuOpen: ArenaRows = (() => {
  const roundId = "round-sample-gpu-open";
  const openedAt = ts(OPENED_MS);
  const need: NeedRow = { roundId, skuSpec: GPU, condition: "new", quantity: 1, unit: "each" };
  const bids = ["fair-price-pc", "gadget-grove", "bargain-bin"];
  const events: EventRow[] = [
    { id: 1n, kind: "round_opened", refTable: "round", refId: roundId, sellerId: "", label: `Sealed round open for ${WINDOW_S} s`, origin: "SIM", at: openedAt },
    ...bids.map((sellerId, i): EventRow => ({
      id: BigInt(i + 2), kind: "bid_sealed", refTable: "bid", refId: `bid-${roundId}-${sellerId}`, sellerId, label: "A sealed bid arrived", origin: "SIM", at: ts(OPENED_MS + (10 + i * 12) * 1000),
    })),
  ];
  return {
    rounds: [{ id: roundId, needId: "need-sample-gpu-open", openedAt, deadline: ts(OPENED_MS + WINDOW_S * 1000), state: "open", sealedCount: bids.length, origin: "SIM" }],
    needs: [need],
    results: [],
    events,
  };
})();

const ssd = closedRound("round-sample-ssd", "need-sample-ssd", "nvme-ssd-2tb", [
  { sellerId: "seller-a", name: "Seller A", rank: 1, landed: 119.99, unitPrice: 109.99, offeredSpec: "nvme ssd 2tb", condition: "new", shield: "allow", advocate: "Advocate: buy" },
  { sellerId: "seller-b", name: "Seller B", rank: 2, landed: 124.5, unitPrice: 114.5, offeredSpec: "nvme ssd 2tb", condition: "new", shield: "allow", advocate: "Advocate: buy" },
  { sellerId: "seller-c", name: "Seller C", rank: 3, landed: 131, unitPrice: 121, offeredSpec: "nvme ssd 2tb", condition: "new", shield: "allow", advocate: "Advocate: caution" },
]);

/** Labelled SIM rounds for /floor when the market has none (or for a recorded replay): the scene projects them like live rows. */
export const SAMPLES: Record<"gpu" | "gpu-open" | "ssd", ArenaRows> = { gpu, "gpu-open": gpuOpen, ssd };
