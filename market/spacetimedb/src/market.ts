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

/**
 * A browser screen takes the buyer role with the demo pairing code (SIM sign-in). A wrong code returns { paired: false } without throwing, so the failure is counted (a throw would
 * roll the count back). 5 failures lock the code, and 5 failures lock the caller across every code.
 * The code itself never appears in a message.
 */
export function pairBuyerScreen(ctx: Ctx, { buyerId, code }: { buyerId: string; code: string }) {
  const cur = roleOf(ctx);
  if (cur && cur.role !== 'buyer') throw new SenderError(`not allowed: a ${cur.role} cannot pair as a buyer screen`);
  const want = ctx.db.pairCode.buyerId.find(buyerId);
  if (!want) throw new SenderError('no pairing code issued for this buyer; ask the operator');
  if (want.locked) throw new SenderError('pairing is locked after too many wrong codes; ask the operator for a new code');
  const mine = ctx.db.pairAttempt.identity.find(ctx.sender);
  if (mine && mine.failures >= PAIR_MAX_FAILURES) throw new SenderError('this screen is locked after too many wrong codes; ask the operator');
  if (want.code !== code) {
    const failed = want.failedAttempts + 1;
    ctx.db.pairCode.buyerId.update({ ...want, failedAttempts: failed, locked: failed >= PAIR_MAX_FAILURES });
    if (mine) ctx.db.pairAttempt.identity.update({ ...mine, failures: mine.failures + 1 });
    else ctx.db.pairAttempt.insert({ identity: ctx.sender, failures: 1 });
    if (failed >= PAIR_MAX_FAILURES) event(ctx, 'pairing_locked', 'pair_code', buyerId, 'Screen pairing locked after too many wrong codes');
    return { paired: false, reason: 'wrong pairing code' };
  }
  if (cur) ctx.db.role.identity.update({ ...cur, subjectId: buyerId });
  else ctx.db.role.insert({ identity: ctx.sender, role: 'buyer', subjectId: buyerId });
  return { paired: true, reason: '' };
}

/** Owner only: a fresh code for this buyer, unlocked, with its counter reset. It also clears every screen's lock (pair_attempt is keyed by identity only): the operator unlocks. */
export function reissuePairCode(ctx: Ctx, { buyerId }: { buyerId: string }) {
  requireRole(ctx, 'reissue_pair_code', ['owner']);
  issuePairCode(ctx, buyerId);
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
  event(ctx, 'allowance_set', 'allowance', a.buyerId, 'A buyer allowance was set', '', 'SIM');
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
    origin: a.origin, source: a.source, sealedAt: ctx.timestamp, lineRejects: fc.lineRejects,
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
  const mine = [...ctx.db.stockHold.bidId.filter(bidId)];
  if (!mine.length) return;
  const now = ms(ctx.timestamp);
  for (const hd of mine) {
    // The deal belongs to the buyer whose need the round served: nobody else can renew, lock or pay for its unit.
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
    needItems.set(i.skuSpec, {
      sku_spec: i.skuSpec, condition: i.condition as Condition, allowed_conditions: i.allowedConditions as Condition[],
      variant: i.variant, quantity: i.quantity, unit: i.unit,
    });
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
      if (c.kind === 'advocate' && c.result === 'veto') reasons.push(`Advocate veto (${c.detail}) [source: ${c.evidenceUrl}]`);
    }
    if (reasons.length) rejections.set(b.id, reasons);
  }
  // The seller fee is deliberately not passed: it never feeds ranking (invariant 8).
  const spendLimit = ctx.db.need.id.find(r.needId)?.spendLimit;
  // A line whose units are held or sold by an earlier round is skipped with a reason, like a line with no floor.
  const nowMs = ms(ctx.timestamp);
  sweepExpiredHolds(ctx);
  const needQtyOf = (sku: string) => needItems.get(sku)?.quantity ?? 1;
  const condOfLine = (l: Line) => l.offeredCondition || needItems.get(l.skuSpec)?.condition || 'new';
  const soldOut = new Map<string, string[]>();
  for (const b of rows) {
    const held = [...ctx.db.stockHold.sellerId.filter(b.sellerId)].map(asHoldLike);
    soldOut.set(b.id, soldOutReasons(b.lines.map((l: Line) => ({ skuSpec: l.skuSpec, condition: condOfLine(l), quantity: l.quantity })), held, b.sellerId, nowMs, needQtyOf));
  }
  const lineRejects = new Map(rows.map((b) => [b.id, b.lines.map((_: Line, i: number) => b.lineRejects[i] || soldOut.get(b.id)![i] || '')]));
  const ranked = rankBids(rows.map(toBid), {
    needItems, rejections, lineRejects, spendLimit, quality: MARKET_CONFIG.quality, verifiedClaims: (b) => verified.get(b.id) ?? 0,
  });
  const byId = new Map(rows.map((b) => [b.id, b]));
  for (const x of ranked.ranked) {
    const b = byId.get(x.bid.id)!;
    // The lines are the picked alternatives (the cheapest allowed line per SKU), the ones the rank is about.
    ctx.db.roundResult.insert({ id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: x.rank, landed: x.landed, reasons: [], lines: x.picked.map((i) => b.lines[i]!), origin: b.origin, source: b.source });
  }
  for (const d of ranked.disqualified) {
    const b = byId.get(d.bid.id)!;
    ctx.db.roundResult.insert({ id: 0n, roundId, bidId: b.id, sellerId: b.sellerId, persona: b.persona, rank: 0, landed: d.landed, reasons: d.reasons, lines: b.lines, origin: b.origin, source: b.source });
  }
  ctx.db.round.id.update({ ...r, state: 'closed', closedAt: ctx.timestamp });
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
  claimDealUnits(ctx, a.dealId, a.buyerId, 'held');
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
  claimDealUnits(ctx, md.dealId, md.buyerId, 'held');
  ctx.db.approval.insert({ id: 0n, mandateHash: a.mandateHash, method: a.method, approvedBy: a.approvedBy, at: ctx.timestamp });
  event(ctx, 'approval_recorded', 'approval', a.mandateHash, `Approved by ${a.method.replace('_', ' ')}`, md.payee, md.origin);
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
