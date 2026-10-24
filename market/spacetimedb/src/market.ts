// Reducer and view bodies as plain functions over ctx, so tests call them directly through the
// module test harness. index.ts registers them. All market logic comes from market/rules, which
// the Convex fallback would call unchanged.
import { SenderError, type InferSchema, type ReducerCtx, type ViewCtx, type AnonymousViewCtx } from 'spacetimedb/server';
import { ScheduleAt, Timestamp, type Identity } from 'spacetimedb';
import type spacetimedb from './schema';
import { ANY_CONDITION, checkFloorByCondition } from '../../rules/floor';
import { rankBids } from '../../rules/scoring';
import { MARKET_CONFIG } from '../../config';
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

export function sha256(text: string): string {
  const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const encoded: number[] = [];
  for (const character of text) {
    const cp = character.codePointAt(0)!;
    if (cp < 0x80) encoded.push(cp);
    else if (cp < 0x800) encoded.push(0xc0 | (cp >> 6), 0x80 | (cp & 0x3f));
    else if (cp < 0x10000) encoded.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
    else encoded.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
  }
  const bytes = [...encoded, 0x80];
  while (bytes.length % 64 !== 56) bytes.push(0);
  const bits = BigInt(encoded.length) * 8n;
  for (let i = 7; i >= 0; i--) bytes.push(Number((bits >> BigInt(i * 8)) & 255n));
  const h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let offset = 0; offset < bytes.length; offset += 64) {
    const w = new Array<number>(64);
    for (let i = 0; i < 16; i++) w[i] = ((bytes[offset + i * 4]! << 24) | (bytes[offset + i * 4 + 1]! << 16) | (bytes[offset + i * 4 + 2]! << 8) | bytes[offset + i * 4 + 3]!) >>> 0;
    for (let i = 16; i < 64; i++) { const a = w[i - 15]!, b = w[i - 2]!; w[i] = (w[i - 16]! + (rotr(a,7) ^ rotr(a,18) ^ (a >>> 3)) + w[i - 7]! + (rotr(b,17) ^ rotr(b,19) ^ (b >>> 10))) >>> 0; }
    let [a,b,c,d,e,f,g,hh] = h;
    for (let i = 0; i < 64; i++) { const t1 = (hh! + (rotr(e!,6) ^ rotr(e!,11) ^ rotr(e!,25)) + ((e! & f!) ^ (~e! & g!)) + K[i]! + w[i]!) >>> 0; const t2 = ((rotr(a!,2) ^ rotr(a!,13) ^ rotr(a!,22)) + ((a! & b!) ^ (a! & c!) ^ (b! & c!))) >>> 0; [hh,g,f,e,d,c,b,a] = [g!,f!,e!, (d! + t1) >>> 0,c!,b!,a!, (t1 + t2) >>> 0]; }
    [a,b,c,d,e,f,g,hh].forEach((v, i) => { h[i] = (h[i]! + v!) >>> 0; });
  }
  return h.map((v) => v.toString(16).padStart(8, '0')).join('');
}

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

// seller_screen: a browser paired to one seller's own screen. Read-only: no reducer allows it.
export type RoleName = 'buyer' | 'seller' | 'referee' | 'seller_screen';
type Allowed = RoleName | 'owner' | 'scheduler';
const ROLES: RoleName[] = ['buyer', 'seller', 'referee', 'seller_screen'];

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

const CONDITIONS = ['new', 'open-box', 'refurbished', 'used'];

/** A seller's floor for every condition of one SKU (the original call; the Lane D bridge uses it). */
export function setFloor(ctx: Ctx, { skuSpec, floor }: { skuSpec: string; floor: number }) {
  writeFloor(ctx, 'set_floor', skuSpec, ANY_CONDITION, floor);
}

/** A seller's floor for one (sku_spec, condition); it wins over a floor set for any condition. */
export function setFloorForCondition(ctx: Ctx, { skuSpec, condition, floor }: { skuSpec: string; condition: string; floor: number }) {
  if (!CONDITIONS.includes(condition)) throw new SenderError(`condition must be one of ${CONDITIONS.join(', ')}`);
  writeFloor(ctx, 'set_floor_for_condition', skuSpec, condition, floor);
}

function writeFloor(ctx: Ctx, what: string, skuSpec: string, condition: string, floor: number) {
  const me = requireRole(ctx, what, ['seller']);
  if (!(Number.isFinite(floor) && floor > 0)) throw new SenderError('floor must be a positive number');
  for (const f of ctx.db.sellerFloor.sellerId.filter(me.subjectId)) {
    if (f.skuSpec === skuSpec && f.condition === condition) ctx.db.sellerFloor.id.delete(f.id);
  }
  ctx.db.sellerFloor.insert({ id: 0n, sellerId: me.subjectId, skuSpec, floor, condition });
}

export const PAIR_MAX_FAILURES = 5;
export const REVIEW_WINDOW_MS = 20_000;

/**
 * A browser screen takes the buyer role with the demo pairing code (SIM sign-in). A wrong code returns { paired: false } without throwing, so the failure is counted (a throw would
 * roll the count back). 5 failures lock the code, and 5 failures lock the caller across every code.
 * The code itself never appears in a message.
 */
export function pairBuyerScreen(ctx: Ctx, { buyerId, code }: { buyerId: string; code: string }) {
  const cur = roleOf(ctx);
  if (cur && cur.role !== 'buyer') throw new SenderError(`not allowed: a ${cur.role} cannot pair as a buyer screen`);
  return pairWithCode(ctx, buyerId, code, 'buyer', buyerId);
}

/** A browser screen takes the read-only seller_screen role for one seller with that seller's code. Same limits as the buyer pairing. */
export function pairSellerScreen(ctx: Ctx, { sellerId, code }: { sellerId: string; code: string }) {
  const cur = roleOf(ctx);
  if (cur && cur.role !== 'seller_screen') throw new SenderError(`not allowed: a ${cur.role} cannot pair as a seller screen`);
  return pairWithCode(ctx, sellerScreenKey(sellerId), code, 'seller_screen', sellerId);
}

const sellerScreenKey = (sellerId: string) => `seller:${sellerId}`;

function pairWithCode(ctx: Ctx, key: string, code: string, role: RoleName, subjectId: string) {
  const cur = roleOf(ctx);
  const want = ctx.db.pairCode.buyerId.find(key);
  if (!want) throw new SenderError('no pairing code issued for this screen; ask the operator');
  if (want.locked) throw new SenderError('pairing is locked after too many wrong codes; ask the operator for a new code');
  const mine = ctx.db.pairAttempt.identity.find(ctx.sender);
  if (mine && mine.failures >= PAIR_MAX_FAILURES) throw new SenderError('this screen is locked after too many wrong codes; ask the operator');
  if (want.code !== code) {
    const failed = want.failedAttempts + 1;
    ctx.db.pairCode.buyerId.update({ ...want, failedAttempts: failed, locked: failed >= PAIR_MAX_FAILURES });
    if (mine) ctx.db.pairAttempt.identity.update({ ...mine, failures: mine.failures + 1 });
    else ctx.db.pairAttempt.insert({ identity: ctx.sender, failures: 1 });
    if (failed >= PAIR_MAX_FAILURES) event(ctx, 'pairing_locked', 'pair_code', key, 'Screen pairing locked after too many wrong codes');
    return { paired: false, reason: 'wrong pairing code' };
  }
  if (cur) ctx.db.role.identity.update({ ...cur, subjectId });
  else ctx.db.role.insert({ identity: ctx.sender, role, subjectId });
  return { paired: true, reason: '' };
}

/** Owner only: a fresh code for this buyer, unlocked, with its counter reset. It also clears every screen's lock (pair_attempt is keyed by identity only): the operator unlocks. */
export function reissuePairCode(ctx: Ctx, { buyerId }: { buyerId: string }) {
  requireRole(ctx, 'reissue_pair_code', ['owner']);
  issuePairCode(ctx, buyerId);
  for (const row of [...ctx.db.pairAttempt.iter()]) ctx.db.pairAttempt.identity.delete(row.identity);
}

/** Owner only: a fresh code for one seller's screen (stored under "seller:<id>"), with every screen lock cleared. */
export function reissueSellerScreenCode(ctx: Ctx, { sellerId }: { sellerId: string }) {
  requireRole(ctx, 'reissue_seller_screen_code', ['owner']);
  issuePairCode(ctx, sellerScreenKey(sellerId));
  for (const row of [...ctx.db.pairAttempt.iter()]) ctx.db.pairAttempt.identity.delete(row.identity);
}

