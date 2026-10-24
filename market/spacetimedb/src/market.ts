// Reducer and view bodies as plain functions over ctx, so tests call them directly through the
// module test harness. index.ts registers them. All market logic comes from market/rules, which
// the Convex fallback would call unchanged.
import { SenderError, type InferSchema, type ReducerCtx, type ViewCtx, type AnonymousViewCtx } from 'spacetimedb/server';
import { ScheduleAt, Timestamp, type Identity } from 'spacetimedb';
import type spacetimedb from './schema';
import { checkFloor } from '../../rules/floor';
import { rankBids } from '../../rules/scoring';
import { DEFAULT_SEAL, isClosed, tryBid, type AuctionClock } from '../../rules/sealing';
import { sellerView } from '../../rules/redaction';
import { authorizePayment } from '../../rules/approval';
import type { Bid, Condition, NeedItem, Origin } from '../../rules/types';

type S = InferSchema<typeof spacetimedb>;
type Ctx = ReducerCtx<S>;
type VCtx = ViewCtx<S>;
type AVCtx = AnonymousViewCtx<S>;

type Line = { skuSpec: string; offeredSpec: string; offeredCondition: string; unitPrice: number; quantity: number };

const ms = (ts: Timestamp) => Number(ts.microsSinceUnixEpoch / 1000n);
const tsFromMs = (x: number) => new Timestamp(BigInt(Math.round(x)) * 1000n);

function event(ctx: Ctx, kind: string, refTable: string, refId: string, label: string, sellerId = '', origin = 'SIM') {
  ctx.db.floorEvent.insert({ id: 0n, kind, refTable, refId, sellerId, label, origin, at: ctx.timestamp });
}

function rejected(ctx: Ctx, kind: string, refId: string, reason: string) {
  ctx.db.rejectedAttempt.insert({ id: 0n, kind, refId, reason, at: ctx.timestamp });
  event(ctx, `${kind}_rejected`, 'rejected_attempt', refId, reason);
}

const sellerOf = (ctx: { db: Ctx['db'] | VCtx['db']; sender: Identity }) => ctx.db.sellerIdentity.identity.find(ctx.sender);

// ---------------------------------------------------------------- identities

export function registerSeller(ctx: Ctx, { sellerId }: { sellerId: string }) {
  if (!sellerId) throw new SenderError('seller id required');
  const existing = ctx.db.sellerIdentity.sellerId.find(sellerId);
  if (existing && !existing.identity.isEqual(ctx.sender)) throw new SenderError(`${sellerId} is already registered to another agent`);
  if (ctx.db.buyerSession.identity.find(ctx.sender)) throw new SenderError('a buyer screen cannot register as a seller');
  if (!existing) ctx.db.sellerIdentity.insert({ identity: ctx.sender, sellerId });
}

export function setFloor(ctx: Ctx, { skuSpec, floor }: { skuSpec: string; floor: number }) {
  const me = sellerOf(ctx);
  if (!me) throw new SenderError('only a registered seller may set its floor');
  for (const f of ctx.db.sellerFloor.sellerId.filter(me.sellerId)) if (f.skuSpec === skuSpec) ctx.db.sellerFloor.id.delete(f.id);
  ctx.db.sellerFloor.insert({ id: 0n, sellerId: me.sellerId, skuSpec, floor });
}

/** Demo sign-in for a buyer screen (SIM). A registered seller identity can never open one. */
export function openBuyerSession(ctx: Ctx, { buyerId }: { buyerId: string }) {
  if (sellerOf(ctx)) throw new SenderError('a seller agent cannot open a buyer session');
  const cur = ctx.db.buyerSession.identity.find(ctx.sender);
  if (cur) ctx.db.buyerSession.identity.update({ ...cur, buyerId });
  else ctx.db.buyerSession.insert({ identity: ctx.sender, buyerId });
}

// ---------------------------------------------------------------- needs and goals

export interface PostNeedArgs {
  id: string; buyerId: string; goalId: string; deliveryWindow: string; spendLimit: number; consent: boolean;
  auctionWindowS: number; origin: string;
  items: { skuSpec: string; condition: string; variant: string; quantity: number; unit: string }[];
}

