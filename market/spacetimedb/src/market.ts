// Reducer and view bodies as plain functions over ctx, so tests call them directly through the
// module test harness. index.ts registers them. All market logic comes from market/rules, which
// the Convex fallback would call unchanged.
import { SenderError, type InferSchema, type ReducerCtx, type ViewCtx, type AnonymousViewCtx } from 'spacetimedb/server';
import { ScheduleAt, Timestamp, type Identity } from 'spacetimedb';
import type spacetimedb from './schema';
import { ANY_CONDITION, checkFloorByCondition } from '../../rules/floor';
import { adjustmentReason, rankBids } from '../../rules/scoring';
import { MARKET_CONFIG } from '../../config';
import { DEFAULT_SEAL, isClosed, tryBid, type AuctionClock } from '../../rules/sealing';
import { sellerView } from '../../rules/redaction';
import { authorizePayment } from '../../rules/approval';
import { sha256Hex } from '../../rules/sha256';
import { HOLD_TTL_MS, SOLD_OUT_REASON, availableStock, holdIsActive, soldOutReasons, type HoldLike, type HoldState } from '../../rules/holds';
import { decide, raiseOnCleanReceiving, recordAutoSpend, requesterMayApprove, newAllowance, setAllowance, type Allowance, type Period } from '../../rules/allowance';
import type { Bid, Condition, NeedItem, Origin } from '../../rules/types';
import { resetDemo, seedDemo } from './demo';

type S = InferSchema<typeof spacetimedb>;
type Ctx = ReducerCtx<S>;
type VCtx = ViewCtx<S>;
type AVCtx = AnonymousViewCtx<S>;

type Line = { skuSpec: string; offeredSpec: string; offeredCondition: string; unitPrice: number; quantity: number };

const ms = (ts: Timestamp) => Number(ts.microsSinceUnixEpoch / 1000n);
const tsFromMs = (x: number) => new Timestamp(BigInt(Math.round(x)) * 1000n);

