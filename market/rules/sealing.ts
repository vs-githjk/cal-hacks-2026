// Sealed bids: hidden until the deadline, with a capped anti-snipe extension.

export interface SealConfig {
  /** Seconds added to the deadline when a bid lands inside the snipe window. */
  extend_s: number;
  /** A bid this many seconds or fewer before the deadline triggers an extension. */
  snipe_window_s: number;
  max_extensions: number;
}

export const DEFAULT_SEAL: SealConfig = { extend_s: 5, snipe_window_s: 3, max_extensions: 2 };

export interface AuctionClock {
  need_id: string;
  opened_ms: number;
  deadline_ms: number;
  extensions: number;
  /** Set when the auction is closed explicitly (before or at the deadline). */
  closed_ms: number | null;
  config: SealConfig;
}

export type Viewer = { kind: "seller"; id: string } | { kind: "buyer" } | { kind: "public" };

export function newAuction(need_id: string, opened_ms: number, window_s: number, config: SealConfig = DEFAULT_SEAL): AuctionClock {
  return { need_id, opened_ms, deadline_ms: opened_ms + window_s * 1000, extensions: 0, closed_ms: null, config };
}

export function isClosed(a: AuctionClock, now_ms: number): boolean {
  return a.closed_ms !== null || now_ms >= a.deadline_ms;
}

export function closeAuction(a: AuctionClock, now_ms: number): AuctionClock {
  return a.closed_ms !== null ? a : { ...a, closed_ms: now_ms };
}

export type BidTiming =
  | { accepted: true; auction: AuctionClock; extended: boolean }
  | { accepted: false; auction: AuctionClock; reason: string };

export function tryBid(a: AuctionClock, now_ms: number): BidTiming {
  if (isClosed(a, now_ms)) return { accepted: false, auction: a, reason: "auction closed: bid arrived after the deadline" };
  const inSnipeWindow = a.deadline_ms - now_ms <= a.config.snipe_window_s * 1000;
  if (inSnipeWindow && a.extensions < a.config.max_extensions) {
    return {
      accepted: true,
      extended: true,
      auction: { ...a, deadline_ms: a.deadline_ms + a.config.extend_s * 1000, extensions: a.extensions + 1 },
    };
  }
  return { accepted: true, extended: false, auction: a };
}

/** Bids a viewer may see. Sellers only ever see their own; others see nothing until close. */
export function visibleBids<B extends { seller_id: string }>(bids: B[], a: AuctionClock, viewer: Viewer, now_ms: number): B[] {
  if (viewer.kind === "seller") return bids.filter((b) => b.seller_id === viewer.id);
  return isClosed(a, now_ms) ? bids : [];
}

/** What the board may show before close: a count, never prices or bidders' lines. */
export function sealedCount(bids: unknown[]): number {
  return bids.length;
}
