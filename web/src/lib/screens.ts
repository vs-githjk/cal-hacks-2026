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

export type Recommendation = "veto" | "caution" | "buy" | "ineligible" | "refused" | "unchecked"; // unchecked: ranked, no advocate card yet

export interface RankedBid {
  rank: number | null; // null when ineligible or refused
  seller: string;
  origin: Origin;
  condition: string;
  altLines?: { condition: string; unitPrice: number }[]; // the other condition lines the same seller bid
  landed: number;
  adjusted: number | null; // quality-adjusted score the ranking used; null when not ranked; equals landed when nothing adjusted it
  adjustedReason: string; // why adjusted differs from landed ("" when it does not)
  recommendation: Recommendation;
  why: string;
  sourceUrl?: string;
  won: boolean;
  /** The market row this bid was drawn from (round_result/<id>); absent on sample rows. */
  rowRef?: string;
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
  verdictOrigin: Origin;
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

/** A live mandate waiting for the buyer, from my_pending_approvals. The code shows on this screen only. */
export interface ReviewView {
  mandateHash: string;
  mandateId: string;
  amount: number;
  payee: string;
  expiry: Date;
  code: string;
  failures: number;
  locked: boolean;
  origin: Origin;
}

/** Matches APPROVAL_MAX_FAILURES in market/spacetimedb/src/market.ts. */
export const REVIEW_MAX_FAILURES = 5;

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

// ---- Row to view mapping (see docs/design/2026-10-23-web/README.md). Plain row shapes so this stays testable.

import type { Timestamp } from "spacetimedb";
import { formatMoney } from "./money.ts";
import { safeUrl } from "./url.ts";

const d = (ts: Timestamp) => new Date(Number(ts.microsSinceUnixEpoch / BigInt(1000)));
export const asOrigin = (o: string): Origin => (o === "LIVE" || o === "MIRROR" ? o : "SIM");

/** A sample view shown in place of an empty table: every origin becomes SIM, so no sample number reads as LIVE or MIRROR. */
export function asSim<T>(v: T): T {
  if (Array.isArray(v)) return v.map(asSim) as T;
  if (v && typeof v === "object" && !(v instanceof Date)) {
    return Object.fromEntries(
      Object.entries(v).map(([k, x]) => [k, /origin$/i.test(k) && (x === "LIVE" || x === "MIRROR") ? "SIM" : asSim(x)]),
    ) as T;
  }
  return v;
}

interface GoalRow { id: string; type: string; cap: number; deadline: Timestamp; state: string; reservedAmount: number; origin: string; createdAt: Timestamp }
interface GoalItemRow { goalId: string; skuSpec: string; condition: string; variant: string; quantity: number; skippedOwnedPartId: string }
interface AllowanceRow { perPurchaseLimit: number; periodLimit: number; period: string; spentThisPeriod: number; ladderStep: number }

export function latestGoal<G extends GoalRow>(goals: readonly G[]): G | undefined {
  return [...goals].sort((a, b) => (a.createdAt.microsSinceUnixEpoch < b.createdAt.microsSinceUnixEpoch ? 1 : -1))[0];
}

export function goalFromRows(goals: readonly GoalRow[], items: readonly GoalItemRow[], allowance: AllowanceRow | undefined): GoalView | null {
  const g = latestGoal(goals);
  if (!g) return null;
  const mine = items.filter((i) => i.goalId === g.id);
  const deadline = d(g.deadline);
  const conditions = [...new Set(mine.map((i) => i.condition).filter(Boolean))];
  const what = mine.map((i) => `${i.quantity > 1 ? `${i.quantity} x ` : ""}${i.skuSpec}`).join(", ") || "a goal";
  const when = deadline.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return {
    text: `${what}${conditions.length ? `, ${conditions.join(" or ")}` : ""}, under ${formatMoney(Math.round(g.cap))} by ${when}`,
    type: (["budget_cap", "part_by_date", "build_by_date"].includes(g.type) ? g.type : "budget_cap") as GoalView["type"],
    state: g.state as GoalView["state"],
    cap: g.cap,
    reserved: g.reservedAmount,
    deadline,
    conditions,
    variant: mine.find((i) => i.variant)?.variant ?? "",
    origin: asOrigin(g.origin),
    skipped: mine.filter((i) => i.skippedOwnedPartId).map((i) => `Already owned (${i.skippedOwnedPartId}), so it is not in this hunt.`),
    allowance: allowance
      ? { perPurchase: allowance.perPurchaseLimit, periodLimit: allowance.periodLimit, period: allowance.period, spent: allowance.spentThisPeriod, ladderStep: allowance.ladderStep }
      : null,
  };
}

interface EventRow { id: bigint; kind: string; refTable: string; refId: string; sellerId: string; label: string; origin: string; at: Timestamp }
interface LineRow { offeredCondition: string; unitPrice: number }
interface ResultRow {
  id: bigint; roundId: string; bidId: string; sellerId: string; persona: string; rank: number; landed: number; reasons: string[];
  lines: LineRow[]; origin: string; source: string; adjustedTotal: number; adjustmentReason: string;
}
interface RoundRow { id: string; needId: string; openedAt: Timestamp; deadline: Timestamp; extensions: number; state: string; sealedCount: number; closedAt?: Timestamp; origin: string }

/** The latest advocate card per bid, read from the public advocate_card events ("Advocate veto (rule)" or "Advocate: buy"). */
function advocateByBid(events: readonly EventRow[]): Map<string, { rec: "veto" | "caution" | "buy"; label: string }> {
  const m = new Map<string, { rec: "veto" | "caution" | "buy"; label: string }>();
  for (const e of [...events].filter((x) => x.kind === "advocate_card").sort((a, b) => (a.id < b.id ? -1 : 1))) {
    const rec = e.label.startsWith("Advocate veto") ? "veto" : e.label.endsWith("caution") ? "caution" : e.label.endsWith("buy") ? "buy" : null;
    if (rec) m.set(e.refId, { rec, label: e.label });
  }
  return m;
}

export function latestRound<R extends RoundRow>(rounds: readonly R[]): R | undefined {
  return [...rounds].sort((a, b) => (a.openedAt.microsSinceUnixEpoch < b.openedAt.microsSinceUnixEpoch ? 1 : -1))[0];
}

const cond = (c: string) => c || "as asked";

export function bidsFromRows(results: readonly ResultRow[], events: readonly EventRow[], roundId: string | undefined): RankedBid[] {
  const adv = advocateByBid(events);
  return results
    .filter((r) => r.roundId === roundId)
    .sort((a, b) => (a.rank || 999) - (b.rank || 999) || a.landed - b.landed)
    .map((r) => {
      const card = adv.get(r.bidId);
      const ranked = r.rank > 0;
      const picked = r.lines[0];
      const refused = !ranked && r.reasons.some((x) => /floor/i.test(x));
      return {
        rank: ranked ? r.rank : null,
        seller: r.persona || r.sellerId,
        origin: asOrigin(r.origin),
        condition: cond(picked?.offeredCondition ?? ""),
        altLines: r.lines.slice(1).map((l) => ({ condition: cond(l.offeredCondition), unitPrice: l.unitPrice })),
        landed: r.landed,
        adjusted: ranked ? r.adjustedTotal : null,
        adjustedReason: ranked ? r.adjustmentReason : "",
        recommendation: card?.rec ?? (ranked ? "unchecked" : refused ? "refused" : "ineligible"),
        why: r.reasons.join("; ") || card?.label || "",
        sourceUrl: safeUrl(r.source) ?? undefined,
        won: r.rank === 1 && card?.rec !== "veto",
        rowRef: `round_result/${r.id}`,
      };
    });
}

const FEED_TITLE: Record<FeedKind, string> = { deal: "Deal found", bid: "Bid in", veto: "Veto", block: "Block", progress: "Progress" };
const PROGRESS = ["goal_posted", "goal_state", "need_posted", "round_opened", "approval_recorded", "payment_recorded", "mandate_created"];

function classify(kind: string, label: string): FeedKind | null {
  if (kind === "bid_sealed") return "bid";
  if (kind === "auction_closed") return label.includes("no eligible") ? "progress" : "deal";
  if (kind === "verdict" && !label.endsWith("allow")) return "block";
  if (kind === "bid_rejected" || (kind === "advocate_card" && label.startsWith("Advocate veto")) || (kind === "claim_checked" && label.endsWith("false"))) return "veto";
  if (PROGRESS.includes(kind)) return "progress";
  return null;
}

interface NoteRow { id: bigint; klass: string; text: string; at: Timestamp }

export function feedFromRows(events: readonly EventRow[], notes: readonly NoteRow[]): FeedItem[] {
  const fromEvents = events.flatMap((e): FeedItem[] => {
    const kind = classify(e.kind, e.label);
    return kind ? [{ key: `e${e.id}`, at: d(e.at), kind, title: FEED_TITLE[kind], text: e.label, origin: asOrigin(e.origin) }] : [];
  });
  const fromNotes = notes.map((n): FeedItem => {
    const kind: FeedKind = n.klass === "veto" ? "veto" : "progress";
    return { key: `n${n.id}`, at: d(n.at), kind, title: FEED_TITLE[kind], text: n.text, origin: "SIM" };
  });
  return [...fromEvents, ...fromNotes].sort((a, b) => b.at.getTime() - a.at.getTime());
}

const ms = (ts: Timestamp) => Number(ts.microsSinceUnixEpoch / BigInt(1000));

export function roundFromRows(r: RoundRow, events: readonly EventRow[], results: readonly ResultRow[]): RoundView {
  const opened = ms(r.openedAt);
  const windowS = Number(events.find((e) => e.kind === "round_opened" && e.refId === r.id)?.label.match(/(\d+(?:\.\d+)?) s/)?.[1]);
  const windowMs = Number.isFinite(windowS) ? windowS * 1000 : ms(r.deadline) - opened;
  const end = r.closedAt ? ms(r.closedAt) : ms(r.deadline);
  const name = new Map(results.map((x) => [x.bidId, x.persona || x.sellerId]));
  const arrivals = events
    .filter((e) => (e.kind === "bid_sealed" || e.kind === "bid_rejected") && e.refTable === "bid" && ms(e.at) >= opened && ms(e.at) <= end)
    .map((e) => ({ label: name.get(e.refId) ?? (e.sellerId || e.refId), atMs: ms(e.at) - opened, origin: asOrigin(e.origin), refused: e.kind === "bid_rejected" }))
    .sort((a, b) => a.atMs - b.atMs);
  return {
    id: r.id,
    needId: r.needId,
    openedAt: d(r.openedAt),
    windowMs,
    closedMs: Math.max(windowMs, end - opened),
    extensions: r.extensions,
    sealedCount: r.sealedCount,
    state: r.state === "closed" ? "closed" : "open",
    origin: asOrigin(r.origin),
    arrivals,
    seenBeforeClose: { buyer: 0, public: 0 }, // bids are private until close by construction (the bid table is not public)
  };
}

/** Floor rejections in a round: bid_rejected events on the bid table between open and close (the bid itself stays private). */
function refusedInRound(events: readonly EventRow[], r: RoundRow): EventRow[] {
  const opened = ms(r.openedAt);
  const end = r.closedAt ? ms(r.closedAt) : ms(r.deadline);
  return events.filter((e) => e.kind === "bid_rejected" && e.refTable === "bid" && ms(e.at) >= opened && ms(e.at) <= end);
}

export function linesFromRows(results: readonly ResultRow[], events: readonly EventRow[], round: RoundRow): SellerLine[] {
  const adv = advocateByBid(events);
  const rows = results.filter((r) => r.roundId === round.id);
  const out: SellerLine[] = rows.flatMap((r) =>
    r.lines.map((l, i): SellerLine => {
      const card = adv.get(r.bidId);
      const base = { seller: r.persona || r.sellerId, origin: asOrigin(r.origin), condition: cond(l.offeredCondition), landed: i === 0 ? r.landed : l.unitPrice, referee: "passed" as const };
      if (i > 0) return { ...base, outcome: { kind: "alt", note: "not the picked line" } };
      if (r.rank === 0) return { ...base, outcome: { kind: "ineligible", note: r.reasons.join("; ") || "not eligible" } };
      if (card?.rec === "veto") return { ...base, outcome: { kind: "veto", rank: r.rank, note: card.label } };
      return { ...base, outcome: { kind: r.rank === 1 ? "won" : "ranked", rank: r.rank } };
    }),
  );
  const refused = refusedInRound(events, round).map(
    (e): SellerLine => ({ seller: e.sellerId || e.refId, origin: asOrigin(e.origin), condition: "·", landed: 0, referee: "refused", refereeReason: "below own floor", outcome: { kind: "refused" } }),
  );
  return [...out, ...refused];
}

export function eventsFromRows(events: readonly EventRow[]): FloorEventView[] {
  return [...events]
    .sort((a, b) => (a.id < b.id ? 1 : -1))
    .map((e) => ({ key: String(e.id), at: d(e.at), kind: e.kind, label: e.label, origin: asOrigin(e.origin), ref: `${e.refTable}/${e.refId}` }));
}

export function originCounts(items: readonly { origin: Origin }[]): { LIVE: number; MIRROR: number; SIM: number } {
  const c = { LIVE: 0, MIRROR: 0, SIM: 0 };
  for (const i of items) c[i.origin]++;
  return c;
}

interface PendingRow { mandateHash: string; mandateId: string; amount: number; payee: string; expiry: Timestamp; code: string; failures: number; locked: boolean; origin: string }

export function reviewFromRows(rows: readonly PendingRow[]): ReviewView | null {
  const r = [...rows].sort((a, b) => (a.expiry.microsSinceUnixEpoch < b.expiry.microsSinceUnixEpoch ? 1 : -1))[0];
  return r ? { ...r, expiry: d(r.expiry), origin: asOrigin(r.origin) } : null;
}
