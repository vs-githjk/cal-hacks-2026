// Who on the floor moves for a floor_event row. Every motion on /floor comes from one of these rows; nothing idles.
import type { Origin } from "./screens";
import { SHIELD } from "./brand.ts";

export interface Actor {
  key: string;
  name: string;
  kind: "buyer" | "advocate" | "shield" | "referee" | "seller";
  origin: Origin;
}

export const FIXED_ACTORS: Actor[] = [
  { key: "buyer", name: "Buyer agent", kind: "buyer", origin: "SIM" },
  { key: "advocate", name: "Advocate", kind: "advocate", origin: "SIM" },
  { key: "shield", name: SHIELD, kind: "shield", origin: "SIM" },
  { key: "referee", name: "Referee", kind: "referee", origin: "SIM" },
];
export const MAX_SELLERS = 5;

const BUYER_KINDS = ["goal_posted", "goal_state", "need_posted", "mandate_created", "approval_recorded", "payment_recorded", "receiving_recorded"];

/** The actor a row belongs to: the seller it names, else the service that writes that kind, else the referee. */
export function actorFor(e: { kind: string; sellerId: string }, sellerKeys: ReadonlySet<string>): string {
  if (e.kind === "verdict") return "shield";
  if (e.kind === "advocate_card" || e.kind === "claim_checked") return "advocate";
  if ((e.kind === "bid_sealed" || e.kind === "bid_rejected") && sellerKeys.has(e.sellerId)) return `seller:${e.sellerId}`;
  if (BUYER_KINDS.includes(e.kind)) return "buyer";
  if (sellerKeys.has(e.sellerId)) return `seller:${e.sellerId}`;
  return "referee";
}
