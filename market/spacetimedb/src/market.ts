// Reducer and view bodies as plain functions over ctx, so tests call them directly through the
// module test harness. index.ts registers them. All market logic comes from market/rules, which
// the Convex fallback would call unchanged.
import { SenderError, type InferSchema, type ReducerCtx, type ViewCtx, type AnonymousViewCtx } from 'spacetimedb/server';
import { ScheduleAt, Timestamp, type Identity } from 'spacetimedb';
import type spacetimedb from './schema';
import { checkFloor, checkQuantity } from '../../rules/floor';
import { rankBids } from '../../rules/scoring';
import { DEFAULT_SEAL, isClosed, tryBid, type AuctionClock } from '../../rules/sealing';
import { sellerView } from '../../rules/redaction';
import { authorizePayment } from '../../rules/approval';
import { decide, raiseOnCleanReceiving, recordAutoSpend, requesterMayApprove, newAllowance, type Allowance, type Period } from '../../rules/allowance';
import type { Bid, Condition, NeedItem, Origin } from '../../rules/types';
import { resetDemo, seedDemo } from './demo';

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

// ---------------------------------------------------------------- identities and roles
// Every state-changing reducer calls requireRole first. One place decides who may act.

export type RoleName = 'buyer' | 'seller' | 'referee';
type Allowed = RoleName | 'owner' | 'scheduler';
const ROLES: RoleName[] = ['buyer', 'seller', 'referee'];

const roleOf = (ctx: { db: Ctx['db'] | VCtx['db']; sender: Identity }) => ctx.db.role.identity.find(ctx.sender);
const isOwner = (ctx: Ctx) => {
  const o = ctx.db.owner.id.find(0);
  return !!o && o.identity.isEqual(ctx.sender);
};

/**
 * Throws "not allowed" unless the caller holds one of the allowed roles. For buyer and seller
 * roles, `subjectId` (when given) must match the role's buyer_id or seller_id.
 */
export function requireRole(ctx: Ctx, what: string, allowed: Allowed[], subjectId?: string) {
  if (allowed.includes('owner') && isOwner(ctx)) return { role: 'owner', subjectId: '' };
  if (allowed.includes('scheduler') && ctx.sender.isEqual(ctx.identity)) return { role: 'scheduler', subjectId: '' };
  const r = roleOf(ctx);
  if (r && allowed.includes(r.role as RoleName)) {
    const bound = r.role === 'buyer' || r.role === 'seller';
    if (!bound || subjectId === undefined || r.subjectId === subjectId) return { role: r.role, subjectId: r.subjectId };
    throw new SenderError(`not allowed: ${what} for ${subjectId}; this ${r.role} acts only for ${r.subjectId}`);
  }
  throw new SenderError(`not allowed: ${what} needs ${allowed.join(' or ')}; caller is ${r ? `${r.role} ${r.subjectId}` : 'unregistered'}`);
}

/** Lifecycle: the publishing identity becomes the owner, once. */
export function init(ctx: Ctx) {
  if (!ctx.db.owner.id.find(0)) ctx.db.owner.insert({ id: 0, identity: ctx.sender });
}

export function assignRole(ctx: Ctx, a: { identity: Identity; role: string; subjectId: string }) {
  requireRole(ctx, 'assign_role', ['owner']);
  if (!ROLES.includes(a.role as RoleName)) throw new SenderError(`role must be one of ${ROLES.join(', ')}`);
  if (!a.subjectId) throw new SenderError('subject id required (buyer_id, seller_id, or a name for the referee)');
  const cur = ctx.db.role.identity.find(a.identity);
  if (cur) ctx.db.role.identity.update({ ...cur, role: a.role, subjectId: a.subjectId });
  else ctx.db.role.insert({ identity: a.identity, role: a.role, subjectId: a.subjectId });
}

export function setFloor(ctx: Ctx, { skuSpec, floor }: { skuSpec: string; floor: number }) {
  const me = requireRole(ctx, 'set_floor', ['seller']);
  for (const f of ctx.db.sellerFloor.sellerId.filter(me.subjectId)) if (f.skuSpec === skuSpec) ctx.db.sellerFloor.id.delete(f.id);
  ctx.db.sellerFloor.insert({ id: 0n, sellerId: me.subjectId, skuSpec, floor });
}

/** A browser screen takes the buyer role with the demo pairing code (SIM sign-in). */
export function pairBuyerScreen(ctx: Ctx, { buyerId, code }: { buyerId: string; code: string }) {
  const cur = roleOf(ctx);
  if (cur && cur.role !== 'buyer') throw new SenderError(`not allowed: a ${cur.role} cannot pair as a buyer screen`);
  const want = ctx.db.pairCode.buyerId.find(buyerId);
  if (!want || want.code !== code) throw new SenderError('wrong pairing code for this buyer');
  if (cur) ctx.db.role.identity.update({ ...cur, subjectId: buyerId });
  else ctx.db.role.insert({ identity: ctx.sender, role: 'buyer', subjectId: buyerId });
}

