// Contract compatibility: Lane A validates its Needs and Bids against these same files
// (agents/common.py validate). Their current shapes, copied from agents/buyer/goal.py
// need_from_goal and agents/sellers/policy.py make_bid on main, must keep validating.
import { describe, expect, it } from "vitest";
import Ajv2020 from "ajv/dist/2020";
import { readFileSync } from "node:fs";

const ajv = new Ajv2020({ strict: false });
const load = (name: string) => ajv.compile(JSON.parse(readFileSync(new URL(`../../contracts/${name}.schema.json`, import.meta.url), "utf8")));
const need = load("Need");
const bid = load("Bid");

const laneANeed = () => ({
  id: "need-1a2b3c4d", buyer_id: "vidyut",
  items: [{ sku_spec: "rtx 4070 super 12gb", condition: "new", variant: "retail", quantity: 1, unit: "each", grade: "new", pack_size: "retail" }],
  delivery_window: "by 2026-10-30T23:59:00Z", spend_limit: 800, consent: true, auction_window_s: 12, source: "live",
});

const laneABid = (): Record<string, unknown> => ({
  id: "bid-n-flash", need_id: "n", supplier_id: "flashdeal-frankie", persona: "FlashDeal Frankie",
  lines: [{ sku_spec: "rtx 4070 super 12gb", unit_price: 520, quantity: 1, offered_condition: "new", variant: "retail", listing_url: "u", page_condition: "open-box", attrs: {} }],
  total_landed_price: 529.99, perks: [], claims: [], floor_check_passed: true, mirror_snapshot_id: "m", decision_trace: "t",
  expires_at: "2026-10-24T06:00:00Z", origin: "SIM", source: "simulated",
});

describe("Lane A compatibility", () => {
  it("Lane A's current Need validates", () => {
    expect(need(laneANeed()), JSON.stringify(need.errors)).toBe(true);
  });
  it("Lane A's current Bid with supplier_id validates (deprecated alias)", () => {
    expect(bid(laneABid()), JSON.stringify(bid.errors)).toBe(true);
  });
  it("a Bid with seller_id validates", () => {
    const { supplier_id, ...rest } = laneABid();
    expect(bid({ ...rest, seller_id: supplier_id }), JSON.stringify(bid.errors)).toBe(true);
  });
  it("a Bid with neither seller_id nor supplier_id is rejected", () => {
    const { supplier_id: _drop, ...rest } = laneABid();
    expect(bid(rest)).toBe(false);
  });
});