export function issuePairCode(ctx: Ctx, buyerId: string) {
  const code = String(ctx.random.integerInRange(100000, 999999));
  const cur = ctx.db.pairCode.buyerId.find(buyerId);
  if (cur) ctx.db.pairCode.buyerId.update({ buyerId, code, failedAttempts: 0, locked: false });
  else ctx.db.pairCode.insert({ buyerId, code, failedAttempts: 0, locked: false });
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
  items: { skuSpec: string; condition: string; allowedConditions: string[]; variant: string; quantity: number; unit: string }[];
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
  if (!(Number.isFinite(a.cap) && a.cap > 0)) throw new SenderError('goal cap must be a finite positive number');
  const deadlineMs = Date.parse(a.deadline);
  if (!/^\d{4}-\d{2}-\d{2}T/.test(a.deadline) || Number.isNaN(deadlineMs)) throw new SenderError('deadline must be an ISO datetime, for example 2026-10-30T23:59:00Z');
  for (const i of a.items) {
    if (!(Number.isFinite(i.quantity) && i.quantity > 0)) throw new SenderError(`goal item ${i.skuSpec}: quantity must be a number above 0`);
  }
  allowanceFor(ctx, a.buyerId);
  ctx.db.goal.insert({
    id: a.id, buyerId: a.buyerId, type: a.type, cap: a.cap, deadline: tsFromMs(deadlineMs), state: 'ACTIVE', reservedAmount: 0,
    reservedDealId: '', reservedMandateHash: '',
    poNumber: a.poNumber, origin: a.origin, createdAt: ctx.timestamp,
  });
  for (const i of a.items) ctx.db.goalItem.insert({ id: 0n, goalId: a.id, ...i });
  ctx.db.notification.insert({ id: 0n, buyerId: a.buyerId, goalId: a.id, klass: 'state', text: 'Goal set. The agent is hunting.', push: false, at: ctx.timestamp });
  event(ctx, 'goal_posted', 'goal', a.id, 'A buyer set a goal', '', a.origin);
}

const GOAL_STATES = ['ACTIVE', 'HUNTING', 'HOLD_FOR_CALL', 'PAUSED', 'EXPIRED'];
const STEP_CLASSES = ['state', 'progress to goal', 'deal found', 'bid in', 'veto', 'payment'];

export function setGoalState(ctx: Ctx, a: { goalId: string; state: string; reservedAmount: number }) {
  const buyerId = requireRole(ctx, 'set_goal_state', ['buyer']).subjectId;
  const g = ctx.db.goal.id.find(a.goalId);
  if (!g || g.buyerId !== buyerId) throw new SenderError('no goal for this buyer');
  if (!GOAL_STATES.includes(a.state)) throw new SenderError(`goal state must be one of ${GOAL_STATES.join(', ')}`);
  if (!(Number.isFinite(a.reservedAmount) && a.reservedAmount >= 0 && a.reservedAmount <= g.cap)) throw new SenderError('reserved amount must be between zero and the goal cap');
  if (a.reservedAmount > 0 && (g.reservedAmount !== a.reservedAmount || !g.reservedDealId || !g.reservedMandateHash)) {
    throw new SenderError('a reservation must be bound to a deal and mandate');
  }
  if (a.reservedAmount === 0 && g.reservedAmount > 0) throw new SenderError('use release_goal_reservation for an active hold');
  if (g.state === 'DONE' || g.state === 'EXPIRED') throw new SenderError(`goal is ${g.state.toLowerCase()} and cannot change`);
  if (a.state === 'HOLD_FOR_CALL' && a.reservedAmount <= 0) throw new SenderError('a call hold needs a positive reservation');
  if (a.reservedAmount > 0) {
    const other = [...ctx.db.goal.buyerId.filter(buyerId)].find((x) => x.id !== g.id && x.reservedAmount > 0);
    if (other) throw new SenderError('this buyer already has an active deal reservation');
  }
  ctx.db.goal.id.update({ ...g, state: a.state, reservedAmount: a.reservedAmount });
}

function reserveGoalInner(ctx: Ctx, goalId: string, dealId: string, mandateHash: string, amount: number) {
  const g = ctx.db.goal.id.find(goalId);
  if (!g) throw new SenderError('no goal for this buyer');
  if (!(Number.isFinite(amount) && amount > 0 && amount <= g.cap)) throw new SenderError('reservation amount must be finite, positive, and within the goal cap');
  if (!dealId || !mandateHash) throw new SenderError('reservation needs a deal ID and mandate hash');
  if (g.state === 'DONE' || g.state === 'EXPIRED' || g.state === 'PAUSED' || ms(ctx.timestamp) > ms(g.deadline)) throw new SenderError('goal cannot accept a new deal');
  if (g.reservedAmount > 0) {
    if (g.reservedAmount === amount && g.reservedDealId === dealId && g.reservedMandateHash === mandateHash) return g;
    throw new SenderError('goal already has an active deal reservation');
  }
  const other = [...ctx.db.goal.buyerId.filter(g.buyerId)].find((x) => x.id !== g.id && x.reservedAmount > 0);
  if (other) throw new SenderError('this buyer already has an active deal reservation');
  return ctx.db.goal.id.update({ ...g, reservedAmount: amount, reservedDealId: dealId, reservedMandateHash: mandateHash });
}

export function reserveGoal(ctx: Ctx, a: { goalId: string; dealId: string; mandateHash: string; amount: number }) {
  const g = ctx.db.goal.id.find(a.goalId);
  if (!g) throw new SenderError('no goal for this buyer');
  requireRole(ctx, 'reserve_goal', ['buyer', 'referee'], g.buyerId);
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md || md.goalId !== a.goalId || md.dealId !== a.dealId || md.buyerId !== g.buyerId || md.amount !== a.amount) {
    throw new SenderError('reservation must match an existing exact mandate');
  }
  reserveGoalInner(ctx, a.goalId, a.dealId, a.mandateHash, a.amount);
}

export function releaseGoalReservation(ctx: Ctx, a: { goalId: string; dealId: string; mandateHash: string }) {
  const g = ctx.db.goal.id.find(a.goalId);
  if (!g) throw new SenderError('no goal for this buyer');
  requireRole(ctx, 'release_goal_reservation', ['buyer', 'referee'], g.buyerId);
  if (g.reservedDealId !== a.dealId || g.reservedMandateHash !== a.mandateHash || g.reservedAmount <= 0) throw new SenderError('reservation identity does not match');
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md || md.goalId !== a.goalId || md.dealId !== a.dealId || ms(ctx.timestamp) <= ms(md.expiry)) throw new SenderError('only an expired mandate may release its reservation');
  if (ctx.db.approval.mandateHash.find(a.mandateHash) || ctx.db.payment.mandateHash.find(a.mandateHash)) throw new SenderError('approved or charged deal holds cannot be released');
  ctx.db.goal.id.update({ ...g, state: 'HUNTING', reservedAmount: 0, reservedDealId: '', reservedMandateHash: '' });
}

export function recordStepEvent(ctx: Ctx, a: { stableId: string; goalId: string; klass: string; text: string; origin: string }) {
  const buyerId = requireRole(ctx, 'record_step_event', ['buyer']).subjectId;
  const g = ctx.db.goal.id.find(a.goalId);
  if (!g || g.buyerId !== buyerId) throw new SenderError('no goal for this buyer');
  if (!a.stableId || a.stableId.length > 128) throw new SenderError('stable event id must be 1 to 128 characters');
  if (!STEP_CLASSES.includes(a.klass)) throw new SenderError(`event class must be one of ${STEP_CLASSES.join(', ')}`);
  if (!a.text || a.text.length > 500) throw new SenderError('event text must be 1 to 500 characters');
  const old = ctx.db.goalStepEvent.stableId.find(a.stableId);
  if (old) {
    if (old.goalId !== a.goalId || old.buyerId !== buyerId || old.klass !== a.klass || old.text !== a.text) throw new SenderError('stable event id was already used for different content');
    return;
  }
  ctx.db.goalStepEvent.insert({ stableId: a.stableId, buyerId, goalId: a.goalId, klass: a.klass, text: a.text, origin: a.origin, at: ctx.timestamp });
}

/** Only an authenticated buyer acknowledgement after an existing exact payment can settle a goal. */
export function settleGoal(ctx: Ctx, a: { goalId: string; dealId: string; mandateHash: string; paymentRef: string }) {
  const buyerId = requireRole(ctx, 'settle_goal', ['buyer']).subjectId;
  const g = ctx.db.goal.id.find(a.goalId);
  if (!g || g.buyerId !== buyerId) throw new SenderError('no goal for this buyer');
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md || md.dealId !== a.dealId || md.goalId !== a.goalId || md.buyerId !== buyerId) throw new SenderError('no matching mandate for this goal and deal');
  const payment = ctx.db.payment.mandateHash.find(md.hash);
  if (!payment || payment.paymentRef !== a.paymentRef || payment.amount !== md.amount) throw new SenderError('goal settlement needs the exact recorded payment');
  if (g.state === 'DONE') {
    if (g.poNumber === a.dealId) return;
    throw new SenderError('goal was already settled to a different deal');
  }
  if (g.reservedDealId !== a.dealId || g.reservedMandateHash !== a.mandateHash || g.reservedAmount !== md.amount) throw new SenderError('payment does not match the active reservation');
  const requested = [...ctx.db.goalItem.goalId.filter(g.id)].filter((i) => !i.skippedOwnedPartId).map((i) => `${i.skuSpec}|${i.quantity}`).sort();
  const need = md.needId ? ctx.db.need.id.find(md.needId) : undefined;
  if (!need || need.goalId !== g.id || need.buyerId !== buyerId) throw new SenderError('settlement need is not bound to this complete goal');
  const covered = [...ctx.db.needItem.needId.filter(md.needId)].map((i) => `${i.skuSpec}|${i.quantity}`).sort();
  if (requested.length !== covered.length || requested.some((x, i) => x !== covered[i])) throw new SenderError('a partial deal cannot complete the parent goal');
  ctx.db.goal.id.update({ ...g, state: 'DONE', reservedAmount: 0, reservedDealId: '', reservedMandateHash: '', poNumber: a.dealId });
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
  ctx.db.round.insert({ id: roundId, needId, openedAt: ctx.timestamp, deadline, extensions: 0, state: 'open', sealedCount: 0, closedAt: undefined, origin: n.origin, reviewDeadline: undefined });
  scheduleClose(ctx, roundId, deadline);
  event(ctx, 'round_opened', 'round', roundId, `Sealed round open for ${windowS} s`, '', n.origin);
}

