// web/src/lib/screens.ts (or data/types.ts)
// View models for the two screens. Market rows map 1:1 onto the SpacetimeDB tables that already exist
// (round, roundResult, floorEvent, rejectedAttempt, goal, goalItem, allowance). The buyer's veto, Shield,
// approval and receipt cards need rows not yet in the public bindings (bidCheck, mandate, approval, payment),
// so they take plain props and are fed from demo/out/sample-run.json until those tables are exposed.

export type Origin = "LIVE" | "MIRROR" | "SIM";

export interface GoalView {
  text: string; // the buyer's own words
  type: "budget_cap" | "part_by_date" | "build_by_date";
  state: "ACTIVE" | "HUNTING" | "HOLD_FOR_CALL" | "DONE" | "EXPIRED" | "PAUSED";
  cap: number;
  reserved: number;
  deadline: Date;
  conditions: string[]; // allowed conditions, e.g. ["new", "open-box"]
  variant: string;
  origin: Origin;
  skipped: string[]; // sentences like "You already own a 750 W PSU ..."
  allowance: { perPurchase: number; periodLimit: number; period: string; spent: number; ladderStep: number } | null;
}

export type Recommendation = "veto" | "caution" | "buy" | "ineligible" | "refused";

export interface RankedBid {
  rank: number | null; // null when ineligible or refused
  seller: string;
  origin: Origin;
  condition: string;
  altLines?: { condition: string; unitPrice: number }[]; // the other condition lines the same seller bid
  landed: number;
  adjusted: number | null; // quality-adjusted; null when not ranked
  recommendation: Recommendation;
  why: string;
  sourceUrl?: string;
  won: boolean;
}

export interface VetoView {
  seller: string;
  origin: Origin;
  landed: number;
  claim: string; // what the seller said
  finding: string; // what the page showed
  ruleId: string;
  sourceUrl: string;
  checkedAt: Date;
  checkOrigin: Origin;
}

export interface ShieldView {
  verdict: "block" | "quarantine" | "allow";
  severity: string;
  seller: string;
  pageOrigin: Origin;
  chars: number;
  latencyMs: number;
  evidence: { text: string; hit: boolean }[]; // spans; hit = highlighted
  ruleIds: string[];
  control?: { name: string; verdict: string; latencyMs: number };
  version: string;
}

export interface ApprovalView {
  amount: number;
  payee: string;
  allowance: number;
  wordPair: string; // the one-time code shown on this screen only
  codeExpiresAt: Date;
  whyAnswer: string; // the advocate's spoken answer to "why not the cheaper one?"
  attempts: { at: Date; label: string; said: string; approved: boolean }[];
}

export interface ReceiptView {
  seller: string;
  item: string;
  condition: string;
  amount: number;
  shipping: number;
  paymentMethod: string;
  chargeId: string;
  chargeStatus: string; // e.g. "SIM stub, no money moved"
  paidAt: Date;
  mandateId: string;
  mandateHash: string;
  mandateExpires: Date;
  mandateOrigin: Origin;
  signature: string;
  replayRefused: boolean;
}

export type FeedKind = "deal" | "bid" | "veto" | "block" | "progress";
export interface FeedItem { key: string; at: Date; kind: FeedKind; title: string; text: string; origin?: Origin }

export interface RoundView {
  id: string;
  needId: string;
  openedAt: Date;
  windowMs: number;
  closedMs: number;
  extensions: number;
  sealedCount: number;
  state: "open" | "closed";
  origin: Origin;
  arrivals: { label: string; atMs: number; origin: Origin; refused: boolean }[];
  seenBeforeClose: { buyer: number; public: number };
}

export interface SellerLine {
  seller: string;
  origin: Origin;
  condition: string;
  landed: number;
  referee: "passed" | "refused";
  refereeReason?: string;
  outcome: { kind: "won" | "ranked" | "veto" | "ineligible" | "alt" | "refused"; rank?: number; note?: string };
}

export interface LossReport { seller: string; origin: Origin; gapBand: string; reason: string; sourceUrl: string }

export interface LearningView {
  seller: string;
  origin: Origin;
  whatToChange: string;
  whatToChangeOrigin: string;
  diff: { key: string; from: string; to: string; note?: string }[];
  control: string;
}

export interface FloorEventView { key: string; at: Date; kind: string; label: string; origin: Origin; ref: string }