export function postNeed(ctx: Ctx, a: PostNeedArgs) {
  if (ctx.db.need.id.find(a.id)) throw new SenderError(`need ${a.id} already exists`);
  if (!a.items.length) throw new SenderError('a need has at least one item');
  ctx.db.need.insert({
    id: a.id, buyerId: a.buyerId, goalId: a.goalId, deliveryWindow: a.deliveryWindow, spendLimit: a.spendLimit,
    consent: a.consent, auctionWindowS: a.auctionWindowS, origin: a.origin, createdAt: ctx.timestamp,
  });
  for (const i of a.items) ctx.db.needItem.insert({ id: 0n, needId: a.id, ...i });
  event(ctx, 'need_posted', 'need', a.id, `New request: ${a.items.length} item(s)`, '', a.origin);
}

export interface PostGoalArgs {
  id: string; buyerId: string; type: string; text: string; cap: number; deadlineMinutes: number; poNumber: string; origin: string;
  items: { category: string; description: string; skuSpec: string; modelNumber: string }[];
}

export const GOAL_TYPES = ['budget_cap', 'part_by_date', 'build_by_date'];

export function postGoal(ctx: Ctx, a: PostGoalArgs) {
  if (!GOAL_TYPES.includes(a.type)) throw new SenderError(`goal type must be one of ${GOAL_TYPES.join(', ')}`);
  if (ctx.db.goal.id.find(a.id)) throw new SenderError(`goal ${a.id} already exists`);
  if (!(a.cap > 0)) throw new SenderError('goal cap must be positive');
  ctx.db.goal.insert({
    id: a.id, buyerId: a.buyerId, type: a.type, text: a.text, cap: a.cap,
    deadline: tsFromMs(ms(ctx.timestamp) + a.deadlineMinutes * 60_000), state: 'ACTIVE', reservedAmount: 0,
    poNumber: a.poNumber, origin: a.origin, createdAt: ctx.timestamp,
  });
  for (const i of a.items) ctx.db.goalItem.insert({ id: 0n, goalId: a.id, ...i });
  ctx.db.notification.insert({ id: 0n, buyerId: a.buyerId, goalId: a.id, klass: 'state', text: 'Goal set. The agent is hunting.', push: false, at: ctx.timestamp });
  event(ctx, 'goal_posted', 'goal', a.id, 'A buyer set a goal', '', a.origin);
}

// ---------------------------------------------------------------- rounds

function clockOf(r: { needId: string; openedAt: Timestamp; deadline: Timestamp; extensions: number; state: string; closedAt: Timestamp | undefined }): AuctionClock {
  return {
    need_id: r.needId, opened_ms: ms(r.openedAt), deadline_ms: ms(r.deadline), extensions: r.extensions,
    closed_ms: r.state === 'closed' && r.closedAt ? ms(r.closedAt) : null, config: DEFAULT_SEAL,
  };
}

function scheduleClose(ctx: Ctx, roundId: string, at: Timestamp) {
  ctx.db.roundTimer.insert({ scheduledId: 0n, scheduledAt: ScheduleAt.time(at.microsSinceUnixEpoch), roundId });
}

export function openRound(ctx: Ctx, { roundId, needId, windowS }: { roundId: string; needId: string; windowS: number }) {
  const n = ctx.db.need.id.find(needId);
  if (!n) throw new SenderError(`no need ${needId}`);
  if (ctx.db.round.id.find(roundId)) throw new SenderError(`round ${roundId} already exists`);
  const deadline = tsFromMs(ms(ctx.timestamp) + windowS * 1000);
  ctx.db.round.insert({ id: roundId, needId, openedAt: ctx.timestamp, deadline, extensions: 0, state: 'open', sealedCount: 0, closedAt: undefined, origin: n.origin });
  scheduleClose(ctx, roundId, deadline);
  event(ctx, 'round_opened', 'round', roundId, `Sealed round open for ${windowS} s`, '', n.origin);
}