function event(ctx: Ctx, kind: string, refTable: string, refId: string, label: string, sellerId = '', origin = 'SIM', at = ctx.timestamp) {
  ctx.db.floorEvent.insert({ id: 0n, kind, refTable, refId, sellerId, label, origin, at });
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
// #135: identities are free, so a per-identity lock alone lets an attacker brute-force the code by rotating
// identities. This soft, code-wide throttle backs it up: PAIR_THROTTLE_MISSES wrong codes on the same code
// within PAIR_THROTTLE_WINDOW_MS make every new attempt on that code (right or wrong, any identity) wait
// PAIR_THROTTLE_WAIT_MS. It never locks the code; the owner always gets through once the wait is over.
export const PAIR_THROTTLE_MISSES = 20;
export const PAIR_THROTTLE_WINDOW_MS = 10 * 60 * 1000;
export const PAIR_THROTTLE_WAIT_MS = 60 * 1000;
// Crockford base32: no I L O U, so a misread character is never mistaken for another. 10 characters, shown
// grouped as XXXXX-XXXXX; compared case-insensitively with the grouping ignored (normPairCode).
const PAIR_CODE_CHARS = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
const PAIR_CODE_LENGTH = 10;
const normPairCode = (s: string) => s.toUpperCase().replace(/[^0-9A-Z]/g, '');
// #449 RT-2: ctx.random is seeded from the transaction timestamp (SDK 2.13), which is public, so a code the module drew
// itself could be predicted. The owner now makes the code off-module and sends it; the pair_code.code column holds only
// the sha256 hex of the normalized code (same column, no schema change), and pairing compares the hash of the input.
const isPairCode = (norm: string) => norm.length === PAIR_CODE_LENGTH && [...norm].every((c) => PAIR_CODE_CHARS.includes(c));
const matchesPairCode = (stored: string, input: string) => {
  const norm = normPairCode(input);
  return norm.length === PAIR_CODE_LENGTH && sha256Hex(norm) === stored;
};

/**
 * A browser screen takes the buyer role with the demo pairing code (SIM sign-in). A wrong code returns { paired: false } without throwing, so the failure is counted (a throw would
 * roll the count back). 5 failures lock that caller (identity) across every code; the code itself only counts failures for the
 * operator, so a stranger's misses can never lock the owner's screen out. The code-wide throttle above backs
 * this up: it is a wait, not a lock, so the operator never has to reissue just because it tripped.
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
  const now = ms(ctx.timestamp);
  if (now < ms(want.throttledUntil)) {
    throw new SenderError(`too many wrong codes on this screen recently; wait ${Math.ceil((ms(want.throttledUntil) - now) / 1000)} s and try again`);
  }
  if (!matchesPairCode(want.code, code)) {
    const windowAge = now - ms(want.windowStart);
    const freshWindow = windowAge > PAIR_THROTTLE_WINDOW_MS;
    const windowStart = freshWindow ? ctx.timestamp : want.windowStart;
    const windowMisses = (freshWindow ? 0 : want.windowMisses) + 1;
    const throttledUntil = windowMisses >= PAIR_THROTTLE_MISSES ? tsFromMs(now + PAIR_THROTTLE_WAIT_MS) : want.throttledUntil;
    ctx.db.pairCode.buyerId.update({ ...want, failedAttempts: want.failedAttempts + 1, windowStart, windowMisses, throttledUntil });
    const failures = (mine?.failures ?? 0) + 1;
    if (mine) ctx.db.pairAttempt.identity.update({ ...mine, failures });
    else ctx.db.pairAttempt.insert({ identity: ctx.sender, failures });
    if (failures >= PAIR_MAX_FAILURES) event(ctx, 'pairing_locked', 'pair_code', '', // #449 item 3 PL-16: no pair key (a buyer id) on the public floor
       'A screen is locked after too many wrong codes');
    if (windowMisses >= PAIR_THROTTLE_MISSES) event(ctx, 'pairing_throttled', 'pair_code', '', 'Pairing on a screen is throttled after many wrong codes');
    return { paired: false, reason: 'wrong pairing code' };
  }
  if (cur) ctx.db.role.identity.update({ ...cur, subjectId });
  else ctx.db.role.insert({ identity: ctx.sender, role, subjectId });
  return { paired: true, reason: '' };
}

/** Owner only: a fresh code for this buyer (made by the owner, off-module; stored as its hash), unlocked, with its counter and its throttle reset. It also clears every screen's lock (pair_attempt is keyed by identity only): the operator unlocks. */
export function reissuePairCode(ctx: Ctx, { buyerId, code }: { buyerId: string; code: string }) {
  requireRole(ctx, 'reissue_pair_code', ['owner']);
  issuePairCode(ctx, buyerId, code);
  for (const row of [...ctx.db.pairAttempt.iter()]) ctx.db.pairAttempt.identity.delete(row.identity);
}

/** Owner only: a fresh code for one seller's screen (made by the owner; stored as its hash under "seller:<id>"), with every screen lock cleared. */
export function reissueSellerScreenCode(ctx: Ctx, { sellerId, code }: { sellerId: string; code: string }) {
  requireRole(ctx, 'reissue_seller_screen_code', ['owner']);
  issuePairCode(ctx, sellerScreenKey(sellerId), code);
  for (const row of [...ctx.db.pairAttempt.iter()]) ctx.db.pairAttempt.identity.delete(row.identity);
}

/** Store the hash of an owner-made code under `key`. A bad shape is refused without echoing what was sent. */
function issuePairCode(ctx: Ctx, key: string, code: string) {
  const norm = normPairCode(code);
  if (!isPairCode(norm)) throw new SenderError(`the pairing code must be ${PAIR_CODE_LENGTH} characters from 0-9 and A-Z, without I, L, O or U`);
  const buyerId = key;
  const fresh = { buyerId, code: sha256Hex(norm), failedAttempts: 0, locked: false, windowStart: ctx.timestamp, windowMisses: 0, throttledUntil: Timestamp.UNIX_EPOCH };
  const cur = ctx.db.pairCode.buyerId.find(buyerId);
  if (cur) ctx.db.pairCode.buyerId.update(fresh);
  else ctx.db.pairCode.insert(fresh);
}

// ---------------------------------------------------------------- #374 open buyer sign-up

export const SIGNUP_MAX = 60; // global sign-up ceiling per window; RT-14 (one sign-up per identity is the real limit) stays open
export const SIGNUP_WINDOW_MS = 10 * 60 * 1000;
const ID_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789';
const PHONE_RE = /^\+[1-9][0-9]{6,14}$/;

/**
 * Anyone without a role: becomes a new buyer b_<8> bound to the caller, with a $0 per-buy allowance
 * (every deal needs their call). One sign-up per identity; 60 per 10 minutes across the market.
 */
export function signUpBuyer(ctx: Ctx, { displayName, phone }: { displayName: string; phone?: string }) {
  const had = roleOf(ctx);
  if (isOwner(ctx) || had) throw new SenderError(`already signed up: this identity is ${had ? `a ${had.role}` : 'the owner'}`);
  const name = displayName.trim().slice(0, 60);
  if (!name) throw new SenderError('display name required');
  const ph = (phone ?? '').trim().replace(/[ ()-]/g, '');
  // #449 PL-15: every purchase is approved by a call to this number, so an account without one could never buy.
  if (!ph) throw new SenderError('a phone number is required: purchases are approved by a call');
  if (!PHONE_RE.test(ph)) throw new SenderError('phone must start with + and a country code, like +14155550100');
  const now = ms(ctx.timestamp);
  const th = ctx.db.signupThrottle.id.find(0);
  const fresh = !th || now - ms(th.windowStart) >= SIGNUP_WINDOW_MS;
  if (!fresh && th.count >= SIGNUP_MAX) throw new SenderError('sign-ups are busy right now, try again in a few minutes');
  const next = { id: 0, windowStart: fresh ? ctx.timestamp : th.windowStart, count: fresh ? 1 : th.count + 1 };
  if (th) ctx.db.signupThrottle.id.update(next);
  else ctx.db.signupThrottle.insert(next);
  let buyerId = '';
  do {
    let raw = '';
    for (let i = 0; i < 8; i++) raw += ID_CHARS[ctx.random.integerInRange(0, ID_CHARS.length - 1)];
    buyerId = `b_${raw}`;
  } while ([...ctx.db.role.subjectId.filter(buyerId)].length || ctx.db.buyerProfile.buyerId.find(buyerId) || ctx.db.allowance.buyerId.find(buyerId));
  ctx.db.role.insert({ identity: ctx.sender, role: 'buyer', subjectId: buyerId });
  ctx.db.buyerProfile.insert({ buyerId, displayName: name, origin: 'SIM', phone: ph });
  ctx.db.allowance.insert(fromRule({ ...newAllowance(buyerId, now), per_purchase_limit: 0 }));
  event(ctx, 'buyer_signed_up', 'buyer_profile', '', 'A new buyer signed up'); // #449 item 3 PL-16: refId '' so the floor never shows the buyer id
  return buyerId;
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

export interface SetAllowanceArgs { buyerId: string; perPurchaseLimit: number; periodLimit: number; period: string }

/**
 * Buyer (their own id) or referee. The referee sets the demo operator's starting allowance; the buyer
 * may only lower theirs (the rule in rules/allowance.setAllowance). Writes only the allowance row and one event.
 */
export function setAllowanceChecked(ctx: Ctx, a: SetAllowanceArgs) {
  if (!a.buyerId) throw new SenderError('set_allowance needs a buyer id');
  const who = requireRole(ctx, 'set_allowance', ['buyer', 'referee'], a.buyerId);
  const r = setAllowance(
    allowanceFor(ctx, a.buyerId),
    { per_purchase_limit: a.perPurchaseLimit, period_limit: a.periodLimit, period: a.period as Period },
    who.role === 'referee' ? 'referee' : 'buyer', ms(ctx.timestamp),
  );
  if (!r.ok) throw new SenderError(`set_allowance refused: ${r.reasons.join('; ')}`);
  saveAllowance(ctx, r.allowance);
  event(ctx, 'allowance_set', 'allowance', '', 'A buyer allowance was set', '', 'SIM'); // #449 item 3 PL-16
}

// ---------------------------------------------------------------- needs and goals

export interface PostNeedArgs {
  id: string; buyerId: string; goalId: string; deliveryWindow: string; spendLimit: number; consent: boolean;
  auctionWindowS: number; origin: string;
  items: { skuSpec: string; condition: string; allowedConditions: string[]; variant: string; quantity: number; unit: string }[];
}

/** The referee path is for the buyer agent acting for a self-signed-up buyer, and only against that buyer's active goal. */
export function postNeed(ctx: Ctx, a: PostNeedArgs) {
  const who = requireRole(ctx, 'post_need', ['buyer', 'referee'], a.buyerId);
  if (who.role === 'referee') {
    const g = ctx.db.goal.id.find(a.goalId);
    if (!g || g.buyerId !== a.buyerId) throw new SenderError(`not allowed: the referee posts a need only for one of that buyer's goals; ${a.goalId || 'no goal'} is not ${a.buyerId}'s`);
    // #449 item 3 PL-9: claim_goal moves a goal to HUNTING, and the claiming agent is the one that posts its need.
    if (g.state !== 'ACTIVE' && g.state !== 'HUNTING') throw new SenderError(`not allowed: goal ${a.goalId} is not active`);
  }
  // #449 item 3 RT-31: a buyer cannot choose its own origin label; the server uses the buyer's profile. The referee keeps passing it.
  const origin = who.role === 'buyer' ? buyerOrigin(ctx, a.buyerId) : a.origin;
  allowanceFor(ctx, a.buyerId);
  if (ctx.db.need.id.find(a.id)) throw new SenderError(`need ${a.id} already exists`);
  if (!a.items.length) throw new SenderError('a need has at least one item');
  ctx.db.need.insert({
    id: a.id, buyerId: a.buyerId, goalId: a.goalId, deliveryWindow: a.deliveryWindow, spendLimit: a.spendLimit,
    consent: a.consent, auctionWindowS: a.auctionWindowS, origin, createdAt: ctx.timestamp,
  });
  for (const i of a.items) ctx.db.needItem.insert({ id: 0n, needId: a.id, ...i });
  event(ctx, 'need_posted', 'need', a.id, `New request: ${a.items.length} item(s)`, '', origin);
}

/** Lane A's Goal contract; deadline is an ISO datetime. */
export interface PostGoalArgs {
  id: string; buyerId: string; type: string; cap: number; deadline: string; poNumber: string; origin: string;
  items: { skuSpec: string; condition: string; variant: string; quantity: number; skippedOwnedPartId: string }[];
}

export const GOAL_TYPES = ['budget_cap', 'part_by_date', 'build_by_date'];

export function postGoal(ctx: Ctx, a: PostGoalArgs) {
  const who = requireRole(ctx, 'post_goal', ['buyer'], a.buyerId);
  // #449 item 3 RT-31: a buyer's goal takes the origin of the buyer's profile, whatever the caller sends.
  insertGoal(ctx, who.role === 'buyer' ? { ...a, origin: buyerOrigin(ctx, a.buyerId) } : a);
}

/** #449 item 3 RT-31: the origin label the server trusts for a buyer's own posts: the profile's, else SIM. */
const buyerOrigin = (ctx: Ctx, buyerId: string) => ctx.db.buyerProfile.buyerId.find(buyerId)?.origin || 'SIM';

/** Goal states the referee may set (PL-4). ACTIVE is only the starting state; claim_goal moves it to HUNTING. */
export const SETTABLE_GOAL_STATES = ['HUNTING', 'HOLD_FOR_CALL', 'DONE', 'EXPIRED', 'PAUSED', 'FAILED'];
const CLOSED_GOAL_STATES = ['DONE', 'EXPIRED', 'FAILED'];

/**
 * #449 item 3 PL-9: referee only. The first writer wins: an ACTIVE goal becomes HUNTING (and so leaves agent_open_goals, every
 * agent's poll); any other state means another agent has it or it is closed.
 */
export function claimGoal(ctx: Ctx, { goalId }: { goalId: string }) {
  requireRole(ctx, 'claim_goal', ['referee']);
  const g = ctx.db.goal.id.find(goalId);
  if (!g) throw new SenderError(`no goal ${goalId}`);
  if (g.state !== 'ACTIVE') throw new SenderError('goal already claimed or closed');
  ctx.db.goal.id.update({ ...g, state: 'HUNTING' });
}

/**
 * #449 item 3 PL-4: referee only. Moves a goal and tells the buyer in plain words on their own feed. A closed goal (DONE,
 * EXPIRED, FAILED) never changes again; a closing state pushes.
 */
export function setGoalState(ctx: Ctx, { goalId, state, text }: { goalId: string; state: string; text: string }) {
  requireRole(ctx, 'set_goal_state', ['referee']);
  if (!SETTABLE_GOAL_STATES.includes(state)) throw new SenderError(`state must be one of ${SETTABLE_GOAL_STATES.join(', ')}`);
  const g = ctx.db.goal.id.find(goalId);
  if (!g) throw new SenderError(`no goal ${goalId}`);
  if (CLOSED_GOAL_STATES.includes(g.state)) throw new SenderError(`goal is closed (${g.state}); it cannot change again`);
  ctx.db.goal.id.update({ ...g, state });
  ctx.db.notification.insert({ id: 0n, buyerId: g.buyerId, goalId, klass: 'state', text: text.trim().slice(0, 200), push: CLOSED_GOAL_STATES.includes(state), at: ctx.timestamp });
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
  ctx.db.round.insert({ id: roundId, needId, openedAt: ctx.timestamp, deadline, extensions: 0, state: 'open', sealedCount: 0, closedAt: undefined, origin: n.origin, stage: 1, maxStages: 1, stageWindowS: 0 });
  scheduleClose(ctx, roundId, deadline);
  event(ctx, 'round_opened', 'round', roundId, `Sealed round open for ${windowS} s`, '', n.origin);
}

/** #336: a sealed knockout round, up to maxStages best-and-final-offer stages. */
export function openKnockoutRound(ctx: Ctx, { roundId, needId, stageWindowS, maxStages = 3 }: { roundId: string; needId: string; stageWindowS: number; maxStages?: number }) {
  requireRole(ctx, 'open_round', ['referee']);
  const n = ctx.db.need.id.find(needId);
  if (!n) throw new SenderError(`no need ${needId}`);
  if (ctx.db.round.id.find(roundId)) throw new SenderError(`round ${roundId} already exists`);
  if (!(maxStages >= 2)) throw new SenderError('a knockout round needs at least 2 stages');
  const deadline = tsFromMs(ms(ctx.timestamp) + stageWindowS * 1000);
  ctx.db.round.insert({
    id: roundId, needId, openedAt: ctx.timestamp, deadline, extensions: 0, state: 'open', sealedCount: 0, closedAt: undefined,
    origin: n.origin, stage: 1, maxStages, stageWindowS,
  });
  scheduleClose(ctx, roundId, deadline);
  event(ctx, 'round_opened', 'round', roundId, `Knockout stage 1 of ${maxStages} open for ${stageWindowS} s`, '', n.origin);
}

// A bid source is a listing URL or a plain label ("sim:fixture"). Anything starting like a URL must have a host, so "https://"
// alone never reaches a screen. A regex, not new URL(): the module runtime may lack it.
const sourceOk = (s: string) => !/^https?:/i.test(s) || /^https?:\/\/[^\s/?#]+[^\s]*$/i.test(s);

export interface PlaceBidArgs {
  id: string; roundId: string; persona: string; lines: Line[]; statedTotal: number; perks: string[]; claims: string[];
  origin: string; source: string;
}

export function placeBid(ctx: Ctx, a: PlaceBidArgs) {
  const me = { sellerId: requireRole(ctx, 'place_bid', ['seller']).subjectId };
  const r = ctx.db.round.id.find(a.roundId);
  if (!r) throw new SenderError(`no round ${a.roundId}`);
  if (!a.lines.length) throw new SenderError('a bid has at least one line');
  if (!sourceOk(a.source)) throw new SenderError('source looks like a URL but has no host (send a full http(s) URL or a plain label)');
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
  for (const b of ctx.db.bid.roundId.filter(a.roundId)) {
    if (b.sellerId === me.sellerId && b.stage === r.stage) throw new SenderError('one offer per seller per stage');
  }
  // #336: a stage > 1 knockout round. Only a seller the previous stage marked "advancing" may offer again,
  // and strictly below its own previous offer on any SKU it already bid (its floor still applies as below).
  if (r.stage > 1) {
    const prevResult = [...ctx.db.roundResult.roundId.filter(a.roundId)].find((x) => x.stage === r.stage - 1 && x.sellerId === me.sellerId);
    if (!prevResult || prevResult.status !== 'advancing') throw new SenderError('not a surviving seller in this round');
    const priorBid = [...ctx.db.bid.roundId.filter(a.roundId)].filter((b) => b.sellerId === me.sellerId).sort((x, y) => y.stage - x.stage)[0];
    if (priorBid) {
      for (const l of a.lines) {
        const pl = priorBid.lines.find((p: Line) => p.skuSpec === l.skuSpec);
        if (pl && !(l.unitPrice < pl.unitPrice)) throw new SenderError('a later-stage offer must be strictly below your own previous offer');
      }
    }
  }
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
    origin: a.origin, source: a.source, sealedAt: ctx.timestamp, lineRejects: fc.lineRejects, stage: r.stage,
  });
  const deadline = tsFromMs(timing.auction.deadline_ms);
  ctx.db.round.id.update({ ...r, sealedCount: r.sealedCount + 1, extensions: timing.auction.extensions, deadline });
  if (timing.extended) scheduleClose(ctx, a.roundId, deadline);
  // #H1: no public event here. A bid id embeds its seller and a rejection names the seller floor, so either
  // one would tell a rival still bidding who is in and who is out; the round (or stage) close emits them,
  // via emitBidArrivalEvents below. The public round row still counts sealed bids (sealedCount).
}

/**
 * #H1: the public events for the bids a round or stage close just revealed: "A sealed bid arrived" or "Bid
 * rejected: below this seller floor", each stamped with the moment its bid really arrived (not the close),
 * in arrival order, so the web's arrival timeline is unchanged. Nothing about a bid is public before this.
 */
function emitBidArrivalEvents(ctx: Ctx, bids: Iterable<BidRow>) {
  const sorted = [...bids].sort((x, y) => (x.sealedAt.microsSinceUnixEpoch < y.sealedAt.microsSinceUnixEpoch ? -1 : x.sealedAt.microsSinceUnixEpoch > y.sealedAt.microsSinceUnixEpoch ? 1 : x.id < y.id ? -1 : 1));
  for (const b of sorted) {
    if (b.floorCheckPassed) event(ctx, 'bid_sealed', 'bid', b.id, 'A sealed bid arrived', b.sellerId, b.origin, b.sealedAt);
    else event(ctx, 'bid_rejected', 'bid', b.id, 'Bid rejected: below this seller floor', b.sellerId, b.origin, b.sealedAt);
  }
}

/**
 * #H1 (red team): emit the public event for one check row attached to a bid. Called immediately only when
 * the bid's round is already closed (a late check, #389's defense in depth, leaks nothing new); otherwise
 * the round or stage close that reveals this bid's outcome flushes it, via emitBidCheckEvents below. Before
 * that, a rival still bidding must never learn from the public floor that this seller carries a flag.
 */
function emitOneBidCheckEvent(ctx: Ctx, bidId: string, c: { kind: string; result: string; detail: string; origin: string }) {
  if (c.kind === 'shield') event(ctx, 'verdict', 'bid_check', bidId, `Bazaar Shield: ${c.result}`, '', c.origin);
  else if (c.kind === 'claim') event(ctx, 'claim_checked', 'bid_check', bidId, `Claim check: ${c.result}`, '', c.origin);
  else if (c.kind === 'advocate') {
    const ruleId = c.detail.includes(': ') ? c.detail.slice(0, c.detail.indexOf(': ')) : c.detail;
    event(ctx, 'advocate_card', 'bid_check', bidId, c.result === 'veto' ? `Advocate veto (${ruleId})` : `Advocate: ${c.result}`, '', c.origin);
  }
}

/** #H1: flush every check already attached to a bid whose outcome a round close just revealed. None of
 * them has had a public event yet, since attach deferred it until now (see the attach_* reducers below). */
function emitBidCheckEvents(ctx: Ctx, bidId: string) {
  for (const c of ctx.db.bidCheck.bidId.filter(bidId)) emitOneBidCheckEvent(ctx, bidId, c);
}

export function attachVerdict(ctx: Ctx, a: { bidId: string; verdict: string; ruleIds: string[]; origin: string }) {
  requireRole(ctx, 'attach_verdict', ['referee']);
  if (!['allow', 'quarantine', 'block'].includes(a.verdict)) throw new SenderError('verdict must be allow, quarantine or block');
  // #389: a Shield verdict is allowed on an already-closed round (the demo's beat 3 attaches a block right
  // after close_round) and never changes a ranking already computed. create_mandate re-checks every card on
  // the winning bid before it mints, so a late block still refuses the mandate; it just can't be dropped here.
  const b = ctx.db.bid.id.find(a.bidId);
  if (!b) throw new SenderError(`no bid ${a.bidId}`);
  ctx.db.bidCheck.insert({ id: 0n, bidId: a.bidId, kind: 'shield', result: a.verdict, detail: a.ruleIds.join(', '), evidenceUrl: '', origin: a.origin, at: ctx.timestamp });
  // #H1: a block or quarantine on a still-open round must not reach the public floor before close; see above.
  if (ctx.db.round.id.find(b.roundId)?.state === 'closed') event(ctx, 'verdict', 'bid_check', a.bidId, `Bazaar Shield: ${a.verdict}`, '', a.origin);
}

export function attachClaimCheck(ctx: Ctx, a: { bidId: string; claim: string; check: string; evidenceUrl: string; origin: string }) {
  requireRole(ctx, 'attach_claim_check', ['referee']);
  if (!['verified', 'unverified', 'false'].includes(a.check)) throw new SenderError('check must be verified, unverified or false');
  // #389: late is fine, same as attach_verdict above; create_mandate is the enforcement point, not the attach.
  const b = ctx.db.bid.id.find(a.bidId);
  if (!b) throw new SenderError(`no bid ${a.bidId}`);
  ctx.db.bidCheck.insert({ id: 0n, bidId: a.bidId, kind: 'claim', result: a.check, detail: a.claim, evidenceUrl: a.evidenceUrl, origin: a.origin, at: ctx.timestamp });
  // #H1: see attach_verdict above.
  if (ctx.db.round.id.find(b.roundId)?.state === 'closed') event(ctx, 'claim_checked', 'bid_check', a.bidId, `Claim check: ${a.check}`, '', a.origin);
}

export const ADVOCATE_RECOMMENDATIONS = ['buy', 'caution', 'veto'];

/**
 * The advocate relay (referee) attaches Lane A's card for one bid. A veto disqualifies the bid in the
 * round result with the rule, the text and the cited source; the buyer's feed gets a veto line. The
 * public floor event names the rule only: never the seller, the text or a price.
 */
export function attachAdvocateCard(
  ctx: Ctx,
  a: { bidId: string; recommendation: string; ruleId: string; text: string; sourceUrl: string; origin: string },
) {
  requireRole(ctx, 'attach_advocate_card', ['referee']);
  if (!ADVOCATE_RECOMMENDATIONS.includes(a.recommendation)) throw new SenderError(`recommendation must be one of ${ADVOCATE_RECOMMENDATIONS.join(', ')}`);
  const b = ctx.db.bid.id.find(a.bidId);
  if (!b) throw new SenderError(`no bid ${a.bidId}`);
  const veto = a.recommendation === 'veto';
  if (veto && !a.sourceUrl) throw new SenderError('an advocate veto must cite a source');
  if (veto && (!a.ruleId || !a.text)) throw new SenderError('an advocate veto needs a rule id and a text');
  if (ctx.db.round.id.find(b.roundId)?.state === 'closed') throw new SenderError('round already closed; a card can no longer change its ranking');
  ctx.db.bidCheck.insert({
    id: 0n, bidId: a.bidId, kind: 'advocate', result: a.recommendation, detail: `${a.ruleId}: ${a.text}`, evidenceUrl: a.sourceUrl,
    origin: a.origin, at: ctx.timestamp,
  });
  // #H1: a round already closed never reaches here (the guard above throws), so this event always waits
  // for close to flush it (emitBidCheckEvents), the same as attach_verdict and attach_claim_check.
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

// ---------------------------------------------------------------- stock holds (rules/holds)

type HoldRow = NonNullable<ReturnType<Ctx['db']['stockHold']['id']['find']>>;
const asHoldLike = (r: HoldRow): HoldLike => ({
  sellerId: r.sellerId, skuSpec: r.skuSpec, condition: r.condition, qty: r.qty, state: r.state as HoldState, expiresAtMs: ms(r.expiresAt),
});

/** A hold past its expiry becomes released (the unit is free again). Runs before any availability check. */
function sweepExpiredHolds(ctx: Ctx) {
  for (const hd of [...ctx.db.stockHold.iter()]) {
    if (hd.state === 'held' && ms(hd.expiresAt) <= ms(ctx.timestamp)) {
      ctx.db.stockHold.id.update({ ...hd, state: 'released' });
      event(ctx, 'stock_released', 'stock_hold', hd.bidId, 'A held unit was released: its approval window ended', hd.sellerId);
    }
  }
}

/**
 * Per bid, per line: SOLD_OUT_REASON when stock held or sold by a round for a different need leaves too few units, else ''.
 * Expired holds are swept first. Only other needs count: replaying the same need (the demo's round 2) must not compete with its
 * own earlier sale, while a second buyer's round still meets the held or sold unit. close_round and close_stage share it (#449 RT-23).
 */
function soldOutLines(ctx: Ctx, needId: string, rows: readonly BidRow[], needItems: Map<string, NeedItem>): Map<string, string[]> {
  sweepExpiredHolds(ctx);
  const nowMs = ms(ctx.timestamp);
  const needQtyOf = (sku: string) => needItems.get(sku)?.quantity ?? 1;
  const sameNeed = (h: HoldRow) => ctx.db.round.id.find(h.roundId)?.needId === needId;
  const soldOut = new Map<string, string[]>();
  for (const b of rows) {
    const held = [...ctx.db.stockHold.sellerId.filter(b.sellerId)].filter((h) => !sameNeed(h)).map(asHoldLike);
    soldOut.set(b.id, soldOutReasons(
      b.lines.map((l: Line) => ({ skuSpec: l.skuSpec, condition: l.offeredCondition || needItems.get(l.skuSpec)?.condition || 'new', quantity: l.quantity })),
      held, b.sellerId, nowMs, needQtyOf,
    ));
  }
  return soldOut;
}

/** A deal id names its awarded bid as `<bid id>`, `deal-<bid id>` or `<round id>:<bid id>`. */
export function bidIdOfDeal(dealId: string): string {
  const d = dealId.startsWith('deal-') ? dealId.slice(5) : dealId;
  return d.slice(d.lastIndexOf(':') + 1);
}

/**
 * Move the units held for a mandate's deal: `held` renews the 2 minute window (the call starts it), `sold` ends it for good.
 * A hold that was released is claimed again only if the seller still has the stock; if another round took it the call
 * throws, so nothing is oversold. A deal that names no awarded bid touches nothing.
 */
function claimDealUnits(ctx: Ctx, dealId: string, buyerId: string, to: 'held' | 'sold') {
  const bidId = bidIdOfDeal(dealId);
  // The deal belongs to the buyer whose need the bid answered, from the bid itself, so the owner is known before any hold
  // exists (bid ids are public while the round is open). A deal that names no bid has no owner and is left alone.
  const bidOwner = ctx.db.need.id.find(ctx.db.bid.id.find(bidId)?.needId ?? '')?.buyerId;
  if (bidOwner !== undefined && bidOwner !== buyerId) throw new SenderError('not your deal');
  const mine = [...ctx.db.stockHold.bidId.filter(bidId)];
  if (!mine.length) return;
  const now = ms(ctx.timestamp);
  for (const hd of mine) {
    // A hold agrees: nobody but the buyer whose need the round served can renew, lock or pay for its unit.
    const owner = ctx.db.need.id.find(ctx.db.round.id.find(hd.roundId)?.needId ?? '')?.buyerId;
    if (owner !== buyerId) throw new SenderError('not your deal');
    // A unit already sold is gone: a second mandate, approval or payment on it can never sell it again.
    if (hd.state === 'sold') throw new SenderError(`${SOLD_OUT_REASON}; the deal must be re-quoted`);
    const active = hd.state === 'held' && ms(hd.expiresAt) > now;
    if (!active) {
      const bidRow = ctx.db.bid.id.find(bidId);
      const needCond = new Map([...ctx.db.needItem.needId.filter(bidRow?.needId ?? '')].map((i) => [i.skuSpec, i.condition]));
      const stock = bidRow?.lines.find((l: Line) => l.skuSpec === hd.skuSpec && (l.offeredCondition || needCond.get(l.skuSpec) || 'new') === hd.condition)?.quantity ?? 0;
      const others = [...ctx.db.stockHold.sellerId.filter(hd.sellerId)].filter((x) => x.id !== hd.id).map(asHoldLike);
      if (availableStock(stock, others, hd.sellerId, hd.skuSpec, hd.condition, now) < hd.qty) {
        throw new SenderError(`${SOLD_OUT_REASON}; the deal must be re-quoted`);
      }
      event(ctx, 'stock_held', 'stock_hold', hd.bidId, 'A released unit was held again for its own deal', hd.sellerId);
    }
    ctx.db.stockHold.id.update({ ...hd, state: to, expiresAt: to === 'held' ? tsFromMs(now + HOLD_TTL_MS) : hd.expiresAt });
    if (to === 'sold') event(ctx, 'stock_sold', 'stock_hold', hd.bidId, 'A held unit was sold: the payment was recorded', hd.sellerId);
  }
}

export function closeRound(ctx: Ctx, { roundId }: { roundId: string }) {
  requireRole(ctx, 'close_round', ['referee']);
  return closeRoundInner(ctx, roundId, false);
}

/** Body of the scheduled reducer: only the module itself (the scheduler) may run it. */
export function closeRoundOnDeadline(ctx: Ctx, roundId: string) {
  requireRole(ctx, 'close_round_on_deadline (the deadline scheduler)', ['scheduler']);
  const r = ctx.db.round.id.find(roundId);
  if (r && r.maxStages > 1) return closeStageInner(ctx, roundId, true);
  return closeRoundInner(ctx, roundId, true);
}

/** #336: close the current stage of a knockout round (referee) or let the scheduler do it on deadline. */
export function closeStage(ctx: Ctx, { roundId }: { roundId: string }) {
  requireRole(ctx, 'close_stage', ['referee']);
  return closeStageInner(ctx, roundId, false);
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
    needItems.set(i.skuSpec, {
      sku_spec: i.skuSpec, condition: i.condition as Condition, allowed_conditions: i.allowedConditions as Condition[],
      variant: i.variant, quantity: i.quantity, unit: i.unit,
    });
  }
  const rows = [...ctx.db.bid.roundId.filter(roundId)];
  const rejections = new Map<string, string[]>();
  const heldBack = new Map<string, string>();
  const verified = new Map<string, number>();
  for (const b of rows) {
    const reasons: string[] = [];
    if (!b.floorCheckPassed) reasons.push('below this seller floor');
    for (const c of ctx.db.bidCheck.bidId.filter(b.id)) {
      if (c.kind === 'shield' && c.result !== 'allow') reasons.push(`Bazaar Shield ${c.result}: ${c.detail}`);
      if (c.kind === 'claim' && c.result === 'false') reasons.push(`claim did not match the page: ${c.detail}`);
      if (c.kind === 'claim' && c.result === 'verified') verified.set(b.id, (verified.get(b.id) ?? 0) + 1);
      if (c.kind === 'advocate' && c.result === 'veto') reasons.push(`Advocate veto (${c.detail}) [source: ${c.evidenceUrl}]`);
    }
    // #191: the latest advocate card decides; caution (fit unconfirmed) ranks below confirmed bids and says so.
    const cards = [...ctx.db.bidCheck.bidId.filter(b.id)].filter((c) => c.kind === 'advocate').sort((x, y) => (x.id < y.id ? -1 : 1));
    const card = cards[cards.length - 1];
    if (card?.result === 'caution') heldBack.set(b.id, `held back: advocate caution (${card.detail})`);
    if (reasons.length) rejections.set(b.id, reasons);
  }
  // The seller fee is deliberately not passed: it never feeds ranking (invariant 8).
  const spendLimit = ctx.db.need.id.find(r.needId)?.spendLimit;
  // A line whose units are held or sold by an earlier round is skipped with a reason, like a line with no floor.
  const nowMs = ms(ctx.timestamp);
  const needQtyOf = (sku: string) => needItems.get(sku)?.quantity ?? 1;
  const condOfLine = (l: Line) => l.offeredCondition || needItems.get(l.skuSpec)?.condition || 'new';
  const soldOut = soldOutLines(ctx, r.needId, rows, needItems);
  const lineRejects = new Map(rows.map((b) => [b.id, b.lines.map((_: Line, i: number) => b.lineRejects[i] || soldOut.get(b.id)![i] || '')]));
  const ranked = rankBids(rows.map(toBid), {
    needItems, rejections, lineRejects, spendLimit, heldBack, quality: MARKET_CONFIG.quality, verifiedClaims: (b) => verified.get(b.id) ?? 0,
  });
  const byId = new Map(rows.map((b) => [b.id, b]));
  for (const x of ranked.ranked) {
    const b = byId.get(x.bid.id)!;
    // The lines are the picked alternatives (the cheapest allowed line per SKU), the ones the rank is about.
    // adjusted_total is the real score rankBids sorted on (equal to landed when nothing adjusted it).
    const pickedLines = x.picked.map((i) => x.bid.lines[i]!);
    ctx.db.roundResult.insert({
      id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: x.rank, landed: x.landed, reasons: heldBack.has(b.id) ? [heldBack.get(b.id)!] : [],
      lines: x.picked.map((i) => b.lines[i]!), origin: b.origin, source: b.source,
      adjustedTotal: x.score, adjustmentReason: adjustmentReason(x.bid, pickedLines, needItems, MARKET_CONFIG.quality), stage: 1, status: '',
    });
  }
  for (const d of ranked.disqualified) {
    const b = byId.get(d.bid.id)!;
    // Never ranked, so there is no adjusted score to show: adjusted_total stays the landed price.
    ctx.db.roundResult.insert({
      id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: 0, landed: d.landed, reasons: d.reasons,
      lines: b.lines, origin: b.origin, source: b.source, adjustedTotal: d.landed, adjustmentReason: '', stage: 1, status: '',
    });
  }
  ctx.db.round.id.update({ ...r, state: 'closed', closedAt: ctx.timestamp });
  // #H1 (red team): every bid arrival and every check attached while this round was open had its public
  // event deferred; the round's result is revealed now anyway, so flush them all.
  emitBidArrivalEvents(ctx, rows);
  for (const b of rows) emitBidCheckEvents(ctx, b.id);
  const top = ranked.ranked[0];
  for (const b of rows) {
    if (soldOut.get(b.id)!.some((x) => x)) event(ctx, 'stock_sold_out', 'bid', b.id, `A bid line was ${SOLD_OUT_REASON}`, b.sellerId, b.origin);
  }
  if (top) {
    // The awarded line holds its units for the approval call, so a round that closes later cannot award them too.
    const won = byId.get(top.bid.id)!;
    for (const i of top.picked) {
      const l = won.lines[i]!;
      ctx.db.stockHold.insert({
        id: 0n, sellerId: won.sellerId, skuSpec: l.skuSpec, condition: condOfLine(l), qty: needQtyOf(l.skuSpec), roundId, bidId: won.id,
        expiresAt: tsFromMs(nowMs + HOLD_TTL_MS), state: 'held',
      });
      event(ctx, 'stock_held', 'stock_hold', won.id, 'A unit is held for the round winner during the approval call', won.sellerId, r.origin);
    }
  }
  event(ctx, 'auction_closed', 'round', roundId, top ? `Round closed: ${ranked.ranked.length} ranked, ${ranked.disqualified.length} out` : 'Round closed: no eligible bid', top?.bid.seller_id ?? '', r.origin);
}

/**
 * Close a knockout round (a champion, no survivor, or no bid at all) and reveal everything held back while it
 * was open: the deferred check events of every bid in the round, and the real rank, landed price and lines of
 * each knocked_out row a continuing stage published blank (see roundResultSealed in schema.ts).
 */
function closeKnockoutRound(ctx: Ctx, r: NonNullable<ReturnType<Ctx['db']['round']['id']['find']>>, allBids: readonly BidRow[]) {
  ctx.db.round.id.update({ ...r, state: 'closed', closedAt: ctx.timestamp });
  for (const b of allBids) emitBidCheckEvents(ctx, b.id);
  for (const held of [...ctx.db.roundResultSealed.roundId.filter(r.id)]) {
    const pub = ctx.db.roundResult.id.find(held.resultId);
    if (pub) ctx.db.roundResult.id.update({ ...pub, rank: held.rank, landed: held.landed, lines: held.lines, adjustedTotal: held.adjustedTotal });
    ctx.db.roundResultSealed.resultId.delete(held.resultId);
  }
}

/**
 * #336: close one stage of a knockout round. Knocks out every rule-breaker (Shield block, failed claim,
 * advocate veto, below floor) plus the single last-placed clean survivor. One left: champion at once, closing
 * the round. None left: the round closes with no deal. More than one at the final stage: the best of them wins
 * outright. More than one before the final stage: the rest advance to the next stage.
 */
function closeStageInner(ctx: Ctx, roundId: string, fromTimer: boolean) {
  const r = ctx.db.round.id.find(roundId);
  if (!r) throw new SenderError(`no round ${roundId}`);
  if (r.maxStages <= 1) throw new SenderError('not a knockout round; use close_round');
  if (r.state === 'closed') {
    if (fromTimer) return;
    throw new SenderError('round already closed');
  }
  if (!isClosed(clockOf(r), ms(ctx.timestamp))) {
    if (fromTimer) return scheduleClose(ctx, roundId, r.deadline);
    throw new SenderError('round is still open until its deadline');
  }

  const stage = r.stage;
  const needItems = new Map<string, NeedItem>();
  for (const i of ctx.db.needItem.needId.filter(r.needId)) {
    needItems.set(i.skuSpec, {
      sku_spec: i.skuSpec, condition: i.condition as Condition, allowed_conditions: i.allowedConditions as Condition[],
      variant: i.variant, quantity: i.quantity, unit: i.unit,
    });
  }
  const allBids = [...ctx.db.bid.roundId.filter(roundId)];
  const thisStageBids = allBids.filter((b) => b.stage === stage);
  // #H1: this stage's bids are revealed by this close (the result rows below name every one), so their
  // arrival events go out now, before the knockout events; the next stage's bids stay hidden until theirs.
  emitBidArrivalEvents(ctx, thisStageBids);
  const survivorIds = stage === 1
    ? [...new Set(thisStageBids.map((b) => b.sellerId))]
    : [...ctx.db.roundResult.roundId.filter(roundId)].filter((x) => x.stage === stage - 1 && x.status === 'advancing').map((x) => x.sellerId);

  // A survivor who placed no new offer this stage keeps competing on its most recent earlier offer.
  const bySeller = new Map<string, BidRow>();
  for (const b of thisStageBids) bySeller.set(b.sellerId, b);
  for (const sid of survivorIds) {
    if (bySeller.has(sid)) continue;
    const prior = allBids.filter((b) => b.sellerId === sid && b.stage < stage).sort((x, y) => y.stage - x.stage)[0];
    if (prior) bySeller.set(sid, prior);
  }
  const rows = survivorIds.map((sid) => bySeller.get(sid)).filter((b): b is BidRow => !!b);

  if (rows.length === 0) {
    closeKnockoutRound(ctx, r, allBids);
    event(ctx, 'auction_closed', 'round', roundId, 'Round closed: no eligible bid', '', r.origin);
    return;
  }

  const rejections = new Map<string, string[]>();
  const heldBack = new Map<string, string>();
  const verified = new Map<string, number>();
  for (const b of rows) {
    const reasons: string[] = [];
    if (!b.floorCheckPassed) reasons.push('below this seller floor');
    for (const c of ctx.db.bidCheck.bidId.filter(b.id)) {
      if (c.kind === 'shield' && c.result !== 'allow') reasons.push(`Bazaar Shield ${c.result}: ${c.detail}`);
      if (c.kind === 'claim' && c.result === 'false') reasons.push(`claim did not match the page: ${c.detail}`);
      if (c.kind === 'claim' && c.result === 'verified') verified.set(b.id, (verified.get(b.id) ?? 0) + 1);
      if (c.kind === 'advocate' && c.result === 'veto') reasons.push(`Advocate veto (${c.detail}) [source: ${c.evidenceUrl}]`);
    }
    // #266: a caution bid (fit unconfirmed) must be held back here too, or it can be crowned champion on price alone.
    const cards = [...ctx.db.bidCheck.bidId.filter(b.id)].filter((c) => c.kind === 'advocate').sort((x, y) => (x.id < y.id ? -1 : 1));
    const card = cards[cards.length - 1];
    if (card?.result === 'caution') heldBack.set(b.id, `held back: advocate caution (${card.detail})`);
    if (reasons.length) rejections.set(b.id, reasons);
  }
  const spendLimit = ctx.db.need.id.find(r.needId)?.spendLimit;
  // #449 RT-23: the same hold sweep and sold-out check close_round runs. A line whose unit another need's round holds or sold is
  // skipped with a reason, so a champion is always crowned on a line that still has stock (its hold below needs no second check).
  const soldOut = soldOutLines(ctx, r.needId, rows, needItems);
  const lineRejects = new Map(rows.map((b) => [b.id, b.lines.map((_: Line, i: number) => b.lineRejects[i] || soldOut.get(b.id)![i] || '')]));
  for (const b of rows) {
    if (soldOut.get(b.id)!.some((x) => x)) event(ctx, 'stock_sold_out', 'bid', b.id, `A bid line was ${SOLD_OUT_REASON}`, b.sellerId, b.origin);
  }
  const ranked = rankBids(rows.map(toBid), {
    needItems, rejections, lineRejects, spendLimit, heldBack, quality: MARKET_CONFIG.quality, verifiedClaims: (b) => verified.get(b.id) ?? 0,
  });
  const byId = new Map(rows.map((b) => [b.id, b]));
  const nowMs = ms(ctx.timestamp);
  const condOfLine = (l: Line) => l.offeredCondition || needItems.get(l.skuSpec)?.condition || 'new';
  const needQtyOf = (sku: string) => needItems.get(sku)?.quantity ?? 1;

  // Among the clean (non-rule-breaking) bids, the last-placed one also goes out, unless only one remains.
  const clean = ranked.ranked;
  const lastPlaced = clean.length > 1 ? clean[clean.length - 1]!.bid.id : undefined;
  const survivors = clean.filter((x) => x.bid.id !== lastPlaced);
  const atFinalStage = stage >= r.maxStages;
  const championId = survivors.length === 1 ? survivors[0]!.bid.id : atFinalStage ? survivors[0]!.bid.id : undefined;

  // #H2 (red team): when this stage leaves the round open, a knocked_out row is public while rivals still bid,
  // so it shows no rank, landed price, lines or adjusted score; the real values wait in roundResultSealed
  // until closeKnockoutRound reveals them. When this stage closes the round, the rows carry the real values.
  const roundStaysOpen = survivors.length > 0 && !championId;
  const insertKnockedOut = (row: Parameters<typeof ctx.db.roundResult.insert>[0]) => {
    if (!roundStaysOpen) { ctx.db.roundResult.insert(row); return; }
    const pub = ctx.db.roundResult.insert({ ...row, rank: 0, landed: 0, lines: [], adjustedTotal: 0 });
    ctx.db.roundResultSealed.insert({ resultId: pub.id, roundId, rank: row.rank, landed: row.landed, lines: row.lines, adjustedTotal: row.adjustedTotal });
  };

  for (const d of ranked.disqualified) {
    const b = byId.get(d.bid.id)!;
    insertKnockedOut({
      id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: 0, landed: d.landed, reasons: d.reasons,
      lines: b.lines, origin: b.origin, source: b.source, adjustedTotal: d.landed, adjustmentReason: '', stage, status: 'knocked_out',
    });
    event(ctx, 'knockout', 'bid', b.id, `Seller knocked out (stage ${stage})`, b.sellerId, b.origin);
  }

  if (lastPlaced) {
    const x = clean[clean.length - 1]!;
    const b = byId.get(lastPlaced)!;
    insertKnockedOut({
      id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: x.rank, landed: x.landed,
      reasons: ['knocked out: last placed this stage'], lines: x.picked.map((i) => b.lines[i]!), origin: b.origin, source: b.source,
      adjustedTotal: x.score, adjustmentReason: '', stage, status: 'knocked_out',
    });
    event(ctx, 'knockout', 'bid', b.id, `Seller knocked out (stage ${stage})`, b.sellerId, b.origin);
  }

  if (survivors.length === 0) {
    closeKnockoutRound(ctx, r, allBids);
    event(ctx, 'auction_closed', 'round', roundId, 'Round closed: no eligible bid', '', r.origin);
    return;
  }

  if (championId) {
    for (const x of survivors) {
      const b = byId.get(x.bid.id)!;
      const isChamp = x.bid.id === championId;
      const pickedLines = x.picked.map((i) => x.bid.lines[i]!);
      ctx.db.roundResult.insert({
        id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: isChamp ? 1 : x.rank + 1, landed: x.landed,
        reasons: isChamp ? (heldBack.has(b.id) ? [heldBack.get(b.id)!] : []) : ['did not advance: final stage'], lines: x.picked.map((i) => b.lines[i]!), origin: b.origin, source: b.source,
        adjustedTotal: x.score, adjustmentReason: isChamp ? adjustmentReason(x.bid, pickedLines, needItems, MARKET_CONFIG.quality) : '',
        stage, status: isChamp ? 'champion' : 'knocked_out',
      });
      if (!isChamp) event(ctx, 'knockout', 'bid', b.id, `Seller knocked out (stage ${stage})`, b.sellerId, b.origin);
    }
    closeKnockoutRound(ctx, r, allBids);
    const champX = survivors.find((x) => x.bid.id === championId)!;
    const champ = byId.get(championId)!;
    for (const i of champX.picked) {
      const l = champ.lines[i]!;
      ctx.db.stockHold.insert({
        id: 0n, sellerId: champ.sellerId, skuSpec: l.skuSpec, condition: condOfLine(l), qty: needQtyOf(l.skuSpec), roundId, bidId: champ.id,
        expiresAt: tsFromMs(nowMs + HOLD_TTL_MS), state: 'held',
      });
      event(ctx, 'stock_held', 'stock_hold', champ.id, 'A unit is held for the round winner during the approval call', champ.sellerId, r.origin);
    }
    event(ctx, 'auction_closed', 'round', roundId, `Round closed: champion after stage ${stage}`, champ.sellerId, r.origin);
    return;
  }

  // #266/#363: round_result is public; a mid-round 'advancing' row must never reveal a still-live seller's price
  // (landed, lines, adjusted_total) or relative standing (rank) to a role-less reader before the round actually
  // closes. Only who is still in, and why, is public; the sealed bid table (private) keeps the real numbers and
  // ranking until a stage crowns a champion.
  for (const x of survivors) {
    const b = byId.get(x.bid.id)!;
    ctx.db.roundResult.insert({
      id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: 0, landed: 0, reasons: heldBack.has(b.id) ? [heldBack.get(b.id)!] : [],
      lines: [], origin: b.origin, source: b.source, adjustedTotal: 0, adjustmentReason: '',
      stage, status: 'advancing',
    });
  }
  const nextDeadline = tsFromMs(nowMs + r.stageWindowS * 1000);
  ctx.db.round.id.update({ ...r, stage: stage + 1, deadline: nextDeadline, extensions: 0 });
  scheduleClose(ctx, roundId, nextDeadline);
  event(ctx, 'round_opened', 'round', roundId, `Knockout stage ${stage + 1} of ${r.maxStages} open for ${r.stageWindowS} s`, '', r.origin);
}

// ---------------------------------------------------------------- mandate, approval, payment

export const MANDATE_MAX_EXPIRY_MIN = 10;
export const APPROVAL_METHODS = ['voice_code', 'allowance'];

/** MOCK until Vidyut's Mandate lands: same fields as the 00-shared shape. */
export function createMandate(
  ctx: Ctx,
  a: {
    hash: string; id: string; dealId: string; buyerId: string; amount: number; payee: string; expiryMinutes: number; nonce: string;
    requestedBy: string; origin: string;
  },
) {
  requireRole(ctx, 'create_mandate', ['referee']);
  if (ctx.db.mandate.hash.find(a.hash)) throw new SenderError('mandate hash already exists');
  // #191: a mandate exists only for the round's real winner, paid to that seller, at its landed price, for minutes.
  const bid = ctx.db.bid.id.find(bidIdOfDeal(a.dealId));
  const round = bid ? ctx.db.round.id.find(bid.roundId) : undefined;
  // #336: a knockout round can carry a seller's bid id forward across stages, so take its latest-stage result.
  const myResults = bid ? [...ctx.db.roundResult.roundId.filter(bid.roundId)].filter((r) => r.bidId === bid.id) : [];
  const won = myResults.length ? myResults.reduce((a, b) => (b.stage > a.stage ? b : a)) : undefined;
  // #266: a knockout stage's rank-1 'advancing' row is not a win yet; only round.state closed and, for a
  // knockout round, status champion actually crowns a winner. A stale advancing row must never get a mandate.
  const actuallyWon = won && round?.state === 'closed' && (round.maxStages <= 1 || won.status === 'champion');
  if (!bid || !round || !actuallyWon || won!.rank !== 1) throw new SenderError('a mandate needs the rank 1 bid of a closed round');
  // #325: a Shield block, a failed claim check or an advocate veto attached to the winning bid (even after the
  // round closed) must still refuse the mandate; the ranking having run before the card arrived is not a defense.
  const lateChecks = [...ctx.db.bidCheck.bidId.filter(bid.id)];
  const blocked = lateChecks.some((c) => (c.kind === 'shield' && c.result !== 'allow') || (c.kind === 'claim' && c.result === 'false') || (c.kind === 'advocate' && c.result === 'veto'));
  if (blocked) throw new SenderError('the winning bid carries a Shield block, a failed claim check or an advocate veto');
  if (a.payee !== bid.sellerId) throw new SenderError(`payee must be the winning seller (${bid.sellerId})`);
  // #325: NaN must never pass as "equal to the landed price" (Math.abs(NaN - x) > 1e-9 is false).
  if (!Number.isFinite(a.amount) || !(Math.abs(a.amount - won.landed) <= 1e-9)) throw new SenderError('amount must equal the winning landed price');
  if (!(Number.isInteger(a.expiryMinutes) && a.expiryMinutes >= 1 && a.expiryMinutes <= MANDATE_MAX_EXPIRY_MIN)) {
    throw new SenderError(`expiry must be 1 to ${MANDATE_MAX_EXPIRY_MIN} minutes`);
  }
  // #449 item 3 RT-11: one live mandate per deal. A live one is not expired, has no payment row and was not denied.
  const wantBid = bidIdOfDeal(a.dealId);
  const denied = (hash: string) => [...ctx.db.rejectedAttempt.iter()].some((r) => r.kind === 'approval' && r.refId === hash && r.reason.startsWith('Approval denied'));
  for (const old of ctx.db.mandate.iter()) {
    if (bidIdOfDeal(old.dealId) !== wantBid || ms(ctx.timestamp) > ms(old.expiry)) continue;
    if (ctx.db.payment.mandateHash.find(old.hash) || denied(old.hash)) continue;
    throw new SenderError('this deal already has a live mandate; wait for it to be paid, denied or expired');
  }
  claimDealUnits(ctx, a.dealId, a.buyerId, 'held');
  const allow = allowanceFor(ctx, a.buyerId);
  const d = decide(allow, a.amount, ms(ctx.timestamp));
  const within = d.path === 'auto';
  ctx.db.mandate.insert({
    hash: a.hash, id: a.id, dealId: a.dealId, buyerId: a.buyerId, amount: a.amount, payee: a.payee,
    expiry: tsFromMs(ms(ctx.timestamp) + a.expiryMinutes * 60_000), nonce: a.nonce, withinAllowance: within,
    requestedBy: a.requestedBy, origin: a.origin,
  });
  // #191: one neutral public label, so the floor never shows which side of the allowance a deal fell.
  event(ctx, 'mandate_created', 'mandate', a.hash, 'Deal ready for approval', a.payee, a.origin);
  if (within) {
    // Inside the allowance: approved by the buyer's own standing rule, with a receipt.
    ctx.db.approval.insert({ id: 0n, mandateHash: a.hash, method: 'allowance', approvedBy: a.buyerId, at: ctx.timestamp, voiceApprovalId: '' });
    saveAllowance(ctx, recordAutoSpend(allow, a.amount, ms(ctx.timestamp)));
    ctx.db.notification.insert({ id: 0n, buyerId: a.buyerId, goalId: '', klass: 'deal_found', text: `Bought within your allowance: ${d.reason}. Receipt for deal ${a.dealId}.`, push: false, at: ctx.timestamp });
    // #325: one neutral public label, so the floor never shows which side of the allowance a deal fell on.
    event(ctx, 'approval_recorded', 'approval', a.hash, 'Deal approved', a.payee, a.origin);
  } else {
    ctx.db.notification.insert({ id: 0n, buyerId: a.buyerId, goalId: '', klass: 'state', text: `Call needed: ${d.reason}.`, push: true, at: ctx.timestamp });
  }
}

export const APPROVAL_CODE_MAX_FAILURES = 3;

export function recordApproval(ctx: Ctx, a: { mandateHash: string; method: string; approvedBy: string; voiceApprovalId: string; code: string }) {
  // #191 (LOCKED: approval by phone call only): the referee relays the call result; no buyer screen records an approval.
  requireRole(ctx, 'record_approval', ['referee']);
  if (!APPROVAL_METHODS.includes(a.method)) throw new SenderError(`method must be one of ${APPROVAL_METHODS.join(', ')}`);
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  if (a.method === 'allowance' && !md.withinAllowance) throw new SenderError('this deal is over the allowance; only the call approves it');
  if (a.method === 'voice_code' && !a.voiceApprovalId.trim()) throw new SenderError('a voice approval needs the VoiceApproval id from the call');
  if (a.approvedBy !== md.buyerId) throw new SenderError(`approvedBy must be the mandate's buyer (${md.buyerId})`);
  const sep = requesterMayApprove(md.requestedBy, a.approvedBy);
  if (!sep.ok) throw new SenderError(sep.reasons.join('; '));
  if (ms(ctx.timestamp) > ms(md.expiry)) throw new SenderError('mandate expired; the deal must be re-quoted');
  if (a.method === 'voice_code') checkApprovalCode(ctx, md, a.code);
  if (ctx.db.approval.mandateHash.find(a.mandateHash)) return rejected(ctx, 'approval', a.mandateHash, 'second approval for the same mandate refused');
  claimDealUnits(ctx, md.dealId, md.buyerId, 'held');
  ctx.db.approval.insert({ id: 0n, mandateHash: a.mandateHash, method: a.method, approvedBy: a.approvedBy, at: ctx.timestamp, voiceApprovalId: a.voiceApprovalId.trim() });
  // #325: same neutral label as the allowance path; the method is never shown on the public floor.
  event(ctx, 'approval_recorded', 'approval', a.mandateHash, 'Deal approved', md.payee, md.origin);
}

/**
 * #449 item 3 RT-11: the code the call checked must be the one issued for this mandate (issue_approval_code). A locked row always
 * refuses. A wrong code counts a failure and locks the row at APPROVAL_CODE_MAX_FAILURES. NOTE: the throw rolls the whole reducer
 * back, so on a real server the count itself is not kept (the same reason pair_buyer_screen returns instead of throwing); the money
 * path stays closed either way, because no approval row is written. A whole-build call (one code for many mandates) has the
 * referee issue that code for each mandate it makes, then relay the approval with it.
 */
function checkApprovalCode(ctx: Ctx, md: { hash: string }, code: string) {
  const row = ctx.db.approvalCode.mandateHash.find(md.hash);
  if (!row) throw new SenderError('no approval code was issued for this mandate; the call cannot approve it');
  if (row.locked) throw new SenderError('the approval code is locked after too many wrong codes');
  if (!normCode(code ?? '') || normCode(code) !== row.code) {
    const failures = row.failures + 1;
    ctx.db.approvalCode.mandateHash.update({ ...row, failures, locked: failures >= APPROVAL_CODE_MAX_FAILURES });
    throw new SenderError('the approval code does not match');
  }
}

/**
 * The approval was denied (wrong code, silence, "no"): the units held for this deal go back on sale. The mandate's own buyer
 * or the referee relaying the call result. The public label says nothing about the amount, the buyer or the reason; the
 * reason goes only to the buyer's own feed.
 */
export function denyApproval(ctx: Ctx, a: { mandateHash: string; reason: string }) {
  requireRole(ctx, 'deny_approval', ['buyer', 'referee']);
  const md = ctx.db.mandate.hash.find(a.mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  requireRole(ctx, 'deny_approval', ['buyer', 'referee'], md.buyerId);
  if (ctx.db.approval.mandateHash.find(a.mandateHash)) throw new SenderError('already approved; a denial can no longer release the units');
  for (const hd of [...ctx.db.stockHold.bidId.filter(bidIdOfDeal(md.dealId))]) {
    if (hd.state !== 'held') continue;
    // A mandate can name a bid that did not exist yet, so a denial frees only the holds of the buyer whose need the round
    // served (the same owner test claimDealUnits uses), never a rival's unit.
    if (ctx.db.need.id.find(ctx.db.round.id.find(hd.roundId)?.needId ?? '')?.buyerId !== md.buyerId) continue;
    ctx.db.stockHold.id.update({ ...hd, state: 'released' });
    event(ctx, 'stock_released', 'stock_hold', hd.bidId, 'A held unit was released: the approval was denied', hd.sellerId, md.origin);
  }
  ctx.db.notification.insert({ id: 0n, buyerId: md.buyerId, goalId: '', klass: 'state', text: `Approval denied: ${a.reason.slice(0, 200)}. The deal was not paid.`, push: false, at: ctx.timestamp });
  rejected(ctx, 'approval', a.mandateHash, 'Approval denied; nothing was paid');
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
  const ap = ctx.db.approval.mandateHash.find(a.mandateHash);
  if (!ap) throw new SenderError('no approval row for this mandate hash; payment refused');
  // #449 item 3 RT-11: an expired mandate is never paid, even when its approval row exists.
  if (ms(ctx.timestamp) > ms(md.expiry)) throw new SenderError('mandate expired; the deal must be re-quoted');
  if (a.amount !== md.amount) throw new SenderError('payment amount differs from the mandate amount');
  const auth = authorizePayment({ amount: a.amount, limit_checked: true, approval_id: String(ap.id) }, md.amount);
  if (!auth.ok) throw new SenderError(auth.reasons.join('; '));
  if (ctx.db.payment.mandateHash.find(a.mandateHash)) return rejected(ctx, 'payment', a.mandateHash, 'second payment for the same mandate refused');
  claimDealUnits(ctx, md.dealId, md.buyerId, 'sold');
  ctx.db.payment.insert({ id: 0n, mandateHash: a.mandateHash, paymentRef: a.paymentRef, amount: a.amount, at: ctx.timestamp, mode: a.mode });
  event(ctx, 'payment_recorded', 'payment', a.mandateHash, mode.label, md.payee, mode.origin);
}

// ---------------------------------------------------------------- receiving check

export interface RecordReceivingArgs {
  id: string; orderId: string; skuSpec: string; photoUrl: string; expectedSpecId: string; result: string;
  reasons: string[]; checkedBy: string; origin: string;
}

/**
 * The delivery check, relayed by the referee. A clean one raises the deal's buyer one allowance step, once per deal.
 * #449 PL-20: it was the buyer's call, so a buyer could report their own clean delivery from a browser console and
 * raise their own allowance. Nothing in the web calls it, so there is no buyer path left.
 */
export function recordReceiving(ctx: Ctx, a: RecordReceivingArgs) {
  requireRole(ctx, 'record_receiving', ['referee']);
  const md = ctx.db.mandate.hash.find(a.orderId);
  if (!md) throw new SenderError('no deal with that mandate hash');
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
    event(ctx, 'allowance_raised', 'allowance', '', 'A buyer allowance went up one step', '', a.origin); // #449 item 3 PL-16
  }
}

// ---------------------------------------------------------------- views

const CEILING_STEP = 500;
// A manual comma formatter: views run in the SpacetimeDB runtime, where Intl may be missing.
const usd = (x: number) => `$${String(Math.round(x)).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`;
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

/** #336: a seller's own knockout standing, per round. Never another seller's price or standing. */
export function myStandingView(ctx: VCtx) {
  const r = roleOf(ctx);
  if (r?.role !== 'seller') return [];
  const sellerId = r.subjectId;
  const roundIds = new Set([...ctx.db.bid.iter()].filter((b) => b.sellerId === sellerId).map((b) => b.roundId));
  const out: { roundId: string; stillIn: boolean; reason: string; lastOfferSkuSpec: string; lastOfferPrice: number }[] = [];
  for (const roundId of roundIds) {
    const mine = [...ctx.db.bid.roundId.filter(roundId)].filter((b) => b.sellerId === sellerId).sort((a, b) => a.stage - b.stage);
    const last = mine[mine.length - 1];
    if (!last) continue;
    const results = [...ctx.db.roundResult.roundId.filter(roundId)].filter((x) => x.sellerId === sellerId).sort((a, b) => a.stage - b.stage);
    const latest = results[results.length - 1];
    const stillIn = !latest || latest.status === 'advancing' || latest.status === 'champion';
    const l = last.lines[0];
    out.push({ roundId, stillIn, reason: stillIn ? '' : (latest!.reasons[0] ?? ''), lastOfferSkuSpec: l?.skuSpec ?? '', lastOfferPrice: l?.unitPrice ?? 0 });
  }
  return out;
}

function myBuyerId(ctx: VCtx) {
  const r = roleOf(ctx);
  return r?.role === 'buyer' ? r.subjectId : undefined;
}

/** The caller's role row; the owner has none, so it gets a synthetic one (the /admin page gates on role owner or referee). */
export function myRoleView(ctx: VCtx) {
  const r = roleOf(ctx);
  if (r) return [r];
  const o = ctx.db.owner.id.find(0);
  return o && o.identity.isEqual(ctx.sender) ? [{ identity: ctx.sender, role: 'owner', subjectId: '' }] : [];
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
const normCode = (x: string) => x.trim().toLowerCase().replace(/\s+/g, ' ');

/** Referee (Lane D's approval relay) only: store the word pair it issued for a mandate that still needs the buyer's call. */
export function issueApprovalCode(ctx: Ctx, { mandateHash, code }: { mandateHash: string; code: string }) {
  requireRole(ctx, 'issue_approval_code', ['referee']);
  const md = ctx.db.mandate.hash.find(mandateHash);
  if (!md) throw new SenderError('no mandate with that hash');
  if (ctx.db.approval.mandateHash.find(mandateHash)) throw new SenderError('mandate already approved; no code needed');
  if (!normCode(code)) throw new SenderError('empty code');
  const row = { mandateHash, buyerId: md.buyerId, code: normCode(code), failures: 0, locked: false, issuedAt: ctx.timestamp, amount: 0, payee: '', expiry: Timestamp.UNIX_EPOCH, origin: '' };
  if (ctx.db.approvalCode.mandateHash.find(mandateHash)) ctx.db.approvalCode.mandateHash.update(row);
  else ctx.db.approvalCode.insert(row);
}

/**
 * Referee only: the code for the ONE call that approves a whole build. The build makes its mandates after the call (and
 * create_mandate takes only a closed round's rank 1), so there is no mandate row to key on: the row is keyed by the aggregate
 * mandate hash the runner already computed, and carries its own amount, label and expiry for the buyer's card. Private to the
 * buyer like every approval_code row. A new build code retires the buyer's earlier one, so exactly one is on screen.
 */
export function issueBuildApprovalCode(
  ctx: Ctx,
  a: { mandateHash: string; buyerId: string; amount: number; payee: string; expiryMinutes: number; code: string; origin: string },
) {
  requireRole(ctx, 'issue_build_approval_code', ['referee']);
  if (!a.mandateHash) throw new SenderError('a build code needs the aggregate mandate hash');
  if (ctx.db.mandate.hash.find(a.mandateHash)) throw new SenderError('that hash is a real mandate; use issue_approval_code');
  if (![...ctx.db.role.subjectId.filter(a.buyerId)].some((r) => r.role === 'buyer')) throw new SenderError('no buyer with that id');
  if (!(Number.isFinite(a.amount) && a.amount > 0)) throw new SenderError('the build amount must be above zero');
  if (!(Number.isInteger(a.expiryMinutes) && a.expiryMinutes >= 1 && a.expiryMinutes <= MANDATE_MAX_EXPIRY_MIN)) {
    throw new SenderError(`expiry must be 1 to ${MANDATE_MAX_EXPIRY_MIN} minutes`);
  }
  const code = normCode(a.code);
  if (!code) throw new SenderError('empty code');
  for (const old of [...ctx.db.approvalCode.buyerId.filter(a.buyerId)]) {
    if (old.mandateHash !== a.mandateHash && ms(old.expiry) > 0) ctx.db.approvalCode.mandateHash.update({ ...old, expiry: Timestamp.UNIX_EPOCH });
  }
  const row = {
    mandateHash: a.mandateHash, buyerId: a.buyerId, code, failures: 0, locked: false, issuedAt: ctx.timestamp,
    amount: a.amount, payee: a.payee.slice(0, 120), expiry: tsFromMs(ms(ctx.timestamp) + a.expiryMinutes * 60_000), origin: a.origin,
  };
  if (ctx.db.approvalCode.mandateHash.find(a.mandateHash)) ctx.db.approvalCode.mandateHash.update(row);
  else ctx.db.approvalCode.insert(row);
}

/** Referee only: take a whole-build code off the buyer's screen (the call ended, approved or not). No-op when there is none, so the runner's finally never throws. */
export function clearBuildApprovalCode(ctx: Ctx, { mandateHash }: { mandateHash: string }) {
  requireRole(ctx, 'clear_build_approval_code', ['referee']);
  const row = ctx.db.approvalCode.mandateHash.find(mandateHash);
  if (row && !ctx.db.mandate.hash.find(mandateHash)) ctx.db.approvalCode.mandateHash.update({ ...row, expiry: Timestamp.UNIX_EPOCH });
}

/** This buyer's mandates still waiting for approval, with the code to show on this screen only. */
export function myPendingApprovalsView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  if (!id) return [];
  return [...ctx.db.approvalCode.buyerId.filter(id)].flatMap((ac) => {
    const md = ctx.db.mandate.hash.find(ac.mandateHash);
    if (!md && ms(ac.expiry) > 0) {
      // A live whole-build code (no mandate row yet); a cleared one has its expiry back at the epoch.
      return [{
        mandateHash: ac.mandateHash, mandateId: 'whole build', amount: ac.amount, payee: ac.payee, expiry: ac.expiry, code: ac.code,
        failures: ac.failures, locked: ac.locked, issuedAt: ac.issuedAt, origin: ac.origin,
      }];
    }
    if (!md || ctx.db.approval.mandateHash.find(ac.mandateHash)) return [];
    return [{
      mandateHash: md.hash, mandateId: md.id, amount: md.amount, payee: md.payee, expiry: md.expiry, code: ac.code,
      failures: ac.failures, locked: ac.locked, issuedAt: ac.issuedAt, origin: md.origin,
    }];
  });
}

/**
 * #191-5: the checks on bids in this buyer's own rounds (advocate cards, Shield verdicts, claim checks), so /buyer shows the
 * live veto and Shield cards. Never another buyer's rounds; sellers and strangers see nothing.
 */
export function myBidChecksView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  if (!id) return [];
  return [...ctx.db.need.buyerId.filter(id)].flatMap((n) =>
    [...ctx.db.round.needId.filter(n.id)].flatMap((r) => [...ctx.db.bid.roundId.filter(r.id)]).flatMap((b) =>
      [...ctx.db.bidCheck.bidId.filter(b.id)].map((c) => ({
        id: c.id, bidId: b.id, roundId: b.roundId, sellerId: b.sellerId, persona: b.persona, bidOrigin: b.origin, kind: c.kind,
        result: c.result, detail: c.detail, evidenceUrl: c.evidenceUrl, origin: c.origin, at: c.at,
      })),
    ),
  ).sort((x, y) => (x.id < y.id ? -1 : 1));
}