// ---------------------------------------------------------------- allowance (D's shape, rules/allowance)

type AllowanceRow = NonNullable<ReturnType<Ctx['db']['allowance']['buyerId']['find']>>;
const toRule = (r: AllowanceRow): Allowance => ({
  buyer_id: r.buyerId, currency: 'USD', per_purchase_limit: r.perPurchaseLimit, period_limit: r.periodLimit,
  period: r.period as Period, spent_this_period: r.spentThisPeriod, ladder_step: r.ladderStep, updated_at: ms(r.updatedAt),
});
const fromRule = (a: Allowance): AllowanceRow => ({
  buyerId: a.buyer_id, currency: a.currency, perPurchaseLimit: a.per_purchase_limit, periodLimit: a.period_limit,
  period: a.period, spentThisPeriod: a.spent_this_period, ladderStep: a.ladder_step, updatedAt: tsFromMs(a.updated_at),
});

function allowanceFor(ctx: Ctx, buyerId: string): Allowance {
  const row = ctx.db.allowance.buyerId.find(buyerId);
  if (row) return toRule(row);
  const fresh = newAllowance(buyerId, ms(ctx.timestamp));
  ctx.db.allowance.insert(fromRule(fresh));
  return fresh;
}

function saveAllowance(ctx: Ctx, a: Allowance) {
  if (ctx.db.allowance.buyerId.find(a.buyer_id)) ctx.db.allowance.buyerId.update(fromRule(a));
  else ctx.db.allowance.insert(fromRule(a));
}

// ---------------------------------------------------------------- needs and goals

export interface PostNeedArgs {
  id: string; buyerId: string; goalId: string; deliveryWindow: string; spendLimit: number; consent: boolean;
  auctionWindowS: number; origin: string;
  items: { skuSpec: string; condition: string; variant: string; quantity: number; unit: string }[];
}

export function postNeed(ctx: Ctx, a: PostNeedArgs) {
  requireRole(ctx, 'post_need', ['buyer'], a.buyerId);
  allowanceFor(ctx, a.buyerId);
  if (ctx.db.need.id.find(a.id)) throw new SenderError(`need ${a.id} already exists`);
  if (!a.items.length) throw new SenderError('a need has at least one item');
  ctx.db.need.insert({
    id: a.id, buyerId: a.buyerId, goalId: a.goalId, deliveryWindow: a.deliveryWindow, spendLimit: a.spendLimit,
    consent: a.consent, auctionWindowS: a.auctionWindowS, origin: a.origin, createdAt: ctx.timestamp,
  });
  for (const i of a.items) ctx.db.needItem.insert({ id: 0n, needId: a.id, ...i });
  event(ctx, 'need_posted', 'need', a.id, `New request: ${a.items.length} item(s)`, '', a.origin);
}

/** Lane A's Goal contract; deadline is an ISO datetime. */
export interface PostGoalArgs {
  id: string; buyerId: string; type: string; cap: number; deadline: string; poNumber: string; origin: string;
  items: { skuSpec: string; condition: string; variant: string; quantity: number; skippedOwnedPartId: string }[];
}

export const GOAL_TYPES = ['budget_cap', 'part_by_date', 'build_by_date'];

export function postGoal(ctx: Ctx, a: PostGoalArgs) {
  requireRole(ctx, 'post_goal', ['buyer'], a.buyerId);
  insertGoal(ctx, a);
}