export interface PlaceBidArgs {
  id: string; roundId: string; persona: string; lines: Line[]; statedTotal: number; perks: string[]; claims: string[];
  origin: string; source: string;
}

export function placeBid(ctx: Ctx, a: PlaceBidArgs) {
  const me = sellerOf(ctx);
  if (!me) throw new SenderError('only a registered seller may bid');
  const r = ctx.db.round.id.find(a.roundId);
  if (!r) throw new SenderError(`no round ${a.roundId}`);
  if (ctx.db.bid.id.find(a.id)) throw new SenderError(`bid ${a.id} already exists`);
  for (const b of ctx.db.bid.roundId.filter(a.roundId)) if (b.sellerId === me.sellerId) throw new SenderError('one sealed bid per seller per round');
  const timing = tryBid(clockOf(r), ms(ctx.timestamp));
  if (!timing.accepted) throw new SenderError(timing.reason);

  const floors: Record<string, number> = {};
  for (const f of ctx.db.sellerFloor.sellerId.filter(me.sellerId)) floors[f.skuSpec] = f.floor;
  const fc = checkFloor({ lines: a.lines.map((l) => ({ sku_spec: l.skuSpec, unit_price: l.unitPrice, quantity: l.quantity })) }, floors);

  ctx.db.bid.insert({
    id: a.id, roundId: a.roundId, needId: r.needId, sellerId: me.sellerId, bidder: ctx.sender, persona: a.persona, lines: a.lines,
    statedTotal: a.statedTotal, perks: a.perks, claims: a.claims, floorCheckPassed: fc.ok, rejectReason: fc.ok ? '' : fc.reasons.join('; '),
    origin: a.origin, source: a.source, sealedAt: ctx.timestamp,
  });
  const deadline = tsFromMs(timing.auction.deadline_ms);
  ctx.db.round.id.update({ ...r, sealedCount: r.sealedCount + 1, extensions: timing.auction.extensions, deadline });
  if (timing.extended) scheduleClose(ctx, a.roundId, deadline);
  if (fc.ok) event(ctx, 'bid_sealed', 'bid', a.id, 'A sealed bid arrived', me.sellerId, a.origin);
  else event(ctx, 'bid_rejected', 'bid', a.id, 'Bid rejected: below this seller floor', me.sellerId, a.origin);
}

export function attachVerdict(ctx: Ctx, a: { bidId: string; verdict: string; ruleIds: string[]; origin: string }) {
  if (!['allow', 'quarantine', 'block'].includes(a.verdict)) throw new SenderError('verdict must be allow, quarantine or block');
  if (!ctx.db.bid.id.find(a.bidId)) throw new SenderError(`no bid ${a.bidId}`);
  ctx.db.bidCheck.insert({ id: 0n, bidId: a.bidId, kind: 'shield', result: a.verdict, detail: a.ruleIds.join(', '), evidenceUrl: '', origin: a.origin, at: ctx.timestamp });
  event(ctx, 'verdict', 'bid_check', a.bidId, `Bazaar Shield: ${a.verdict}`, '', a.origin);
}

export function attachClaimCheck(ctx: Ctx, a: { bidId: string; claim: string; check: string; evidenceUrl: string; origin: string }) {
  if (!['verified', 'unverified', 'false'].includes(a.check)) throw new SenderError('check must be verified, unverified or false');
  if (!ctx.db.bid.id.find(a.bidId)) throw new SenderError(`no bid ${a.bidId}`);
  ctx.db.bidCheck.insert({ id: 0n, bidId: a.bidId, kind: 'claim', result: a.check, detail: a.claim, evidenceUrl: a.evidenceUrl, origin: a.origin, at: ctx.timestamp });
  event(ctx, 'claim_checked', 'bid_check', a.bidId, `Claim check: ${a.check}`, '', a.origin);
}

type BidRow = ReturnType<Ctx["db"]["bid"]["iter"]> extends Iterable<infer R> ? R : never;

