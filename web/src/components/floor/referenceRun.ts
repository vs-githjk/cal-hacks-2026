// The built-in reference run for /floor when the market has no rows: ONE recorded GPU lot with the four current sellers
// (agents/common.py SELLER_JOBS), winner $1,299.99. The run is a SIM replay, so every bid is labelled SIM except the real store's
// dated listing, which is MIRROR and can never be ordered or paid, so it cannot win. No link, no id, no loopback address.
import type { ArenaRows, EventRow, ResultRow, RoundRow } from "../../lib/arenaScene.ts";

const OPENED_MS = Date.UTC(2026, 9, 24, 17, 0, 0);
const WINDOW_S = 90;
const ts = (ms: number) => ({ microsSinceUnixEpoch: BigInt(ms) * BigInt(1000) });
const ROUND = "reference-run";

interface Spec { id: string; name: string; rank: number; landed: number; unit: number; spec: string; condition: string; origin: "SIM" | "MIRROR"; reasons?: string[] }

const SPECS: Spec[] = [
  { id: "seller_1", name: "Byte Bros Outlet", rank: 1, landed: 1299.99, unit: 1279.99, spec: "asus prime rtx 5070 ti oc", condition: "new", origin: "SIM" },
  { id: "seller_5", name: "ReNew Refurb", rank: 2, landed: 1247.02, unit: 1229.02, spec: "rtx 5070 ti", condition: "open-box", origin: "SIM" },
  {
    id: "seller_3", name: "FlashDeal Frankie", rank: 0, landed: 1199, unit: 1179, spec: "rtx 5070 ti", condition: "new", origin: "SIM",
    reasons: ["Advocate veto (advocate.condition: Listed brand new, but the page shows open-box)"],
  },
  {
    id: "seller_6", name: "Central Comp", rank: 0, landed: 1222.23, unit: 1222.23, spec: "rtx 5070 ti", condition: "new", origin: "MIRROR",
    reasons: ["This is a dated store listing (MIRROR): it can never be ordered or paid"],
  },
];

export const REFERENCE_RUN: ArenaRows = (() => {
  const bid = (s: Spec) => `bid-${ROUND}-${s.id}`;
  const rounds: RoundRow[] = [{
    id: ROUND, needId: "need-reference", openedAt: ts(OPENED_MS), deadline: ts(OPENED_MS + WINDOW_S * 1000), state: "closed",
    sealedCount: SPECS.length, closedAt: ts(OPENED_MS + WINDOW_S * 1000), origin: "SIM",
  }];
  const results: ResultRow[] = SPECS.map((s, i) => ({
    id: BigInt(i + 1), roundId: ROUND, bidId: bid(s), sellerId: s.id, persona: s.name, rank: s.rank, landed: s.landed, reasons: s.reasons ?? [],
    lines: [{ skuSpec: "rtx 5070 ti", offeredSpec: s.spec, offeredCondition: s.condition, unitPrice: s.unit, quantity: 1 }],
    origin: s.origin, source: "",
  }));
  const events: EventRow[] = [];
  const push = (kind: string, refTable: string, refId: string, sellerId: string, label: string, atS: number, origin = "SIM") =>
    events.push({ id: BigInt(events.length + 1), kind, refTable, refId, sellerId, label, origin, at: ts(OPENED_MS + atS * 1000) });
  push("round_opened", "round", ROUND, "", `Sealed round open for ${WINDOW_S} s`, 0);
  SPECS.forEach((s, i) => push("bid_sealed", "bid", bid(s), s.id, "A sealed bid arrived", 10 + i * 12, s.origin));
  push("auction_closed", "round", ROUND, "seller_1", "Round closed: 2 ranked, 2 out", WINDOW_S);
  return { rounds, needs: [], results, events };
})();
