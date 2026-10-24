import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { closeAuction, isClosed, newAuction, sealedCount, tryBid, visibleBids } from "./sealing";

const cfg = { extend_s: 10, snipe_window_s: 5, max_extensions: 2 };
const bid = (id: string, supplier_id: string) => ({ id, supplier_id });

describe("sealing", () => {
  it("accepts a bid before the deadline without extending when early", () => {
    const a = newAuction("n1", 0, 60, cfg);
    const r = tryBid(a, 10_000);
    expect(r.accepted).toBe(true);
    expect(r.auction.deadline_ms).toBe(60_000);
  });

  it("extends the deadline when a bid lands in the snipe window", () => {
    const a = newAuction("n1", 0, 60, cfg);
    const r = tryBid(a, 57_000);
    expect(r.accepted).toBe(true);
    expect(r.auction.deadline_ms).toBe(70_000);
    expect(r.auction.extensions).toBe(1);
  });

  it("caps extensions at max_extensions", () => {
    let a = newAuction("n1", 0, 60, cfg);
    a = tryBid(a, 59_000).auction; // -> 70s
    a = tryBid(a, 69_000).auction; // -> 80s
    const r = tryBid(a, 79_000);
    expect(r.accepted).toBe(true);
    expect(r.auction.deadline_ms).toBe(80_000);
    expect(r.auction.extensions).toBe(2);
  });

  it("rejects bids at or after the deadline, and after an explicit close", () => {
    const a = newAuction("n1", 0, 60, cfg);
    expect(tryBid(a, 60_000)).toMatchObject({ accepted: false });
    const closed = closeAuction(a, 30_000);
    expect(tryBid(closed, 31_000)).toMatchObject({ accepted: false });
    expect(isClosed(closed, 31_000)).toBe(true);
  });

  it("before close, only the bidder sees its own bid; nobody else sees anything", () => {
    const a = newAuction("n1", 0, 60, cfg);
    const bids = [bid("b1", "s1"), bid("b2", "s2")];
    expect(visibleBids(bids, a, { kind: "supplier", id: "s1" }, 1000)).toEqual([bids[0]]);
    expect(visibleBids(bids, a, { kind: "buyer" }, 1000)).toEqual([]);
    expect(visibleBids(bids, a, { kind: "public" }, 1000)).toEqual([]);
    expect(sealedCount(bids)).toBe(2);
  });

  it("after close, buyer and public see all bids, suppliers still only their own", () => {
    const a = newAuction("n1", 0, 60, cfg);
    const bids = [bid("b1", "s1"), bid("b2", "s2")];
    expect(visibleBids(bids, a, { kind: "buyer" }, 61_000)).toEqual(bids);
    expect(visibleBids(bids, a, { kind: "public" }, 61_000)).toEqual(bids);
    expect(visibleBids(bids, a, { kind: "supplier", id: "s2" }, 61_000)).toEqual([bids[1]]);
  });

  it("property: before close, a non-bidder never sees another supplier's bid", () => {
    fc.assert(
      fc.property(
        fc.array(fc.record({ id: fc.uuid(), supplier_id: fc.constantFrom("s1", "s2", "s3") })),
        fc.constantFrom("s1", "s2", "s3", "s4"),
        fc.integer({ min: 0, max: 59_999 }),
        (bids, viewer, now) => {
          const a = newAuction("n", 0, 60, cfg);
          const seen = visibleBids(bids, a, { kind: "supplier", id: viewer }, now);
          return seen.every((b) => b.supplier_id === viewer);
        },
      ),
    );
  });
});