const toBid = (b: BidRow): Bid => ({
  id: b.id, need_id: b.needId, seller_id: b.sellerId, persona: b.persona,
  lines: b.lines.map((l: Line) => ({
    sku_spec: l.skuSpec, unit_price: l.unitPrice, quantity: l.quantity,
    ...(l.offeredSpec ? { offered_spec: l.offeredSpec } : {}),
    ...(l.offeredCondition ? { offered_condition: l.offeredCondition as Condition } : {}),
  })),
  total_landed_price: b.statedTotal, perks: b.perks, claims: b.claims, floor_check_passed: b.floorCheckPassed,
  mirror_snapshot_id: '', decision_trace: '', expires_at: '', origin: b.origin as Origin, source: b.source, sealed_at: ms(b.sealedAt),
});

export function closeRound(ctx: Ctx, { roundId }: { roundId: string }, { fromTimer = false } = {}) {
  const r = ctx.db.round.id.find(roundId);
  if (!r) throw new SenderError(`no round ${roundId}`);
  if (r.state === 'closed') {
    if (fromTimer) return;
    throw new SenderError('round already closed');
  }
  if (!isClosed(clockOf(r), ms(ctx.timestamp))) {
    if (fromTimer) return scheduleClose(ctx, roundId, r.deadline);
    throw new SenderError('round is still open until its deadline');
  }

  const needItems = new Map<string, NeedItem>();
  for (const i of ctx.db.needItem.needId.filter(r.needId)) {
    needItems.set(i.skuSpec, { sku_spec: i.skuSpec, condition: i.condition as Condition, variant: i.variant, quantity: i.quantity, unit: i.unit });
  }
  const rows = [...ctx.db.bid.roundId.filter(roundId)];
  const rejections = new Map<string, string[]>();
  const verified = new Map<string, number>();
  for (const b of rows) {
    const reasons: string[] = [];
    if (!b.floorCheckPassed) reasons.push('below this seller floor');
    for (const c of ctx.db.bidCheck.bidId.filter(b.id)) {
      if (c.kind === 'shield' && c.result !== 'allow') reasons.push(`Bazaar Shield ${c.result}: ${c.detail}`);
      if (c.kind === 'claim' && c.result === 'false') reasons.push(`claim did not match the page: ${c.detail}`);
      if (c.kind === 'claim' && c.result === 'verified') verified.set(b.id, (verified.get(b.id) ?? 0) + 1);
    }
    if (reasons.length) rejections.set(b.id, reasons);
  }
  // The seller fee is deliberately not passed: it never feeds ranking (invariant 8).
  const ranked = rankBids(rows.map(toBid), { needItems, rejections, verifiedClaims: (b) => verified.get(b.id) ?? 0 });
  const byId = new Map(rows.map((b) => [b.id, b]));
  for (const x of ranked.ranked) {
    const b = byId.get(x.bid.id)!;
    ctx.db.roundResult.insert({ id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: x.rank, landed: x.landed, reasons: [], lines: b.lines, origin: b.origin, source: b.source });
  }
  for (const d of ranked.disqualified) {
    const b = byId.get(d.bid.id)!;
    const landed = b.lines.reduce((s, l) => s + l.unitPrice * l.quantity, 0);
    ctx.db.roundResult.insert({ id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: 0, landed, reasons: d.reasons, lines: b.lines, origin: b.origin, source: b.source });
  }
  ctx.db.round.id.update({ ...r, state: 'closed', closedAt: ctx.timestamp });
  const top = ranked.ranked[0];
  event(ctx, 'auction_closed', 'round', roundId, top ? `Round closed: ${ranked.ranked.length} ranked, ${ranked.disqualified.length} out` : 'Round closed: no eligible bid', top?.bid.seller_id ?? '', r.origin);
}

// ---------------------------------------------------------------- mandate, approval, payment

/** MOCK until Vidyut's Mandate lands: same fields as the 00-shared shape. */
export function createMandate(
  ctx: Ctx,
  a: { hash: string; id: string; dealId: string; buyerId: string; amount: number; payee: string; expiryMinutes: number; nonce: string; origin: string },
) {
  if (ctx.db.mandate.hash.find(a.hash)) throw new SenderError('mandate hash already exists');
  ctx.db.mandate.insert({
    hash: a.hash, id: a.id, dealId: a.dealId, buyerId: a.buyerId, amount: a.amount, payee: a.payee,
    expiry: tsFromMs(ms(ctx.timestamp) + a.expiryMinutes * 60_000), nonce: a.nonce, origin: a.origin,
  });
  event(ctx, 'mandate_created', 'mandate', a.hash, 'Deal ready for approval', a.payee, a.origin);
}