/** No role check: callers are postGoal (gated) and seedDemo (gated). */
export function insertGoal(ctx: Ctx, a: PostGoalArgs) {
  if (!GOAL_TYPES.includes(a.type)) throw new SenderError(`goal type must be one of ${GOAL_TYPES.join(', ')}`);
  if (ctx.db.goal.id.find(a.id)) throw new SenderError(`goal ${a.id} already exists`);
  if (!(a.cap > 0)) throw new SenderError('goal cap must be positive');
  const deadlineMs = Date.parse(a.deadline);
  if (!/^\d{4}-\d{2}-\d{2}T/.test(a.deadline) || Number.isNaN(deadlineMs)) throw new SenderError('deadline must be an ISO datetime, for example 2026-10-30T23:59:00Z');
  for (const i of a.items) {
    if (!(Number.isFinite(i.quantity) && i.quantity > 0)) throw new SenderError(`goal item ${i.skuSpec}: quantity must be a number above 0`);
  }
  allowanceFor(ctx, a.buyerId);
  ctx.db.goal.insert({
    id: a.id, buyerId: a.buyerId, type: a.type, cap: a.cap, deadline: tsFromMs(deadlineMs), state: 'ACTIVE', reservedAmount: 0,
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
  requireRole(ctx, 'open_round', ['referee']);
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
  const me = { sellerId: requireRole(ctx, 'place_bid', ['seller']).subjectId };
  const r = ctx.db.round.id.find(a.roundId);
  if (!r) throw new SenderError(`no round ${a.roundId}`);
  const needQty = new Map([...ctx.db.needItem.needId.filter(r.needId)].map((i) => [i.skuSpec, i.quantity]));
  const q = checkQuantity(a.lines.map((l) => ({ sku_spec: l.skuSpec, quantity: l.quantity })), needQty);
  if (!q.ok) throw new SenderError(`bid refused: ${q.reasons.join('; ')}`);
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
  requireRole(ctx, 'attach_verdict', ['referee']);
  if (!['allow', 'quarantine', 'block'].includes(a.verdict)) throw new SenderError('verdict must be allow, quarantine or block');
  if (!ctx.db.bid.id.find(a.bidId)) throw new SenderError(`no bid ${a.bidId}`);
  ctx.db.bidCheck.insert({ id: 0n, bidId: a.bidId, kind: 'shield', result: a.verdict, detail: a.ruleIds.join(', '), evidenceUrl: '', origin: a.origin, at: ctx.timestamp });
  event(ctx, 'verdict', 'bid_check', a.bidId, `Bazaar Shield: ${a.verdict}`, '', a.origin);
}

export function attachClaimCheck(ctx: Ctx, a: { bidId: string; claim: string; check: string; evidenceUrl: string; origin: string }) {
  requireRole(ctx, 'attach_claim_check', ['referee']);
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

export function closeRound(ctx: Ctx, { roundId }: { roundId: string }) {
  requireRole(ctx, 'close_round', ['referee']);
  return closeRoundInner(ctx, roundId, false);
}

/** Body of the scheduled reducer: only the module itself (the scheduler) may run it. */
export function closeRoundOnDeadline(ctx: Ctx, roundId: string) {
  requireRole(ctx, 'close_round_on_deadline (the deadline scheduler)', ['scheduler']);
  return closeRoundInner(ctx, roundId, true);
}

function closeRoundInner(ctx: Ctx, roundId: string, fromTimer: boolean) {
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
  a: {
    hash: string; id: string; dealId: string; buyerId: string; amount: number; payee: string; expiryMinutes: number; nonce: string;
    requestedBy: string; origin: string;
  },
) {
  requireRole(ctx, 'create_mandate', ['buyer', 'referee'], a.buyerId);
  if (ctx.db.mandate.hash.find(a.hash)) throw new SenderError('mandate hash already exists');
  const allow = allowanceFor(ctx, a.buyerId);
  const d = decide(allow, a.amount, ms(ctx.timestamp));
  const within = d.path === 'auto';
  ctx.db.mandate.insert({
    hash: a.hash, id: a.id, dealId: a.dealId, buyerId: a.buyerId, amount: a.amount, payee: a.payee,
    expiry: tsFromMs(ms(ctx.timestamp) + a.expiryMinutes * 60_000), nonce: a.nonce, withinAllowance: within,
    requestedBy: a.requestedBy, origin: a.origin,
  });
  event(ctx, 'mandate_created', 'mandate', a.hash, within ? 'Deal within the allowance' : 'Deal needs the buyer call', a.payee, a.origin);
  if (within) {
    // Inside the allowance: approved by the buyer's own standing rule, with a receipt.
    ctx.db.approval.insert({ id: 0n, mandateHash: a.hash, method: 'allowance', approvedBy: a.buyerId, at: ctx.timestamp });
    saveAllowance(ctx, recordAutoSpend(allow, a.amount, ms(ctx.timestamp)));
    ctx.db.notification.insert({ id: 0n, buyerId: a.buyerId, goalId: '', klass: 'deal_found', text: `Bought within your allowance: ${d.reason}. Receipt for deal ${a.dealId}.`, push: false, at: ctx.timestamp });
    event(ctx, 'approval_recorded', 'approval', a.hash, 'Approved within the allowance', a.payee, a.origin);
  } else {
    ctx.db.notification.insert({ id: 0n, buyerId: a.buyerId, goalId: '', klass: 'state', text: `Call needed: ${d.reason}.`, push: true, at: ctx.timestamp });
  }
}

export function recordApproval(ctx: Ctx, a: { mandateHash: string; method: string; approvedBy: string }) {
  requireRole(ctx, 'record_approval', ['buyer', 'referee']);
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  // Only the mandate's own buyer, or the referee relaying that buyer's verified code.
  requireRole(ctx, 'record_approval', ['buyer', 'referee'], md.buyerId);
  if (a.approvedBy !== md.buyerId) throw new SenderError(`approvedBy must be the mandate's buyer (${md.buyerId})`);
  const sep = requesterMayApprove(md.requestedBy, a.approvedBy);
  if (!sep.ok) throw new SenderError(sep.reasons.join('; '));
  if (ms(ctx.timestamp) > ms(md.expiry)) throw new SenderError('mandate expired; the deal must be re-quoted');
  if (ctx.db.approval.mandateHash.find(a.mandateHash)) return rejected(ctx, 'approval', a.mandateHash, 'second approval for the same mandate refused');
  ctx.db.approval.insert({ id: 0n, mandateHash: a.mandateHash, method: a.method, approvedBy: a.approvedBy, at: ctx.timestamp });
  event(ctx, 'approval_recorded', 'approval', a.mandateHash, `Approved by ${a.method.replace('_', ' ')}`, md.payee, md.origin);
}

/** INVARIANT-1: no payment row without an approval row for the same mandate hash. */
export function recordPayment(ctx: Ctx, a: { mandateHash: string; paymentRef: string; amount: number }) {
  requireRole(ctx, 'record_payment', ['referee']);
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

// ---------------------------------------------------------------- receiving check

export interface RecordReceivingArgs {
  id: string; orderId: string; skuSpec: string; photoUrl: string; expectedSpecId: string; result: string;
  reasons: string[]; checkedBy: string; origin: string;
}

/** The buyer's own check at delivery. A clean one raises the allowance one step, once per deal. */
export function recordReceiving(ctx: Ctx, a: RecordReceivingArgs) {
  requireRole(ctx, 'record_receiving', ['buyer']);
  const md = ctx.db.mandate.hash.find(a.orderId);
  if (!md) throw new SenderError('no deal with that mandate hash');
  requireRole(ctx, 'record_receiving', ['buyer'], md.buyerId);
  if (!ctx.db.payment.mandateHash.find(a.orderId)) throw new SenderError('this deal is not paid, so there is nothing to receive');
  if (!['accepted', 'rejected'].includes(a.result)) throw new SenderError('result must be accepted or rejected');
  if (ctx.db.receivingEvent.id.find(a.id)) throw new SenderError(`receiving event ${a.id} already exists`);
  const clean = a.result === 'accepted';
  const alreadyRaised = [...ctx.db.receivingEvent.orderId.filter(a.orderId)].some((e) => e.raisedAllowance);
  const raise = clean && !alreadyRaised;
  ctx.db.receivingEvent.insert({
    id: a.id, orderId: a.orderId, skuSpec: a.skuSpec, photoUrl: a.photoUrl, expectedSpecId: a.expectedSpecId, result: a.result,
    reasons: a.reasons, creditRequestId: clean ? '' : `credit-${a.id}`, checkedBy: a.checkedBy, raisedAllowance: raise,
    origin: a.origin, at: ctx.timestamp,
  });
  event(ctx, 'delivery_checked', 'receiving_event', a.id, clean ? 'Delivery passed the receiving check' : 'Delivery failed the receiving check; credit requested', md.payee, a.origin);
  if (raise) {
    const next = raiseOnCleanReceiving(allowanceFor(ctx, md.buyerId), ms(ctx.timestamp));
    saveAllowance(ctx, next);
    ctx.db.notification.insert({ id: 0n, buyerId: md.buyerId, goalId: '', klass: 'progress', text: 'Clean delivery: your allowance went up one step.', push: false, at: ctx.timestamp });
    event(ctx, 'allowance_raised', 'allowance', md.buyerId, 'A buyer allowance went up one step', '', a.origin);
  }
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
  const r = roleOf(ctx);
  return r?.role === 'buyer' ? r.subjectId : undefined;
}

export function myRoleView(ctx: VCtx) {
  const r = roleOf(ctx);
  return r ? [r] : [];
}

export function myGoalsView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  return id ? [...ctx.db.goal.buyerId.filter(id)] : [];
}

export function myGoalItemsView(ctx: VCtx) {
  return myGoalsView(ctx).flatMap((g) => [...ctx.db.goalItem.goalId.filter(g.id)]);
}

export function myAllowanceView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  const row = id ? ctx.db.allowance.buyerId.find(id) : undefined;
  return row ? [row] : [];
}

export function myNotificationsView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  return id ? [...ctx.db.notification.buyerId.filter(id)] : [];
}

// ---------------------------------------------------------------- demo operator

export function resetDemoChecked(ctx: Ctx) {
  requireRole(ctx, 'reset_demo', ['owner', 'referee']);
  resetDemo(ctx);
}

export function seedDemoChecked(ctx: Ctx) {
  requireRole(ctx, 'seed_demo', ['owner', 'referee']);
  seedDemo(ctx);
}