/** #191-5: this buyer's mandates with their approval and payment rows, so /buyer shows the live approval and receipt cards. */
export function myDealsView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  if (!id) return [];
  return [...ctx.db.mandate.iter()].filter((md) => md.buyerId === id).map((md) => {
    const ap = ctx.db.approval.mandateHash.find(md.hash);
    const pay = ctx.db.payment.mandateHash.find(md.hash);
    return {
      mandateHash: md.hash, mandateId: md.id, dealId: md.dealId, amount: md.amount, payee: md.payee, expiry: md.expiry,
      withinAllowance: md.withinAllowance, origin: md.origin, approvalMethod: ap?.method ?? '', voiceApprovalId: ap?.voiceApprovalId ?? '',
      approvedAt: ap?.at, paymentRef: pay?.paymentRef ?? '', paymentMode: pay?.mode ?? '', paidAt: pay?.at,
    };
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
  const existing = ctx.db.buyerProfile.buyerId.find(buyerId);
  const row = { buyerId, displayName: name.slice(0, 60), origin: 'SIM', phone: existing?.phone ?? '' };
  if (existing) ctx.db.buyerProfile.buyerId.update(row);
  else ctx.db.buyerProfile.insert(row);
}

export function myBuyerProfileView(ctx: VCtx) {
  const id = myBuyerId(ctx);
  const row = id ? ctx.db.buyerProfile.buyerId.find(id) : undefined;
  return row ? [row] : [];
}

// ---------------------------------------------------------------- #374 public telemetry
// Counts only. No amounts, prices, payees, phones or names; nothing per user.

const pct = (sorted: number[], p: number) => (sorted.length ? sorted[Math.max(0, Math.ceil((p / 100) * sorted.length) - 1)]! : 0);

export function telemetryView(ctx: AVCtx) {
  const count = (it: Iterable<unknown>) => { let n = 0; for (const _ of it) n++; return n; };
  const durations: number[] = [];
  let roundsOpened = 0, roundsClosed = 0;
  for (const r of ctx.db.round.iter()) {
    roundsOpened++;
    if (r.state === 'closed' && r.closedAt) { roundsClosed++; durations.push(Math.max(0, ms(r.closedAt) - ms(r.openedAt))); }
  }
  durations.sort((a, b) => a - b);
  let accountsCreated = 0;
  for (const p of ctx.db.buyerProfile.iter()) if (p.buyerId.startsWith('b_')) accountsCreated++; // self sign-ups
  let shieldCatches = 0;
  for (const c of ctx.db.bidCheck.iter()) if (c.kind === 'shield' && c.result !== 'allow') shieldCatches++; // Shield quarantine or block
  let denials = 0, errors = 0;
  for (const x of ctx.db.rejectedAttempt.iter()) {
    if (x.kind === 'approval' && x.reason.startsWith('Approval denied')) denials++; // deny_approval writes this row
    else errors++; // every other refused attempt
  }
  return [{
    accountsCreated,
    goalsPosted: count(ctx.db.goal.iter()), // goal rows
    roundsOpened, // round rows
    roundsClosed, // rounds with state closed and a close time
    bids: count(ctx.db.bid.iter()), // bid rows
    shieldCatches,
    callsPlaced: count(ctx.db.approvalCode.iter()), // approval_code rows: one per approval call issued
    approvals: count(ctx.db.approval.iter()), // approval rows
    denials,
    errors,
    roundP50Ms: pct(durations, 50), // closedAt minus openedAt, nearest rank
    roundP95Ms: pct(durations, 95),
  }];
}

/** One row per agent name in agent_event, sorted by name. */
export function telemetryAgentView(ctx: AVCtx) {
  const by = new Map<string, number>();
  for (const e of ctx.db.agentEvent.iter()) by.set(e.agentName, (by.get(e.agentName) ?? 0) + 1);
  return [...by].map(([agent, events]) => ({ agent, events })).sort((a, b) => (a.agent < b.agent ? -1 : a.agent > b.agent ? 1 : 0));
}

// ---------------------------------------------------------------- #374 referee-only views for the buyer and caller agents
// The agents act for every buyer through the referee identity; my_* views show only the caller's own rows.

const isReferee = (ctx: VCtx) => roleOf(ctx)?.role === 'referee';

/** Referee only: who to call for each buyer. */
export function agentBuyerContactView(ctx: VCtx) {
  if (!isReferee(ctx)) return [];
  return [...ctx.db.buyerProfile.iter()].map((p) => ({ buyerId: p.buyerId, displayName: p.displayName, phone: p.phone }));
}

/** #449 item 3: referee only. The approval rows, so the buyer agent can confirm a record_approval took (it cannot read the buyer-private views). */
export function agentApprovalsView(ctx: VCtx) {
  if (!isReferee(ctx)) return [];
  return [...ctx.db.approval.iter()].map((a) => ({ mandateHash: a.mandateHash, method: a.method, approvedBy: a.approvedBy, at: a.at, voiceApprovalId: a.voiceApprovalId }));
}

/** #449 item 3: referee only. The payment rows, for the same readback. */
export function agentPaymentsView(ctx: VCtx) {
  if (!isReferee(ctx)) return [];
  return [...ctx.db.payment.iter()].map((p) => ({ mandateHash: p.mandateHash, paymentRef: p.paymentRef, amount: p.amount, mode: p.mode, at: p.at }));
}

/** Referee only: goals still open. Open means state ACTIVE, the only state postGoal writes. */
export function agentOpenGoalsView(ctx: VCtx) {
  if (!isReferee(ctx)) return [];
  return [...ctx.db.goal.iter()].filter((g) => g.state === 'ACTIVE');
}

/** Referee only: the items of the open goals. */
export function agentGoalItemsView(ctx: VCtx) {
  return agentOpenGoalsView(ctx).flatMap((g) => [...ctx.db.goalItem.goalId.filter(g.id)]);
}
