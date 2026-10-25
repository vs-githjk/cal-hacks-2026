// web/src/lib/screens.ts (or data/types.ts)
// View models for the two screens. Market rows map 1:1 onto the SpacetimeDB tables that already exist
// (round, roundResult, floorEvent, rejectedAttempt, goal, goalItem, allowance). The buyer's veto, Shield,
// approval and receipt cards need rows not yet in the public bindings (bidCheck, mandate, approval, payment),
// so they take plain props and are fed from demo/out/sample-run.json until those tables are exposed.

export type Origin = "LIVE" | "MIRROR" | "SIM";

export interface GoalView {
  id: string;
  text: string; // the buyer's own words
  type: "budget_cap" | "part_by_date" | "build_by_date";
  state: "ACTIVE" | "HUNTING" | "HOLD_FOR_CALL" | "DONE" | "EXPIRED" | "PAUSED";
  cap: number;
  reserved: number;
  deadline: Date;
  conditions: string[]; // allowed conditions, e.g. ["new", "open-box"]
  variant: string;
  origin: Origin;
  skipped: { part: string; text: string }[]; // the owned part that was skipped ("PSU", "case") and the sentence about it
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
  recommendation: Recommendation;
  why: string;
  sourceUrl?: string;
  won: boolean;
  /** #191: the referee ranked it below confirmed bids (advocate caution); the reason as close_round wrote it. */
  heldBack?: string;
  /** The market row this bid was drawn from (round_result/<id>); absent on sample rows. */
  rowRef?: string;
}

export interface VetoView {
  seller: string;
  origin: Origin;
  landed: number;
  claim?: string; // what the seller said (a false claim check); absent when none was checked
  finding: string; // what the page showed
  ruleId: string;
  sourceUrl: string;
  checkedAt: Date;
  checkOrigin: Origin;
}

export interface ShieldView {
  verdict: "block" | "quarantine" | "allow";
  severity?: string; // severity, chars, latency and version come from the Shield service; a market row does not store them
  seller: string;
  pageOrigin: Origin;
  chars?: number;
  latencyMs?: number;
  evidence: { text: string; hit: boolean }[]; // spans; hit = highlighted
  ruleIds: string[];
  control?: { name: string; verdict: string; latencyMs: number };
  version?: string;
  verdictOrigin: Origin;
}