export function recordApproval(ctx: Ctx, a: { mandateHash: string; method: string; approvedBy: string }) {
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  if (ms(ctx.timestamp) > ms(md.expiry)) throw new SenderError('mandate expired; the deal must be re-quoted');
  if (ctx.db.approval.mandateHash.find(a.mandateHash)) return rejected(ctx, 'approval', a.mandateHash, 'second approval for the same mandate refused');
  ctx.db.approval.insert({ id: 0n, mandateHash: a.mandateHash, method: a.method, approvedBy: a.approvedBy, at: ctx.timestamp });
  event(ctx, 'approval_recorded', 'approval', a.mandateHash, `Approved by ${a.method.replace('_', ' ')}`, md.payee, md.origin);
}

/** INVARIANT-1: no payment row without an approval row for the same mandate hash. */
export function recordPayment(ctx: Ctx, a: { mandateHash: string; paymentRef: string; amount: number }) {
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  const ap = ctx.db.approval.mandateHash.find(a.mandateHash);
  if (!ap) throw new SenderError('no approval row for this mandate hash; payment refused');
  if (a.amount !== md.amount) throw new SenderError('payment amount differs from the mandate amount');
  const auth = authorizePayment({ amount: a.amount, limit_checked: true, approval_id: String(ap.id) }, md.amount);
  if (!auth.ok) throw new SenderError(auth.reasons.join('; '));
  if (ctx.db.payment.mandateHash.find(a.mandateHash)) return rejected(ctx, 'payment', a.mandateHash, 'second payment for the same mandate refused');
  ctx.db.payment.insert({ id: 0n, mandateHash: a.mandateHash, paymentRef: a.paymentRef, amount: a.amount, at: ctx.timestamp });
  event(ctx, 'payment_recorded', 'payment', a.mandateHash, 'Payment recorded (Stripe test mode)', md.payee, 'SIM');
}

// ---------------------------------------------------------------- views

export function sellerNeedsView(ctx: VCtx | AVCtx) {
  const out: { roundId: string; needId: string; skuSpec: string; condition: string; variant: string; quantity: number; unit: string; deliveryWindow: string; deadline: Timestamp }[] = [];
  for (const r of ctx.db.round.iter()) {
    if (r.state !== 'open') continue;
    const n = ctx.db.need.id.find(r.needId);
    if (!n) continue;
    const items = [...ctx.db.needItem.needId.filter(n.id)].map((i) => ({ sku_spec: i.skuSpec, condition: i.condition as Condition, variant: i.variant, quantity: i.quantity, unit: i.unit }));
    const v = sellerView({ id: n.id, items, delivery_window: n.deliveryWindow }, '');
    for (const i of v.items) {
      out.push({ roundId: r.id, needId: v.need_id, skuSpec: i.sku_spec, condition: i.condition, variant: i.variant, quantity: i.quantity, unit: i.unit, deliveryWindow: v.delivery_window, deadline: r.deadline });
    }
  }
  return out;
}

export function myBidsView(ctx: VCtx) {
  return [...ctx.db.bid.iter()].filter((b) => b.bidder.isEqual(ctx.sender));
}

function myBuyerId(ctx: VCtx) {
  return ctx.db.buyerSession.identity.find(ctx.sender)?.buyerId;
}

export function myGoalsView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  return id ? [...ctx.db.goal.buyerId.filter(id)] : [];
}

export function myGoalItemsView(ctx: VCtx) {
  return myGoalsView(ctx).flatMap((g) => [...ctx.db.goalItem.goalId.filter(g.id)]);
}

export function myNotificationsView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  return id ? [...ctx.db.notification.buyerId.filter(id)] : [];
}