export interface PlaceBidArgs {
  id: string; roundId: string; persona: string; lines: Line[]; statedTotal: number; perks: string[]; claims: string[];
  origin: string; source: string;
}

type LineMeta = {
  lineIndex: number;
  shipping: number;
  listingId: string;
  listingHash: string;
  source: string;
  snapshotId: string;
  provenance: Record<string, unknown>;
  attrs: Record<string, unknown>;
};

const META_KEYS = ['lineIndex', 'shipping', 'listingId', 'listingHash', 'source', 'snapshotId', 'provenance', 'attrs'];

function parseLineMeta(raw: string, lineCount: number): { rows?: LineMeta[]; reason?: string } {
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return { reason: 'line metadata is invalid JSON' }; }
  if (!Array.isArray(value) || value.length !== lineCount) return { reason: 'line metadata must cover every original bid line exactly once' };
  const seen = new Set<number>();
  for (const item of value) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return { reason: 'line metadata entry must be an object' };
    const row = item as Record<string, unknown>;
    if (Object.keys(row).length !== META_KEYS.length || Object.keys(row).some((key) => !META_KEYS.includes(key))) {
      return { reason: 'line metadata contains missing or unsupported fields' };
    }
    if (!Number.isInteger(row.lineIndex) || (row.lineIndex as number) < 0 || (row.lineIndex as number) >= lineCount || seen.has(row.lineIndex as number)) {
      return { reason: 'line metadata indexes must match distinct original line indexes' };
    }
    if (!(Number.isFinite(row.shipping) && (row.shipping as number) >= 0)) return { reason: 'shipping must be finite and nonnegative' };
    if (typeof row.listingId !== 'string' || !row.listingId.trim() || row.listingId.length > 512) return { reason: 'listingId must be a bounded nonempty string' };
    if (typeof row.listingHash !== 'string' || !/^[a-f0-9]{64}$/.test(row.listingHash)) return { reason: 'listingHash must be a lowercase SHA-256 hex digest' };
    if (typeof row.source !== 'string' || !row.source.trim() || row.source.length > 512) return { reason: 'source must be a bounded nonempty string' };
    if (typeof row.snapshotId !== 'string' || row.snapshotId.length > 256) return { reason: 'snapshotId must be a bounded string' };
    if (!row.provenance || typeof row.provenance !== 'object' || Array.isArray(row.provenance)
        || !row.attrs || typeof row.attrs !== 'object' || Array.isArray(row.attrs)) return { reason: 'provenance and attrs must be objects' };
    const safeScalar = (val: unknown) => val === null || typeof val === 'boolean'
      || (typeof val === 'number' && Number.isFinite(val))
      || (typeof val === 'string' && val.length <= 512);
    const safeObject = (obj: Record<string, unknown>) => Object.entries(obj).every(([key, val]) =>
      key.length > 0 && key.length <= 64 && (safeScalar(val)
        || (Array.isArray(val) && val.length <= 32 && val.every((item) => safeScalar(item)
          && (typeof item !== 'string' || item.length <= 128)))));
    if (!safeObject(row.provenance as Record<string, unknown>) || !safeObject(row.attrs as Record<string, unknown>)) {
      return { reason: 'provenance or attrs contains an unsupported value' };
    }
    seen.add(row.lineIndex as number);
  }
  const canonicalObject = (obj: Record<string, unknown>) => Object.fromEntries(
    Object.entries(obj).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
  );
  const rows = value.map((item) => {
    const row = item as LineMeta;
    return {
      lineIndex: row.lineIndex, shipping: row.shipping, listingId: row.listingId, listingHash: row.listingHash,
      source: row.source, snapshotId: row.snapshotId,
      provenance: canonicalObject(row.provenance), attrs: canonicalObject(row.attrs),
    };
  }).sort((a, b) => a.lineIndex - b.lineIndex);
  return { rows };
}

/** Seller-owned, append-only metadata step. A bid without this complete metadata remains ineligible. */
export function setBidLineMeta(ctx: Ctx, { bidId, lineMetaJson }: { bidId: string; lineMetaJson: string }) {
  const sellerId = requireRole(ctx, 'set_bid_line_meta', ['seller']).subjectId;
  const b = ctx.db.bid.id.find(bidId);
  if (!b || b.sellerId !== sellerId) throw new SenderError('no bid for this seller');
  if (lineMetaJson.length > 32_000) throw new SenderError('line metadata is too large');
  const checked = parseLineMeta(lineMetaJson, b.lines.length);
  if (!checked.rows) throw new SenderError(checked.reason ?? 'line metadata is invalid');
  const canonical = JSON.stringify(checked.rows);
  const current = b.lineMetaJson || '[]';
  if (current !== '[]') {
    if (current === canonical) return;
    throw new SenderError('line metadata is immutable once written');
  }
  const r = ctx.db.round.id.find(b.roundId);
  if (!r || r.state !== 'open' || isClosed(clockOf(r), ms(ctx.timestamp))) throw new SenderError('line metadata must be written while bidding is open');
  ctx.db.bid.id.update({ ...b, lineMetaJson: canonical });
}