export interface ApprovalView {
  amount: number;
  payee: string;
  allowance: number;
  wordPair?: string; // the one-time code shown on this screen only (absent once a live deal is approved)
  codeExpiresAt: Date;
  whyAnswer?: string; // the advocate's spoken answer to "why not the cheaper one?"
  within?: boolean; // approved by the allowance rule, not a call
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

/** The mandateId my_pending_approvals gives the one code that approves a whole build (market.ts myPendingApprovalsView). */
export const WHOLE_BUILD_ID = "whole build";
export const isWholeBuild = (r: Pick<ReviewView, "mandateId">): boolean => r.mandateId === WHOLE_BUILD_ID;

/** Matches APPROVAL_MAX_FAILURES in market/spacetimedb/src/market.ts. */
export const REVIEW_MAX_FAILURES = 5;

export interface ReceiptView {
  seller: string;
  item?: string;
  condition?: string;
  amount: number;
  shipping?: number; // absent when the market row does not state it (never shown as $0)
  paymentMethod: string;
  chargeId: string;
  chargeStatus: string; // e.g. "SIM stub, no money moved"
  chargeOrigin?: Origin;
  paidAt: Date;
  mandateId: string;
  mandateHash: string;
  mandateExpires: Date;
  mandateOrigin: Origin;
  signature?: string;
  replayRefused?: boolean;
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
  arrivals: Arrival[];
  seenBeforeClose: { buyer: number; public: number };
}

export interface Arrival { label: string; atMs: number; origin: Origin; refused: boolean }

export interface SellerLine {
  seller: string;
  origin: Origin;
  condition: string;
  landed: number;
  referee: "passed" | "refused";
  refereeReason?: string;
  outcome: { kind: "won" | "ranked" | "held" | "veto" | "ineligible" | "alt" | "refused"; rank?: number; note?: string };
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

/** The round's winning bid, whatever its origin (the market and the producer enforce eligibility). */
export function winningBid<T extends { won?: boolean }>(bids: readonly T[]): T | undefined {
  return bids.find((b) => b.won);
}

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

interface GoalRow { id: string; buyerId: string; type: string; cap: number; deadline: Timestamp; state: string; reservedAmount: number; origin: string; createdAt: Timestamp }
interface GoalItemRow { goalId: string; skuSpec: string; condition: string; variant: string; quantity: number; skippedOwnedPartId: string }
interface AllowanceRow { buyerId: string; perPurchaseLimit: number; periodLimit: number; period: string; spentThisPeriod: number; ladderStep: number }

export function latestGoal<G extends GoalRow>(goals: readonly G[]): G | undefined {
  return [...goals].sort((a, b) => (a.createdAt.microsSinceUnixEpoch < b.createdAt.microsSinceUnixEpoch ? 1 : -1))[0];
}

/** "owned-psu" -> "PSU", "owned-case" -> "case": the part an owned-part id names, short ids as acronyms. */
function ownedPartLabel(id: string): string {
  const name = id.replace(/^owned-/, "").replaceAll("-", " ").trim() || "part";
  return name.length <= 3 ? name.toUpperCase() : name;
}

function goalView(g: GoalRow, items: readonly GoalItemRow[], allowance: AllowanceRow | undefined): GoalView {
  const mine = items.filter((i) => i.goalId === g.id);
  const deadline = d(g.deadline);
  const conditions = [...new Set(mine.map((i) => i.condition).filter(Boolean))];
  const what = mine.map((i) => `${i.quantity > 1 ? `${i.quantity} x ` : ""}${i.skuSpec}`).join(", ") || "a goal";
  const when = deadline.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return {
    id: g.id,
    text: `${what}${conditions.length ? `, ${conditions.join(" or ")}` : ""}, under ${formatMoney(Math.round(g.cap))} by ${when}`,
    type: (["budget_cap", "part_by_date", "build_by_date"].includes(g.type) ? g.type : "budget_cap") as GoalView["type"],
    state: g.state as GoalView["state"],
    cap: g.cap,
    reserved: g.reservedAmount,
    deadline,
    conditions,
    variant: mine.find((i) => i.variant)?.variant ?? "",
    origin: asOrigin(g.origin),
    skipped: mine.filter((i) => i.skippedOwnedPartId).map((i) => {
      const part = ownedPartLabel(i.skippedOwnedPartId);
      return { part, text: `You already own the ${part}, so it is not in this hunt.` };
    }),
    allowance: allowanceView(allowance),
  };
}

function allowanceView(a: AllowanceRow | undefined): GoalView["allowance"] {
  return a ? { perPurchase: a.perPurchaseLimit, periodLimit: a.periodLimit, period: a.period, spent: a.spentThisPeriod, ladderStep: a.ladderStep } : null;
}

/** The spending rule for one buyer; another buyer's row (a stale cache) is never shown. */
export function allowanceForBuyer(rows: readonly AllowanceRow[], buyerId: string): GoalView["allowance"] {
  return allowanceView(buyerId ? rows.find((r) => r.buyerId === buyerId) : undefined);
}

/** The newest goal in the rows, whoever owns it. /market and the sample screens use this; buyer screens use goalsForBuyer. */
export function goalFromRows(goals: readonly GoalRow[], items: readonly GoalItemRow[], allowance: AllowanceRow | undefined): GoalView | null {
  const g = latestGoal(goals);
  return g ? goalView(g, items, allowance) : null;
}

const OPEN_GOAL_STATES = ["ACTIVE", "HUNTING", "HOLD_FOR_CALL", "PAUSED"];

/**
 * One buyer's goals, open searches first and newest first within each group. Rows owned by anyone else (a stale
 * cache from a previous identity) and another buyer's allowance are dropped. Display hygiene only: the market's
 * my_* views are what authorize, this just keeps a stale row from rendering.
 */
export function goalsForBuyer(goals: readonly GoalRow[], items: readonly GoalItemRow[], allowance: AllowanceRow | undefined, buyerId: string): GoalView[] {
  if (!buyerId) return [];
  const mine = allowance?.buyerId === buyerId ? allowance : undefined;
  const open = (g: GoalRow) => (OPEN_GOAL_STATES.includes(g.state) ? 0 : 1);
  return goals
    .filter((g) => g.buyerId === buyerId)
    .sort((a, b) => open(a) - open(b) || (a.createdAt.microsSinceUnixEpoch < b.createdAt.microsSinceUnixEpoch ? 1 : -1))
    .map((g) => goalView(g, items, mine));
}

interface RoleRow { role: string; subjectId: string }
export type BuyerSession = { status: "connecting" } | { status: "unpaired" } | { status: "buyer"; buyerId: string };

/** Who this screen is paired as, from the market's own my_role row. Anything unclear fails closed: no connection, no roles yet, no buyer role, or two different buyers. */
export function buyerSession(connected: boolean, rolesReady: boolean, roles: readonly RoleRow[]): BuyerSession {
  if (!connected || !rolesReady) return { status: "connecting" };
  const ids = new Set(roles.filter((r) => r.role === "buyer" && r.subjectId).map((r) => r.subjectId));
  return ids.size === 1 ? { status: "buyer", buyerId: [...ids][0]! } : { status: "unpaired" };
}

interface EventRow { id: bigint; kind: string; refTable: string; refId: string; sellerId: string; label: string; origin: string; at: Timestamp }
interface LineRow { offeredCondition: string; unitPrice: number }
interface ResultRow {
  id: bigint; roundId: string; bidId: string; sellerId: string; persona: string; rank: number; landed: number; reasons: string[];
  lines: LineRow[]; origin: string; source: string;
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

/** The home question. It names no dollar figure: the cap is the buyer's own (demo/build.py), so a number here would drift from it. */
export function buildQuestion(): string {
  return "Who builds the best 1440p gaming PC under the buyer's cap?";
}

export interface HomeRound { status: "loading" | "none" | "open" | "closed"; title: string; pill: string }

/** What home says about the market (#398): from the newest real round, in words, never its raw id. No round means "no round yet", so the
 * page never shows a round as open while saying there is none. */
export function homeRound<R extends RoundRow>(rounds: readonly R[], ready = true): HomeRound {
  const r = latestRound(rounds);
  // Until the round table's subscription lands, an empty list means "not loaded", not "no round": say so neutrally.
  if (!ready && !r) return { status: "loading", title: "Connecting...", pill: "connecting..." };
  if (!r) return { status: "none", title: "No round yet", pill: "no round yet" };
  const status = r.state === "open" ? "open" : "closed";
  const title = roundTitle(r.id) ?? "Latest round";
  return { status, title, pill: `${title}, ${status}` };
}

const PART_WORD: Record<string, string> = { board: "Motherboard", gpu: "Graphics card", cpu: "Processor", ram: "Memory", ssd: "Storage", cooler: "CPU cooler", psu: "Power supply", case: "Case" };

/** "Motherboard, round 2" for a build round id like round-goal-build-1-board-2; null when the id is not a build round. */
export function roundTitle(roundId: string): string | null {
  const m = /-([a-z]+)-([1-9]\d*)$/.exec(roundId);
  return m && Object.hasOwn(PART_WORD, m[1]!) ? `${PART_WORD[m[1]!]}, round ${m[2]}` : null;
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
      const held = ranked ? r.reasons.find((x) => x.startsWith("held back")) : undefined;
      return {
        rank: ranked ? r.rank : null,
        seller: r.persona || r.sellerId,
        origin: asOrigin(r.origin),
        condition: cond(picked?.offeredCondition ?? ""),
        altLines: r.lines.slice(1).map((l) => ({ condition: cond(l.offeredCondition), unitPrice: l.unitPrice })),
        landed: r.landed,
        recommendation: card?.rec ?? (ranked ? "unchecked" : refused ? "refused" : "ineligible"),
        why: r.reasons.join("; ") || card?.label || "",
        sourceUrl: safeUrl(r.source) ?? undefined,
        won: r.rank === 1 && card?.rec !== "veto",
        ...(held ? { heldBack: held } : {}),
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
      const held = r.reasons.find((x) => x.startsWith("held back"));
      if (held) return { ...base, outcome: { kind: "held", rank: r.rank, note: held } };
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

/** The honest origin mix as "18 bids · 12 MIRROR · 6 SIM" (zero counts dropped from the breakdown); "" when every count is 0. */
export function originMixLabel(c: { LIVE: number; MIRROR: number; SIM: number }): string {
  const total = c.LIVE + c.MIRROR + c.SIM;
  if (total === 0) return "";
  const breakdown = (["LIVE", "MIRROR", "SIM"] as const).filter((o) => c[o] > 0).map((o) => `${c[o]} ${o}`).join(" · ");
  return `${total} bid${total === 1 ? "" : "s"} · ${breakdown}`;
}

/**
 * Group a round's arrivals (sorted by atMs, as roundFromRows gives them) into clusters no two of which land
 * within gapFrac of the track, so a dense run of near-simultaneous bids draws as one marker, never a pile of
 * overlapping dots or labels. Every arrival stays in exactly one cluster: none are dropped.
 */
export function clusterArrivals(arrivals: readonly Arrival[], totalMs: number, gapFrac = 0.03): Arrival[][] {
  if (!arrivals.length) return [];
  const minGap = gapFrac * totalMs;
  const clusters: Arrival[][] = [[arrivals[0]!]];
  for (let i = 1; i < arrivals.length; i++) {
    const a = arrivals[i]!;
    const cur = clusters[clusters.length - 1]!;
    if (a.atMs - cur[cur.length - 1]!.atMs < minGap) cur.push(a);
    else clusters.push([a]);
  }
  return clusters;
}

interface PendingRow { mandateHash: string; mandateId: string; amount: number; payee: string; expiry: Timestamp; code: string; failures: number; locked: boolean; origin: string }

export function reviewFromRows(rows: readonly PendingRow[]): ReviewView | null {
  const r = [...rows].sort((a, b) => (a.expiry.microsSinceUnixEpoch < b.expiry.microsSinceUnixEpoch ? 1 : -1))[0];
  return r ? { ...r, expiry: d(r.expiry), origin: asOrigin(r.origin) } : null;
}

// ---- #191-5: live veto, Shield, approval and receipt cards (my_bid_checks, my_deals). Only what the rows hold; nothing filled in.

interface CheckRow { id: bigint; bidId: string; roundId: string; sellerId: string; persona: string; bidOrigin: string; kind: string; result: string; detail: string; evidenceUrl: string; origin: string; at: Timestamp }
interface DealRow {
  mandateHash: string; mandateId: string; dealId: string; amount: number; payee: string; expiry: Timestamp; withinAllowance: boolean; origin: string;
  approvalMethod: string; voiceApprovalId: string; approvedAt?: Timestamp; paymentRef: string; paymentMode: string; paidAt?: Timestamp;
}

const latestOf = <T extends { id: bigint }>(xs: T[]) => [...xs].sort((a, b) => (a.id < b.id ? 1 : -1))[0];

/** The latest advocate veto in this round, with the seller's false claim (if one was checked) and the landed price. */
export function vetoFromRows(checks: readonly CheckRow[], results: readonly ResultRow[], roundId: string | undefined): VetoView | null {
  const c = latestOf(checks.filter((x) => x.roundId === roundId && x.kind === "advocate" && x.result === "veto"));
  if (!c) return null;
  const [, rule = "", text = c.detail] = /^([\w.]+): (.*)$/s.exec(c.detail) ?? [];
  const claim = latestOf(checks.filter((x) => x.bidId === c.bidId && x.kind === "claim" && x.result === "false"));
  return {
    seller: c.persona || c.sellerId, origin: asOrigin(c.bidOrigin), landed: results.find((r) => r.bidId === c.bidId)?.landed ?? 0,
    ...(claim ? { claim: claim.detail } : {}), finding: text, ruleId: rule, sourceUrl: c.evidenceUrl, checkedAt: d(c.at), checkOrigin: asOrigin(c.origin),
  };
}

/** The latest Smell Test (Shield) block or quarantine in this round, with the rule ids the row stores. */
export function shieldFromRows(checks: readonly CheckRow[], roundId: string | undefined): ShieldView | null {
  const c = latestOf(checks.filter((x) => x.roundId === roundId && x.kind === "shield" && x.result !== "allow"));
  if (!c) return null;
  return {
    verdict: c.result === "quarantine" ? "quarantine" : "block", seller: c.persona || c.sellerId, pageOrigin: asOrigin(c.bidOrigin),
    evidence: [], ruleIds: c.detail.split(",").map((x) => x.trim()).filter(Boolean), verdictOrigin: asOrigin(c.origin),
  };
}

const PAY_LABEL: Record<string, { method: string; status: string; origin: Origin }> = {
  sim: { method: "SIM stub", status: "SIM stub, no money moved", origin: "SIM" },
  stripe_test: { method: "Stripe test mode", status: "Stripe test mode", origin: "LIVE" },
};

/** The buyer's latest deal: the approval card once the call (or the allowance) approved it, the receipt once paid. */
export function dealFromRows(deals: readonly DealRow[], allowance: number | null, results: readonly ResultRow[] = []): { approval: ApprovalView | null; receipt: ReceiptView | null } {
  const dl = [...deals].sort((a, b) => (a.expiry.microsSinceUnixEpoch < b.expiry.microsSinceUnixEpoch ? 1 : -1))[0];
  if (!dl) return { approval: null, receipt: null };
  const approval: ApprovalView | null = dl.approvalMethod && dl.approvedAt
    ? {
        amount: dl.amount, payee: dl.payee, allowance: allowance ?? 0, codeExpiresAt: d(dl.expiry), within: dl.approvalMethod === "allowance",
        attempts: [{ at: d(dl.approvedAt), label: dl.approvalMethod === "allowance" ? "Approved within the allowance" : "Approved on the call", said: dl.voiceApprovalId ? `VoiceApproval ${dl.voiceApprovalId}` : "", approved: true }],
      }
    : null;
  const bidId = dl.dealId.replace(/^deal-/, "").split(":").pop();
  const line = results.find((r) => r.bidId === bidId)?.lines[0] as (LineRow & { skuSpec?: string }) | undefined;
  const pay = PAY_LABEL[dl.paymentMode] ?? PAY_LABEL.sim!;
  const receipt: ReceiptView | null = dl.paidAt
    ? {
        seller: dl.payee, ...(line?.skuSpec ? { item: line.skuSpec } : {}), ...(line?.offeredCondition ? { condition: line.offeredCondition } : {}),
        amount: dl.amount, paymentMethod: pay.method, chargeId: dl.paymentRef, chargeStatus: pay.status, chargeOrigin: pay.origin, paidAt: d(dl.paidAt),
        mandateId: dl.mandateId, mandateHash: dl.mandateHash, mandateExpires: d(dl.expiry), mandateOrigin: asOrigin(dl.origin),
      }
    : null;
  return { approval, receipt };
}