export function placeBid(ctx: Ctx, a: PlaceBidArgs) {
  const me = { sellerId: requireRole(ctx, 'place_bid', ['seller']).subjectId };
  const r = ctx.db.round.id.find(a.roundId);
  if (!r) throw new SenderError(`no round ${a.roundId}`);
  if (r.state !== 'open') throw new SenderError(`round is ${r.state}; bids are closed`);
  if (!a.lines.length) throw new SenderError('a bid has at least one line');
  const needCond = new Map([...ctx.db.needItem.needId.filter(r.needId)].map((i) => [i.skuSpec, i.condition]));
  const condOf = (sku: string, offered: string) => offered || needCond.get(sku) || 'new';
  for (const l of a.lines) {
    // A seller has one sealed bid per round, so a line for a SKU the need does not have is refused here, not at close.
    if (!needCond.has(l.skuSpec)) throw new SenderError(`bid refused: ${l.skuSpec}: not part of this need`);
    // A line's quantity is its stock (qty_available): a finite number above 0. Whether it covers the
    // need is decided at close, per line, so a short line just cannot be picked.
    if (!(Number.isFinite(l.quantity) && l.quantity > 0)) {
      throw new SenderError(`bid refused: ${l.skuSpec} ${condOf(l.skuSpec, l.offeredCondition)}: qty_available ${l.quantity} is not a number above 0`);
    }
  }
  if (ctx.db.bid.id.find(a.id)) throw new SenderError(`bid ${a.id} already exists`);
  for (const b of ctx.db.bid.roundId.filter(a.roundId)) if (b.sellerId === me.sellerId) throw new SenderError('one sealed bid per seller per round');
  const timing = tryBid(clockOf(r), ms(ctx.timestamp));
  if (!timing.accepted) throw new SenderError(timing.reason);

  const floors = new Map<string, number>();
  for (const f of ctx.db.sellerFloor.sellerId.filter(me.sellerId)) floors.set(`${f.skuSpec}|${f.condition}`, f.floor);
  const fc = checkFloorByCondition(
    a.lines.map((l) => ({ sku_spec: l.skuSpec, unit_price: l.unitPrice, quantity: l.quantity, offered_condition: (l.offeredCondition || undefined) as Condition | undefined })),
    floors,
    (l) => condOf(l.sku_spec, l.offered_condition ?? ''),
  );

  ctx.db.bid.insert({
    id: a.id, roundId: a.roundId, needId: r.needId, sellerId: me.sellerId, bidder: ctx.sender, persona: a.persona, lines: a.lines,
    statedTotal: a.statedTotal, perks: a.perks, claims: a.claims, floorCheckPassed: fc.ok, rejectReason: fc.ok ? '' : fc.reasons.join('; '),
    origin: a.origin, source: a.source, sealedAt: ctx.timestamp, lineRejects: fc.lineRejects, lineMetaJson: '[]',
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
  const b = ctx.db.bid.id.find(a.bidId);
  if (!b) throw new SenderError(`no bid ${a.bidId}`);
  const round = ctx.db.round.id.find(b.roundId);
  if (round?.state === 'closed') throw new SenderError('round already closed');
  if (!round || round.state !== 'review' || !round.reviewDeadline || ms(ctx.timestamp) >= ms(round.reviewDeadline)) throw new SenderError('Shield verdicts are accepted only during review');
  ctx.db.bidCheck.insert({ id: 0n, bidId: a.bidId, kind: 'shield', result: a.verdict, detail: a.ruleIds.join(', '), evidenceUrl: '', origin: a.origin, at: ctx.timestamp, bindingJson: '' });
  event(ctx, 'verdict', 'bid_check', a.bidId, `Bazaar Shield: ${a.verdict}`, '', a.origin);
}

export function attachClaimCheck(ctx: Ctx, a: { bidId: string; claim: string; check: string; evidenceUrl: string; origin: string; bindingHash: string; lineIndex: number; listingId: string; listingHash: string }) {
  requireRole(ctx, 'attach_claim_check', ['referee']);
  if (!['verified', 'unverified', 'false'].includes(a.check)) throw new SenderError('check must be verified, unverified or false');
  const b = ctx.db.bid.id.find(a.bidId);
  if (!b) throw new SenderError(`no bid ${a.bidId}`);
  const round = ctx.db.round.id.find(b.roundId);
  if (round?.state === 'closed') throw new SenderError('round already closed');
  if (!round || round.state !== 'review' || !round.reviewDeadline || ms(ctx.timestamp) >= ms(round.reviewDeadline)) throw new SenderError('claim checks are accepted only during review');
  if (!/^[a-f0-9]{64}$/.test(a.bindingHash)) throw new SenderError('claim check needs the current candidate SHA-256 binding');
  const metadata = parseLineMeta(b.lineMetaJson || '[]', b.lines.length).rows;
  const selected = metadata?.[a.lineIndex];
  if (!selected || selected.lineIndex !== a.lineIndex || selected.listingId !== a.listingId || selected.listingHash !== a.listingHash) {
    throw new SenderError('claim evidence must bind an exact original listing and line index');
  }
  ctx.db.bidCheck.insert({ id: 0n, bidId: a.bidId, kind: 'claim', result: a.check, detail: a.claim, evidenceUrl: a.evidenceUrl, origin: a.origin, at: ctx.timestamp,
    bindingJson: JSON.stringify({ bindingHash: a.bindingHash, lineIndex: a.lineIndex, listingId: a.listingId, listingHash: a.listingHash }) });
  event(ctx, 'claim_checked', 'bid_check', a.bidId, `Claim check: ${a.check}`, '', a.origin);
}

export const ADVOCATE_RECOMMENDATIONS = ['buy', 'caution', 'veto'];
export const SAME_SELLER_REASON = {
  rule_id: 'advocate.same_seller',
  summary: 'This seller shares trusted identity evidence with a higher-ranked seller',
  source_url: 'https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/same_seller.py',
} as const;

/**
 * The advocate relay (referee) attaches Lane A's card for one bid. A veto disqualifies the bid in the
 * round result with the rule, the text and the cited source; the buyer's feed gets a veto line. The
 * public floor event names the rule only: never the seller, the text or a price.
 */
export function attachAdvocateCard(
  ctx: Ctx,
  a: { bidId: string; recommendation: string; ruleId: string; text: string; sourceUrl: string; origin: string; bindingHash: string },
) {
  requireRole(ctx, 'attach_advocate_card', ['referee']);
  if (!ADVOCATE_RECOMMENDATIONS.includes(a.recommendation)) throw new SenderError(`recommendation must be one of ${ADVOCATE_RECOMMENDATIONS.join(', ')}`);
  const b = ctx.db.bid.id.find(a.bidId);
  if (!b) throw new SenderError(`no bid ${a.bidId}`);
  const round = ctx.db.round.id.find(b.roundId);
  if (round?.state === 'closed') throw new SenderError('round already closed');
  if (!round || round.state !== 'review' || !round.reviewDeadline || ms(ctx.timestamp) >= ms(round.reviewDeadline)) throw new SenderError('AdvocateCards are accepted only during review');
  if (!/^[a-f0-9]{64}$/.test(a.bindingHash)) throw new SenderError('AdvocateCard needs the current candidate SHA-256 binding');
  const veto = a.recommendation === 'veto';
  if (veto && !a.sourceUrl) throw new SenderError('an advocate veto must cite a source');
  if (veto && (!a.ruleId || !a.text)) throw new SenderError('an advocate veto needs a rule id and a text');
  if (ctx.db.round.id.find(b.roundId)?.state === 'closed') throw new SenderError('round already closed; a card can no longer change its ranking');
  ctx.db.bidCheck.insert({
    id: 0n, bidId: a.bidId, kind: 'advocate', result: a.recommendation, detail: `${a.ruleId}: ${a.text}`, evidenceUrl: a.sourceUrl,
    origin: a.origin, at: ctx.timestamp, bindingJson: JSON.stringify({ bindingHash: a.bindingHash }),
  });
  event(ctx, 'advocate_card', 'bid_check', a.bidId, veto ? `Advocate veto (${a.ruleId})` : `Advocate: ${a.recommendation}`, '', a.origin);
  if (veto) {
    const n = ctx.db.need.id.find(b.needId);
    if (n) {
      ctx.db.notification.insert({
        id: 0n, buyerId: n.buyerId, goalId: n.goalId, klass: 'veto',
        text: `Your advocate vetoed ${b.persona}: ${a.text} (${a.ruleId}). Source: ${a.sourceUrl}`, push: false, at: ctx.timestamp,
      });
    }
  }
}

type BidRow = ReturnType<Ctx["db"]["bid"]["iter"]> extends Iterable<infer R> ? R : never;

const toBid = (b: BidRow, metadata: LineMeta[] | undefined = []): Bid => ({
  id: b.id, need_id: b.needId, seller_id: b.sellerId, persona: b.persona,
  lines: b.lines.map((l: Line, i: number) => ({
    sku_spec: l.skuSpec, unit_price: l.unitPrice, quantity: l.quantity,
    ...(l.offeredSpec ? { offered_spec: l.offeredSpec } : {}),
    ...(l.offeredCondition ? { offered_condition: l.offeredCondition as Condition } : {}),
    ...(metadata?.[i] ? { shipping: metadata[i]!.shipping } : {}),
  })),
  total_landed_price: b.statedTotal, perks: b.perks, claims: b.claims, floor_check_passed: b.floorCheckPassed,
  mirror_snapshot_id: '', decision_trace: '', expires_at: '', origin: b.origin as Origin, source: b.source, sealed_at: ms(b.sealedAt),
});

function needItemsFor(ctx: { db: Ctx['db'] | VCtx['db'] }, needId: string) {
  const needItems = new Map<string, NeedItem>();
  for (const i of ctx.db.needItem.needId.filter(needId)) {
    needItems.set(i.skuSpec, {
      sku_spec: i.skuSpec, condition: i.condition as Condition, allowed_conditions: i.allowedConditions as Condition[],
      variant: i.variant, quantity: i.quantity, unit: i.unit,
    });
  }
  return needItems;
}

function selectedCandidate(roundId: string, needId: string, b: BidRow, metadata: LineMeta[], picked: number[], landed: number,
                           needItems: Map<string, NeedItem>) {
  const lines = picked.map((lineIndex) => {
    const line = b.lines[lineIndex]!;
    const meta = metadata[lineIndex]!;
    return {
      line_index: lineIndex, sku_spec: line.skuSpec, unit_price: line.unitPrice, quantity: line.quantity,
      ...(line.offeredSpec ? { offered_spec: line.offeredSpec } : {}),
      ...(line.offeredCondition ? { offered_condition: line.offeredCondition } : {}),
      listing_id: meta.listingId, listing_hash: meta.listingHash, source: meta.source, snapshot_id: meta.snapshotId,
      provenance: meta.provenance, attrs: meta.attrs, shipping: meta.shipping,
    };
  });
  const lineMetaJson = JSON.stringify(picked.map((i) => metadata[i]!));
  const linesJson = JSON.stringify(lines);
  // Bind the requested SKU/quantity/spec contract as well as the seller's available stock lines.
  // The view keeps the original stock quantity for audit; consumers use Need.quantity to order.
  const needBinding = [...needItems.values()].map((item) => ({
    sku_spec: item.sku_spec, condition: item.condition,
    allowed_conditions: [...(item.allowed_conditions ?? [])].sort(), variant: item.variant,
    quantity: item.quantity, unit: item.unit,
  })).sort((a, b) => a.sku_spec < b.sku_spec ? -1 : a.sku_spec > b.sku_spec ? 1 : 0);
  const bindingHash = sha256(JSON.stringify({ roundId, needId, bidId: b.id, sellerId: b.sellerId, origin: b.origin,
    landed, needItems: needBinding, lines, lineMetaJson }));
  return { linesJson, lineMetaJson, bindingHash };
}

/** Same shared picker used by final close; the private referee view returns only the chosen allowed lines. */
export function reviewCandidatesView(ctx: VCtx) {
  if (roleOf(ctx)?.role !== 'referee') return [];
  return reviewCandidates(ctx);
}

function reviewCandidates(ctx: { db: Ctx['db'] | VCtx['db'] }) {
  const out: { roundId: string; needId: string; bidId: string; sellerId: string; origin: string; rank: number; landed: number; linesJson: string; lineMetaJson: string; bindingHash: string }[] = [];
  for (const round of ctx.db.round.iter()) {
    if (round.state !== 'review') continue;
    const need = ctx.db.need.id.find(round.needId);
    if (!need) continue;
    const rows = [...ctx.db.bid.roundId.filter(round.id)];
    const needItems = needItemsFor(ctx, round.needId);
    const rejections = new Map<string, string[]>();
    const lineRejects = new Map<string, string[]>();
    const metas = new Map<string, LineMeta[]>();
    for (const b of rows) {
      const parsed = parseLineMeta(b.lineMetaJson || '[]', b.lines.length);
      if (!parsed.rows) rejections.set(b.id, [`missing or invalid line metadata: ${parsed.reason}`]);
      else metas.set(b.id, parsed.rows);
      if (!b.floorCheckPassed) rejections.set(b.id, [...(rejections.get(b.id) ?? []), 'below this seller floor']);
      lineRejects.set(b.id, b.lineRejects);
    }
    const ranked = rankBids(rows.map((b) => toBid(b, metas.get(b.id))), {
      needItems, rejections, lineRejects, quality: MARKET_CONFIG.quality,
    });
    for (const item of ranked.ranked) {
      // Partial bids may remain visible in rank ordering, but cannot enter review or settlement.
      if (item.picked.length !== needItems.size) continue;
      const b = rows.find((row) => row.id === item.bid.id)!;
      const metadata = metas.get(b.id)!;
      const selected = selectedCandidate(round.id, round.needId, b, metadata, item.picked, item.landed, needItems);
      out.push({ roundId: round.id, needId: round.needId, bidId: b.id, sellerId: b.sellerId, origin: b.origin,
        rank: item.rank, landed: item.landed, ...selected });
    }
  }
  return out;
}

type ReviewRanking = {
  rows: BidRow[];
  metas: Map<string, LineMeta[]>;
  needItems: Map<string, NeedItem>;
  candidateHashes: Map<string, string>;
  ranked: ReturnType<typeof rankBids>;
};

/** One authoritative post-check eligibility and ordering pass, shared by the referee view and final close. */
function rankReviewRound(ctx: { db: Ctx['db'] | VCtx['db'] }, roundId: string,
                         sameSellerExclusions: Map<string, string[]> = new Map()): ReviewRanking {
  const round = ctx.db.round.id.find(roundId);
  if (!round) throw new SenderError(`no round ${roundId}`);
  const needItems = needItemsFor(ctx, round.needId);
  const rows = [...ctx.db.bid.roundId.filter(roundId)];
  const rejections = new Map<string, string[]>();
  const verified = new Map<string, number>();
  const metas = new Map<string, LineMeta[]>();
  const candidateHashes = new Map<string, string>();
  for (const b of rows) {
    const reasons: string[] = [];
    const parsedMeta = parseLineMeta(b.lineMetaJson || '[]', b.lines.length);
    if (!parsedMeta.rows) reasons.push(`missing or invalid line metadata: ${parsedMeta.reason}`);
    else metas.set(b.id, parsedMeta.rows);
    if (!b.floorCheckPassed) reasons.push('below this seller floor');
    const checks = [...ctx.db.bidCheck.bidId.filter(b.id)];
    if (!checks.some((c) => c.kind === 'shield')) reasons.push('missing independent Shield review');
    const candidateRank = parsedMeta.rows && b.floorCheckPassed
      ? rankBids([toBid(b, parsedMeta.rows)], { needItems, lineRejects: new Map([[b.id, b.lineRejects]]), quality: MARKET_CONFIG.quality }).ranked[0]
      : undefined;
    const candidate = candidateRank && candidateRank.picked.length === needItems.size && parsedMeta.rows
      ? selectedCandidate(roundId, round.needId, b, parsedMeta.rows, candidateRank.picked, candidateRank.landed, needItems)
      : undefined;
    if (candidate) candidateHashes.set(b.id, candidate.bindingHash);
    if (candidateRank && candidateRank.picked.length !== needItems.size) reasons.push('bid does not cover every requested item');
    const bound = (check: typeof checks[number], line?: { line_index: number; listing_id: string; listing_hash: string }) => {
      try {
        const proof = JSON.parse(check.bindingJson || '{}');
        return proof.bindingHash === candidate?.bindingHash && (!line || (proof.lineIndex === line.line_index
          && proof.listingId === line.listing_id && proof.listingHash === line.listing_hash));
      } catch { return false; }
    };
    if (candidate && !checks.some((c) => c.kind === 'advocate' && bound(c))) reasons.push('missing AdvocateCard bound to the selected candidate');
    const selectedLines = candidate ? JSON.parse(candidate.linesJson) as { line_index: number; listing_id: string; listing_hash: string }[] : [];
    for (const claim of b.claims) for (const line of selectedLines) {
      if (!checks.some((c) => c.kind === 'claim' && c.detail === claim && bound(c, line))) {
        reasons.push(`missing independent check for claim: ${claim} on selected line ${line.line_index}`);
      }
    }
    for (const c of checks) {
      if (c.kind === 'shield' && c.result !== 'allow') reasons.push(`Bazaar Shield ${c.result}: ${c.detail}`);
      if (c.kind === 'claim' && c.result === 'false') reasons.push(`claim did not match the page: ${c.detail}`);
      if (c.kind === 'claim' && c.result === 'verified' && bound(c)) verified.set(b.id, (verified.get(b.id) ?? 0) + 1);
      if (c.kind === 'advocate' && c.result === 'veto') reasons.push(`Advocate veto (${c.detail}) [source: ${c.evidenceUrl}]`);
    }
    if (sameSellerExclusions.has(b.id)) reasons.push(...sameSellerExclusions.get(b.id)!);
    if (reasons.length) rejections.set(b.id, reasons);
  }
  const spendLimit = ctx.db.need.id.find(round.needId)?.spendLimit;
  const lineRejects = new Map(rows.map((b) => [b.id, b.lineRejects]));
  const ranked = rankBids(rows.map((b) => toBid(b, metas.get(b.id))), {
    needItems, rejections, lineRejects, spendLimit, quality: MARKET_CONFIG.quality, verifiedClaims: (b) => verified.get(b.id) ?? 0,
  });
  return { rows, metas, needItems, candidateHashes, ranked };
}

/** Referee-only final ordering after independent checks, before same-seller exclusions. */
export function eligibleReviewCandidatesView(ctx: VCtx) {
  if (roleOf(ctx)?.role !== 'referee') return [];
  const out: { roundId: string; needId: string; bidId: string; sellerId: string; origin: string; rank: number; landed: number; linesJson: string; lineMetaJson: string; bindingHash: string }[] = [];
  for (const round of ctx.db.round.iter()) {
    if (round.state !== 'review') continue;
    const ranking = rankReviewRound(ctx, round.id);
    const byId = new Map(ranking.rows.map((b) => [b.id, b]));
    for (const item of ranking.ranked.ranked) {
      if (item.picked.length !== ranking.needItems.size) continue;
      const b = byId.get(item.bid.id)!;
      const metadata = ranking.metas.get(b.id)!;
      const selected = selectedCandidate(round.id, round.needId, b, metadata, item.picked, item.landed, ranking.needItems);
      out.push({ roundId: round.id, needId: round.needId, bidId: b.id, sellerId: b.sellerId, origin: b.origin,
        rank: item.rank, landed: item.landed, ...selected });
    }
  }
  return out;
}

function sameSellerProof(bindingJson: string) {
  try { return JSON.parse(bindingJson || 'null'); } catch { return undefined; }
}

/**
 * Referee attests the opaque reference identifies a pinned registry, mirror, or bound-state identity record/group.
 * Never pass raw or hashed payee/owner values or seller-supplied claims; Market validates binding and shape, not ownership.
 */
export function attachSameSellerExclusion(
  ctx: Ctx,
  a: { roundId: string; keptBidId: string; excludedBidId: string; keptBindingHash: string; excludedBindingHash: string;
    identityEvidenceJson: { source: string; reference: string } },
) {
  requireRole(ctx, 'attach_same_seller_exclusion', ['referee']);
  const round = ctx.db.round.id.find(a.roundId);
  if (!round || round.state !== 'review' || !round.reviewDeadline || ms(ctx.timestamp) >= ms(round.reviewDeadline)) {
    throw new SenderError('same-seller exclusions are accepted only during review');
  }
  if (a.keptBidId === a.excludedBidId || !/^[a-f0-9]{64}$/.test(a.keptBindingHash)
      || !/^[a-f0-9]{64}$/.test(a.excludedBindingHash)) throw new SenderError('same-seller proof needs distinct bids and current SHA-256 bindings');
  const ranking = rankReviewRound(ctx, a.roundId);
  const kept = ranking.ranked.ranked.find((row) => row.bid.id === a.keptBidId);
  const excluded = ranking.ranked.ranked.find((row) => row.bid.id === a.excludedBidId);
  const keptBid = ranking.rows.find((row) => row.id === a.keptBidId);
  const excludedBid = ranking.rows.find((row) => row.id === a.excludedBidId);
  if (!kept || !excluded || !keptBid || !excludedBid || kept.rank >= excluded.rank
      || kept.picked.length !== ranking.needItems.size || excluded.picked.length !== ranking.needItems.size
      || keptBid.sellerId === excludedBid.sellerId
      || ranking.candidateHashes.get(a.keptBidId) !== a.keptBindingHash
      || ranking.candidateHashes.get(a.excludedBidId) !== a.excludedBindingHash) {
    throw new SenderError('same-seller proof must bind eligible bids in current Market rank order');
  }
  if (!validSameSellerIdentityEvidence(a.identityEvidenceJson, [a.keptBidId, a.excludedBidId, keptBid.sellerId, excludedBid.sellerId])) {
    throw new SenderError('same-seller proof needs a trusted identity evidence reference');
  }
  const proof = {
    keptBidId: a.keptBidId, keptSellerId: keptBid.sellerId, keptBindingHash: a.keptBindingHash,
    excludedBidId: a.excludedBidId, excludedSellerId: excludedBid.sellerId, excludedBindingHash: a.excludedBindingHash,
    identityEvidenceJson: a.identityEvidenceJson,
    reason: SAME_SELLER_REASON,
  };
  const detail = `${SAME_SELLER_REASON.rule_id}: ${SAME_SELLER_REASON.summary}`;
  const existing = [...ctx.db.bidCheck.bidId.filter(a.excludedBidId)].filter((check) => check.kind === 'same_seller');
  const matching = existing.find((check) => check.result === 'excluded' && check.detail === detail
    && check.evidenceUrl === SAME_SELLER_REASON.source_url && JSON.stringify(sameSellerProof(check.bindingJson)) === JSON.stringify(proof));
  if (matching) return;
  const row = { bidId: a.excludedBidId, kind: 'same_seller', result: 'excluded', detail,
    evidenceUrl: SAME_SELLER_REASON.source_url, origin: excludedBid.origin, at: ctx.timestamp, bindingJson: JSON.stringify(proof) };
  if (existing.length) {
    ctx.db.bidCheck.id.update({ ...existing[0]!, ...row });
    for (const duplicate of existing.slice(1)) ctx.db.bidCheck.id.update({ ...duplicate, result: 'stale' });
  } else ctx.db.bidCheck.insert({ id: 0n, ...row });
}

function validSameSellerIdentityEvidence(value: unknown, candidateIds: string[]): value is { source: string; reference: string } {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const evidence = value as Record<string, unknown>;
  return Object.keys(evidence).length === 2 && Object.keys(evidence).every((key) => key === 'source' || key === 'reference')
    && ['registry', 'mirror', 'bound_state'].includes(String(evidence.source))
    && typeof evidence.reference === 'string'
    && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(evidence.reference)
    && !candidateIds.includes(evidence.reference);
}

/** Referee-only confirmation that a stale duplicate exclusion no longer applies after re-review. */
export function clearSameSellerExclusion(ctx: Ctx, { roundId, excludedBidId }: { roundId: string; excludedBidId: string }) {
  requireRole(ctx, 'clear_same_seller_exclusion', ['referee']);
  const round = ctx.db.round.id.find(roundId);
  if (!round || round.state !== 'review' || !round.reviewDeadline || ms(ctx.timestamp) >= ms(round.reviewDeadline)) {
    throw new SenderError('same-seller exclusions can be cleared only during review');
  }
  const bid = ctx.db.bid.id.find(excludedBidId);
  if (!bid || bid.roundId !== roundId) throw new SenderError('no excluded bid in this round');
  for (const check of ctx.db.bidCheck.bidId.filter(excludedBidId)) {
    if (check.kind !== 'same_seller') continue;
    if (check.result === 'excluded') throw new SenderError('only a stale same-seller exclusion can be cleared');
    if (check.result === 'stale') ctx.db.bidCheck.id.update({ ...check, result: 'cleared' });
  }
}

export function closeRound(ctx: Ctx, { roundId }: { roundId: string }) {
  requireRole(ctx, 'close_round', ['referee']);
  return closeRoundInner(ctx, roundId, false);
}

/** Body of the scheduled reducer: only the module itself (the scheduler) may run it. */
export function closeRoundOnDeadline(ctx: Ctx, roundId: string) {
  requireRole(ctx, 'close_round_on_deadline (the deadline scheduler)', ['scheduler']);
  return closeRoundInner(ctx, roundId, true);
}

function validateSameSellerProofs(ctx: Ctx, ranking: ReviewRanking): Map<string, string[]> | undefined {
  const bids = new Map(ranking.rows.map((bid) => [bid.id, bid]));
  const ranked = new Map(ranking.ranked.ranked.map((item) => [item.bid.id, item]));
  const active = ranking.rows.flatMap((bid) => [...ctx.db.bidCheck.bidId.filter(bid.id)]
    .filter((check) => check.kind === 'same_seller' && check.result !== 'cleared'));
  const excluded = new Map<string, string[]>();
  let stale = false;
  for (const check of active) {
    if (check.result === 'stale') { stale = true; continue; }
    const proof = sameSellerProof(check.bindingJson);
    const keptBid = proof && bids.get(proof.keptBidId);
    const excludedBid = proof && bids.get(proof.excludedBidId);
    const keptRank = proof && ranked.get(proof.keptBidId);
    const excludedRank = proof && ranked.get(proof.excludedBidId);
    const valid = check.result === 'excluded' && check.bidId === proof?.excludedBidId
      && check.detail === `${SAME_SELLER_REASON.rule_id}: ${SAME_SELLER_REASON.summary}`
      && check.evidenceUrl === SAME_SELLER_REASON.source_url
      && proof?.reason?.rule_id === SAME_SELLER_REASON.rule_id
      && proof?.reason?.summary === SAME_SELLER_REASON.summary
      && proof?.reason?.source_url === SAME_SELLER_REASON.source_url
      && keptBid && excludedBid && keptBid.sellerId === proof.keptSellerId && excludedBid.sellerId === proof.excludedSellerId
      && validSameSellerIdentityEvidence(proof.identityEvidenceJson, [proof.keptBidId, proof.excludedBidId, proof.keptSellerId, proof.excludedSellerId])
      && keptBid.sellerId !== excludedBid.sellerId && keptRank && excludedRank && keptRank.rank < excludedRank.rank
      && ranking.candidateHashes.get(keptBid.id) === proof.keptBindingHash
      && ranking.candidateHashes.get(excludedBid.id) === proof.excludedBindingHash;
    if (!valid) { stale = true; continue; }
    const reason = `same-seller exclusion: ${proof.keptBidId} (${proof.keptSellerId}) shares trusted identity with the higher-ranked seller`;
    if (excluded.has(proof.excludedBidId)) { stale = true; continue; }
    excluded.set(proof.excludedBidId, [reason]);
  }
  return stale ? undefined : excluded;
}

function reopenForSameSellerReview(ctx: Ctx, roundId: string, round: NonNullable<ReturnType<typeof ctx.db.round.id.find>>) {
  for (const bid of ctx.db.bid.roundId.filter(roundId)) for (const check of ctx.db.bidCheck.bidId.filter(bid.id)) {
    if (check.kind === 'same_seller' && check.result !== 'cleared' && check.result !== 'stale') {
      ctx.db.bidCheck.id.update({ ...check, result: 'stale' });
    }
  }
  const reviewDeadline = tsFromMs(ms(ctx.timestamp) + REVIEW_WINDOW_MS);
  ctx.db.round.id.update({ ...round, state: 'review', reviewDeadline });
  scheduleClose(ctx, roundId, reviewDeadline);
  event(ctx, 'same_seller_review_reopened', 'round', roundId,
    'Same-seller review must be refreshed after independent checks changed', '', round.origin);
}

function closeRoundInner(ctx: Ctx, roundId: string, fromTimer: boolean) {
  const r = ctx.db.round.id.find(roundId);
  if (!r) throw new SenderError(`no round ${roundId}`);
  if (r.state === 'closed') {
    if (fromTimer) return;
    throw new SenderError('round already closed');
  }
  if (r.state === 'open') {
    if (!isClosed(clockOf(r), ms(ctx.timestamp))) {
      if (fromTimer) return scheduleClose(ctx, roundId, r.deadline);
      throw new SenderError('round is still open until its deadline');
    }
    const reviewDeadline = tsFromMs(ms(ctx.timestamp) + REVIEW_WINDOW_MS);
    ctx.db.round.id.update({ ...r, state: 'review', reviewDeadline });
    scheduleClose(ctx, roundId, reviewDeadline);
    event(ctx, 'review_opened', 'round', roundId, 'Bid cutoff reached; independent checks are being collected', '', r.origin);
    return;
  }
  if (r.state !== 'review' || !r.reviewDeadline) throw new SenderError('round lifecycle state is invalid');
  if (ms(ctx.timestamp) < ms(r.reviewDeadline)) {
    if (fromTimer) return scheduleClose(ctx, roundId, r.reviewDeadline);
    throw new SenderError('review period is still open until its deadline');
  }

  const baseRanking = rankReviewRound(ctx, roundId);
  const sameSellerExclusions = validateSameSellerProofs(ctx, baseRanking);
  if (!sameSellerExclusions) {
    reopenForSameSellerReview(ctx, roundId, r);
    return;
  }
  const ranking = sameSellerExclusions.size ? rankReviewRound(ctx, roundId, sameSellerExclusions) : baseRanking;
  const { rows, metas, candidateHashes, ranked } = ranking;
  const byId = new Map(rows.map((b) => [b.id, b]));
  for (const x of ranked.ranked) {
    const b = byId.get(x.bid.id)!;
    // The lines are the picked alternatives (the cheapest allowed line per SKU), the ones the rank is about.
    const metadata = metas.get(b.id)!;
    ctx.db.roundResult.insert({ id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: x.rank, landed: x.landed, reasons: [], lines: x.picked.map((i) => b.lines[i]!), origin: b.origin, source: b.source, lineMetaJson: JSON.stringify(x.picked.map((i) => metadata[i]!)), bindingHash: candidateHashes.get(b.id) ?? '' });
  }
  for (const d of ranked.disqualified) {
    const b = byId.get(d.bid.id)!;
    ctx.db.roundResult.insert({ id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: 0, landed: d.landed, reasons: d.reasons, lines: b.lines, origin: b.origin, source: b.source, lineMetaJson: metas.has(b.id) ? JSON.stringify(metas.get(b.id)) : '[]', bindingHash: candidateHashes.get(b.id) ?? '' });
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
    requestedBy: string; origin: string; goalId: string; needId: string;
  },
) {
  requireRole(ctx, 'create_mandate', ['buyer', 'referee'], a.buyerId);
  if (ctx.db.mandate.hash.find(a.hash)) throw new SenderError('mandate hash already exists');
  if (!(Number.isFinite(a.amount) && a.amount > 0)) throw new SenderError('mandate amount must be finite and positive');
  if (!(Number.isInteger(a.expiryMinutes) && a.expiryMinutes > 0 && a.expiryMinutes <= 10)) throw new SenderError('mandate expiry must be between 1 and 10 minutes');
  const allow = allowanceFor(ctx, a.buyerId);
  const d = decide(allow, a.amount, ms(ctx.timestamp));
  const within = d.path === 'auto';
  if (a.goalId) {
    const g = ctx.db.goal.id.find(a.goalId);
    if (!g || g.buyerId !== a.buyerId) throw new SenderError('no goal for this buyer');
    const n = a.needId ? ctx.db.need.id.find(a.needId) : undefined;
    if (!n || n.goalId !== g.id || n.buyerId !== a.buyerId) throw new SenderError('mandate need is not bound to this buyer goal');
    if (n.spendLimit > g.cap) throw new SenderError('need cap is above the goal cap');
    const expected = [...ctx.db.goalItem.goalId.filter(g.id)].filter((i) => !i.skippedOwnedPartId).map((i) => `${i.skuSpec}|${i.quantity}`).sort();
    const covered = [...ctx.db.needItem.needId.filter(n.id)].map((i) => `${i.skuSpec}|${i.quantity}`).sort();
    if (expected.length !== covered.length || expected.some((x, i) => x !== covered[i])) throw new SenderError('mandate need does not cover the complete goal');
    reserveGoalInner(ctx, a.goalId, a.dealId, a.hash, a.amount);
    const current = ctx.db.goal.id.find(a.goalId)!;
    ctx.db.goal.id.update({ ...current, state: within ? 'HUNTING' : 'HOLD_FOR_CALL' });
  } else if (a.needId) {
    throw new SenderError('a need cannot be bound without its goal');
  }
  ctx.db.mandate.insert({
    hash: a.hash, id: a.id, dealId: a.dealId, buyerId: a.buyerId, amount: a.amount, payee: a.payee,
    expiry: tsFromMs(ms(ctx.timestamp) + a.expiryMinutes * 60_000), nonce: a.nonce, withinAllowance: within,
    requestedBy: a.requestedBy, origin: a.origin, goalId: a.goalId, needId: a.needId, retired: false, retirementAttemptId: '',
  });
  event(ctx, 'mandate_created', 'mandate', a.hash, within ? 'Deal within the allowance' : 'Deal needs the buyer call', a.payee, a.origin);
  if (within) {
    // The standing rule authorizes the deal, but spend is counted only after a confirmed charge.
    ctx.db.approval.insert({ id: 0n, mandateHash: a.hash, method: 'allowance', approvedBy: a.buyerId, at: ctx.timestamp });
    ctx.db.notification.insert({ id: 0n, buyerId: a.buyerId, goalId: '', klass: 'deal_found', text: `Auto-approved within your allowance: ${d.reason}. Waiting for the seller payment request; no charge yet.`, push: false, at: ctx.timestamp });
    event(ctx, 'approval_recorded', 'approval', a.hash, 'Authorized within the allowance; charge not yet made', a.payee, a.origin);
  } else {
    ctx.db.notification.insert({ id: 0n, buyerId: a.buyerId, goalId: '', klass: 'state', text: `Call needed: ${d.reason}.`, push: true, at: ctx.timestamp });
  }
}

export function recordApproval(ctx: Ctx, a: { mandateHash: string; method: string; approvedBy: string }) {
  requireRole(ctx, 'record_approval', ['buyer', 'referee']);
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  if (md.retired) throw new SenderError('mandate was retired before submission; approval is closed');
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
export const PAYMENT_MODES: Record<string, { label: string; origin: string }> = {
  sim: { label: 'Payment recorded (SIM stub, no money moved)', origin: 'SIM' },
  stripe_test: { label: 'Payment recorded (Stripe test mode)', origin: 'LIVE' },
};

/** `mode` says how the money moved, so the label is honest: sim (our stub) or stripe_test (Stripe's test API). */
export function recordPayment(ctx: Ctx, a: { mandateHash: string; paymentRef: string; amount: number; mode: string }) {
  requireRole(ctx, 'record_payment', ['referee']);
  const mode = PAYMENT_MODES[a.mode];
  if (!mode) throw new SenderError(`payment mode must be one of ${Object.keys(PAYMENT_MODES).join(', ')}`);
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  if (md.retired) throw new SenderError('mandate was retired before submission; payment refused');
  const ap = ctx.db.approval.mandateHash.find(a.mandateHash);
  if (!ap) throw new SenderError('no approval row for this mandate hash; payment refused');
  if (a.amount !== md.amount) throw new SenderError('payment amount differs from the mandate amount');
  if (md.goalId) {
    const g = ctx.db.goal.id.find(md.goalId);
    if (!g || g.buyerId !== md.buyerId || g.reservedAmount !== md.amount || g.reservedDealId !== md.dealId
        || g.reservedMandateHash !== md.hash || g.state === 'DONE' || g.state === 'EXPIRED') {
      throw new SenderError('payment does not match the active goal reservation');
    }
  }
  const auth = authorizePayment({ amount: a.amount, limit_checked: true, approval_id: String(ap.id) }, md.amount);
  if (!auth.ok) throw new SenderError(auth.reasons.join('; '));
  if (ctx.db.payment.mandateHash.find(a.mandateHash)) return rejected(ctx, 'payment', a.mandateHash, 'second payment for the same mandate refused');
  ctx.db.payment.insert({ id: 0n, mandateHash: a.mandateHash, paymentRef: a.paymentRef, amount: a.amount, at: ctx.timestamp, mode: a.mode });
  // Every successful spend counts against the same period budget, whether a call or standing rule approved it.
  saveAllowance(ctx, recordAutoSpend(allowanceFor(ctx, md.buyerId), a.amount, ms(ctx.timestamp)));
  event(ctx, 'payment_recorded', 'payment', a.mandateHash, mode.label, md.payee, mode.origin);
}

/**
 * Referee-only relay after NonceStore.retire_unsubmitted_attempt atomically proves that this exact
 * RequestPayment was never submitted. Generic Payment Protocol refusals are not retirement proof.
 */
export function resolveNoCharge(ctx: Ctx, a: { dealId: string; mandateHash: string; attemptId: string }) {
  requireRole(ctx, 'resolve_no_charge', ['referee']);
  if (!/^req:[a-f0-9]{64}$/.test(a.attemptId)) throw new SenderError('attempt ID must be the exact request hash');
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md || md.dealId !== a.dealId || !md.goalId) throw new SenderError('no matching goal mandate for this exact deal');
  if (md.retired) {
    if (md.retirementAttemptId === a.attemptId) return;
    throw new SenderError('mandate was already retired by a different request');
  }
  if (ctx.db.payment.mandateHash.find(md.hash)) throw new SenderError('a charged mandate cannot be retired as no-charge');
  const g = ctx.db.goal.id.find(md.goalId);
  if (!g || g.buyerId !== md.buyerId || g.reservedDealId !== md.dealId || g.reservedMandateHash !== md.hash
      || g.reservedAmount !== md.amount) throw new SenderError('no active exact reservation to release');
  ctx.db.mandate.hash.update({ ...md, retired: true, retirementAttemptId: a.attemptId });
  ctx.db.goal.id.update({ ...g, state: 'HUNTING', reservedAmount: 0, reservedDealId: '', reservedMandateHash: '' });
  event(ctx, 'mandate_retired', 'mandate', md.hash, 'Exact unsubmitted payment attempt retired; reservation released', md.payee, md.origin);
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

const CEILING_STEP = 500;
const usd = (x: number) => `$${x.toLocaleString('en-US')}`;
/** The buyer's ceiling as a $500 band ("$500 to $1,000"), never the number itself. */
export function ceilingBand(limit: number): string {
  if (!(limit > 0)) return 'not set';
  const lo = Math.floor(limit / CEILING_STEP) * CEILING_STEP;
  return lo === 0 ? `under ${usd(CEILING_STEP)}` : `${usd(lo)} to ${usd(lo + CEILING_STEP)}`;
}

export function sellerNeedsView(ctx: VCtx | AVCtx) {
  const out: { roundId: string; needId: string; skuSpec: string; condition: string; variant: string; quantity: number; unit: string; deliveryWindow: string; deadline: Timestamp; ceilingBand: string; origin: string }[] = [];
  for (const r of ctx.db.round.iter()) {
    if (r.state !== 'open') continue;
    const n = ctx.db.need.id.find(r.needId);
    if (!n) continue;
    const items = [...ctx.db.needItem.needId.filter(n.id)].map((i) => ({ sku_spec: i.skuSpec, condition: i.condition as Condition, variant: i.variant, quantity: i.quantity, unit: i.unit }));
    const v = sellerView({ id: n.id, items, delivery_window: n.deliveryWindow }, '');
    for (const i of v.items) {
      out.push({ roundId: r.id, needId: v.need_id, skuSpec: i.sku_spec, condition: i.condition, variant: i.variant, quantity: i.quantity, unit: i.unit, deliveryWindow: v.delivery_window, deadline: r.deadline, ceilingBand: ceilingBand(n.spendLimit), origin: n.origin });
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

/** This caller's failed pairing attempts, so a screen can say "wrong code" (never the code). */
export function myPairAttemptsView(ctx: VCtx) {
  const row = ctx.db.pairAttempt.identity.find(ctx.sender);
  return row ? [row] : [];
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

export function myGoalStepEventsView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  return id ? [...ctx.db.goalStepEvent.buyerId.filter(id)] : [];
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

// ---- b5: approval code on the buyer screen, typed fallback ----

export const APPROVAL_MAX_FAILURES = 5;
// Keep in parity with pay.approval.CALL_CODE_TTL_S. A screen code must not outlive the real voice code.
export const APPROVAL_CODE_TTL_MS = 300_000;
const normCode = (x: string) => x.trim().toLowerCase().replace(/\s+/g, ' ');
const approvalCodeExpiresAt = (md: { expiry: Timestamp }, issuedAt: Timestamp) =>
  Math.min(ms(md.expiry), ms(issuedAt) + APPROVAL_CODE_TTL_MS);

/** Referee (Lane D's approval relay) only: store the word pair it issued for a mandate that still needs the buyer's call. */
export function issueApprovalCode(ctx: Ctx, { mandateHash, code }: { mandateHash: string; code: string }) {
  requireRole(ctx, 'issue_approval_code', ['referee']);
  const md = ctx.db.mandate.hash.find(mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  if (md.retired) throw new SenderError('mandate was retired before submission; approval is closed');
  if (ms(ctx.timestamp) >= ms(md.expiry)) throw new SenderError('mandate expired; the deal must be re-quoted');
  if (ctx.db.approval.mandateHash.find(mandateHash)) throw new SenderError('mandate already approved; no code needed');
  if (!normCode(code)) throw new SenderError('empty code');
  const row = { mandateHash, buyerId: md.buyerId, code: normCode(code), failures: 0, locked: false, issuedAt: ctx.timestamp };
  if (ctx.db.approvalCode.mandateHash.find(mandateHash)) ctx.db.approvalCode.mandateHash.update(row);
  else ctx.db.approvalCode.insert(row);
}

/**
 * The typed fallback: the mandate's own buyer types the code shown on its screen. A match records the same approval the call
 * would (method typed_code) for that exact mandate. A miss returns { approved: false } without throwing, so it is counted; 5 lock it.
 * The code never appears in a message.
 */
export function approveTyped(ctx: Ctx, { mandateHash, code }: { mandateHash: string; code: string }) {
  const md = ctx.db.mandate.hash.find(mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  if (md.retired) throw new SenderError('mandate was retired before submission; approval is closed');
  requireRole(ctx, 'approve_typed', ['buyer'], md.buyerId);
  const ac = ctx.db.approvalCode.mandateHash.find(mandateHash);
  if (!ac) throw new SenderError('no code issued for this mandate yet; wait for the call');
  if (ms(ctx.timestamp) >= approvalCodeExpiresAt(md, ac.issuedAt)) throw new SenderError('approval code expired; the deal must be re-quoted');
  if (ac.locked) throw new SenderError('typed approval is locked after too many wrong codes; approve on the call');
  if (normCode(code) !== ac.code) {
    const failures = ac.failures + 1;
    ctx.db.approvalCode.mandateHash.update({ ...ac, failures, locked: failures >= APPROVAL_MAX_FAILURES });
    return { approved: false, reason: 'wrong code' };
  }
  recordApproval(ctx, { mandateHash, method: 'typed_code', approvedBy: md.buyerId });
  return { approved: true, reason: '' };
}

/** This buyer's mandates still waiting for approval, with the code to show on this screen only. */
export function myPendingApprovalsView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  if (!id) return [];
  return [...ctx.db.approvalCode.buyerId.filter(id)].flatMap((ac) => {
    const md = ctx.db.mandate.hash.find(ac.mandateHash);
    if (!md || ctx.db.approval.mandateHash.find(ac.mandateHash)) return [];
    return [{
      mandateHash: md.hash, mandateId: md.id, amount: md.amount, payee: md.payee, expiry: md.expiry, code: ac.code,
      failures: ac.failures, locked: ac.locked, issuedAt: ac.issuedAt,
      codeExpiresAt: new Timestamp(BigInt(approvalCodeExpiresAt(md, ac.issuedAt)) * 1000n), origin: md.origin,
    }];
  });
}

// ---- b6: loss reports ----

export const GAP_BANDS = ['within5', 'within10', 'within20', 'over20'];
export const LOSS_REASONS = ['price', 'fit', 'condition', 'delivery', 'record', 'advocate_veto'];

export interface LossReportArgs {
  id: string; roundId: string; sellerId: string; won: boolean; gapBand: string; reason: string; sourceUrl: string;
  strategyDiff: { key: string; from: string; to: string }[]; whatToChange: string; whatToChangeOrigin: string; origin: string;
}

/** Referee only: a seller's loss report (banded gap, reason category, source), with its strategy diff and "what to change" when present. */
export function recordLossReport(ctx: Ctx, a: LossReportArgs) {
  requireRole(ctx, 'record_loss_report', ['referee']);
  if (!GAP_BANDS.includes(a.gapBand)) throw new SenderError(`gap_band must be one of ${GAP_BANDS.join(', ')}`);
  if (!LOSS_REASONS.includes(a.reason)) throw new SenderError(`reason must be one of ${LOSS_REASONS.join(', ')}`);
  if (ctx.db.lossReport.id.find(a.id)) throw new SenderError(`loss report ${a.id} already exists`);
  ctx.db.lossReport.insert({ ...a, createdAt: ctx.timestamp });
}

/** A seller (agent or its paired screen) sees only its own loss reports. */
export function myLossReportsView(ctx: VCtx) {
  const r = roleOf(ctx);
  if (!r || (r.role !== 'seller' && r.role !== 'seller_screen')) return [];
  return [...ctx.db.lossReport.sellerId.filter(r.subjectId)];
}

// ---- #60: agent events for the Fetch agents tile ----

/** Referee (the agents' relay) only: one line an agent sent. ts is ISO 8601 (empty means now); origin other than LIVE or MIRROR is stored as SIM. */
export function recordAgentEvent(ctx: Ctx, a: { agentName: string; address: string; text: string; ts: string; origin: string }) {
  requireRole(ctx, 'record_agent_event', ['referee']);
  if (!/^agent1q[0-9a-z]{20,}$/.test(a.address)) throw new SenderError('address must be an agent1q... Agentverse address');
  const at = a.ts ? Date.parse(a.ts) : ms(ctx.timestamp);
  if (!Number.isFinite(at)) throw new SenderError('ts must be an ISO 8601 time');
  const origin = a.origin === 'LIVE' || a.origin === 'MIRROR' ? a.origin : 'SIM';
  ctx.db.agentEvent.insert({ id: 0n, agentName: a.agentName, address: a.address, text: a.text.slice(0, 280), ts: tsFromMs(at), origin });
}

// ---- #37 item 9: buyer display name ----

/** Referee or owner: the name a buyer's screens show. */
export function setBuyerProfile(ctx: Ctx, { buyerId, displayName }: { buyerId: string; displayName: string }) {
  requireRole(ctx, 'set_buyer_profile', ['referee', 'owner']);
  const name = displayName.trim();
  if (!name) throw new SenderError('display name required');
  const row = { buyerId, displayName: name.slice(0, 60), origin: 'SIM' };
  if (ctx.db.buyerProfile.buyerId.find(buyerId)) ctx.db.buyerProfile.buyerId.update(row);
  else ctx.db.buyerProfile.insert(row);
}

export function myBuyerProfileView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  const row = id ? ctx.db.buyerProfile.buyerId.find(id) : undefined;
  return row ? [row] : [];
}
