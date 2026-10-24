// Reducer tests, run in-process against SpacetimeDB's module test harness (no server needed).
import { beforeEach, describe, expect, it } from 'vitest';
import { ConnectionId, TimeDuration, Timestamp, type Identity } from 'spacetimedb';
import { createModuleTestHarness, TestAuth } from 'spacetimedb/server/test-utils';
import type { InferSchema } from 'spacetimedb/server';
import spacetimedb from './schema';
import * as mod from './index';
import * as m from './market';

const T0 = new Timestamp(1_761_300_000_000_000n);
let conn = 1n;
const as = (sub: string) =>
  TestAuth.fromJwtPayload(JSON.stringify({ iss: 'https://tech-bazaar.test', sub, aud: ['spacetimedb'] }), new ConnectionId(conn++));
type Auth = ReturnType<typeof as>;

let h: ReturnType<typeof createModuleTestHarness<InferSchema<typeof spacetimedb>>>;
const run = <T>(auth: Auth, f: (ctx: any) => T) => h.withReducerTx(auth, f);
const idOf = (auth: Auth): Identity => run(auth, (ctx) => ctx.sender);
const advance = (ms: number) => h.clock.advance(TimeDuration.fromMillis(ms));
const events = () => [...h.db.floorEvent.iter()];

const GPU = 'gpu-rtx5070ti-retail';
const line = (price: number, extra: Partial<{ offeredSpec: string; offeredCondition: string; quantity: number }> = {}) => ({
  skuSpec: GPU, offeredSpec: '', offeredCondition: '', unitPrice: price, quantity: 1, ...extra,
});

// Identities: the module owner, the referee (market service, Shield, advocate relay), Joe's buyer
// agent, another buyer, three sellers and a stranger with no role.
let OWNER: Auth, REF: Auth, JOE: Auth, BOB: Auth, A: Auth, B: Auth, C: Auth, STRANGER: Auth;

const needArgs = (over: Partial<m.PostNeedArgs> = {}): m.PostNeedArgs => ({
  id: 'need-1', buyerId: 'joe', goalId: 'goal-1', deliveryWindow: 'by Friday', spendLimit: 800, consent: true,
  auctionWindowS: 15, origin: 'SIM',
  items: [{ skuSpec: GPU, condition: 'new', variant: 'retail', quantity: 1, unit: 'each' }], ...over,
});

function setupRound(windowS = 15) {
  run(JOE, (ctx) => m.postNeed(ctx, needArgs({ auctionWindowS: windowS })));
  run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS }));
}

const bidArgs = (id: string, lines: ReturnType<typeof line>[]) => ({
  id, roundId: 'round-1', persona: 'p', lines, statedTotal: 0, perks: [], claims: [], origin: 'SIM', source: 'sim:fixture',
});

const mandateArgs = (over: Partial<Parameters<typeof m.createMandate>[1]> = {}) => ({
  hash: 'h1', id: 'mdt-1', dealId: 'round-1:bid-a', buyerId: 'joe', amount: 780, payee: 'seller-a', expiryMinutes: 10, nonce: 'n1', origin: 'SIM', ...over,
});

const goalArgs = (over: Partial<m.PostGoalArgs> = {}): m.PostGoalArgs => ({
  id: 'goal-1', buyerId: 'joe', type: 'part_by_date', cap: 800, deadline: '2025-10-27T23:59:00Z', poNumber: '', origin: 'SIM',
  items: [{ skuSpec: GPU, condition: 'new', variant: 'retail', quantity: 1, skippedOwnedPartId: '' }], ...over,
});

beforeEach(() => {
  h = createModuleTestHarness(spacetimedb, mod);
  h.clock.set(T0);
  OWNER = as('owner'); REF = as('referee'); JOE = as('joe-agent'); BOB = as('bob-agent');
  A = as('seller-a'); B = as('seller-b'); C = as('seller-c'); STRANGER = as('stranger');
  run(OWNER, (ctx) => m.init(ctx));
  const grant = (who: Auth, role: string, subjectId: string) => {
    const identity = idOf(who); // outside the next transaction: the harness cannot nest them
    run(OWNER, (ctx) => m.assignRole(ctx, { identity, role, subjectId }));
  };
  grant(REF, 'referee', 'market');
  grant(JOE, 'buyer', 'joe');
  grant(BOB, 'buyer', 'bob');
  grant(A, 'seller', 'seller-a');
  grant(B, 'seller', 'seller-b');
  grant(C, 'seller', 'seller-c');
  run(A, (ctx) => m.setFloor(ctx, { skuSpec: GPU, floor: 700 }));
  run(B, (ctx) => m.setFloor(ctx, { skuSpec: GPU, floor: 650 }));
});

describe('post_need and redaction', () => {
  it('writes the need and a floor event without the spend limit in any public label', () => {
    setupRound();
    expect(h.db.need.id.find('need-1')?.spendLimit).toBe(800);
    expect(events().map((e) => e.kind)).toEqual(['need_posted', 'round_opened']);
    expect(JSON.stringify(events().map((e) => e.label))).not.toContain('800');
  });

  it('the seller view of a need carries items, window and deadline, never the spend limit or goal', () => {
    setupRound();
    const v = m.sellerNeedsView(h.viewContext(A) as any);
    expect(v).toHaveLength(1);
    expect(v[0]).toMatchObject({ needId: 'need-1', roundId: 'round-1', skuSpec: GPU, condition: 'new' });
    const text = JSON.stringify(v, (_, x) => (typeof x === 'bigint' ? String(x) : x));
    expect(text).not.toMatch(/spendLimit|800|goal|joe/);
  });
});

describe('sealed round', () => {
  it('before close a seller sees only its own bid; the public result table is empty', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(760)])));
    expect(m.myBidsView(h.viewContext(A) as any).map((b: any) => b.id)).toEqual(['bid-a']);
    expect(m.myBidsView(h.viewContext(B) as any).map((b: any) => b.id)).toEqual(['bid-b']);
    expect([...h.db.roundResult.iter()]).toHaveLength(0);
    expect(h.db.round.id.find('round-1')?.sealedCount).toBe(2);
  });

  it('a bid in the last seconds extends the deadline (anti-snipe)', () => {
    setupRound(15);
    const before = h.db.round.id.find('round-1')!.deadline.microsSinceUnixEpoch;
    advance(13_500);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    const r = h.db.round.id.find('round-1')!;
    expect(r.extensions).toBe(1);
    expect(r.deadline.microsSinceUnixEpoch > before).toBe(true);
  });

  it('a bid after the deadline is refused', () => {
    setupRound(15);
    advance(16_000);
    expect(() => run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])))).toThrow(/closed/);
  });
});

describe('bid quantity', () => {
  it.each([0, -1, NaN, Infinity, 2])('place_bid refuses quantity %s with a reason', (q) => {
    setupRound();
    expect(() => run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780, { quantity: q })])))).toThrow(/quantity/);
    expect(h.db.bid.id.find('bid-a')).toBeFalsy();
  });

  it('a bid with the need quantity is accepted and ranks', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780, { quantity: 1 })])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect([...h.db.roundResult.iter()][0]!.rank).toBe(1);
  });
});

describe('floor', () => {
  it('a below-floor bid is recorded as rejected with a reason only its bidder can read, and never ranks', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(690)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(760)])));
    const mine = m.myBidsView(h.viewContext(A) as any)[0] as any;
    expect(mine.floorCheckPassed).toBe(false);
    expect(mine.rejectReason).toContain('floor');
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const res = [...h.db.roundResult.iter()];
    const a = res.find((r) => r.bidId === 'bid-a')!;
    expect(a.rank).toBe(0);
    expect(a.reasons).toEqual(['below this seller floor']);
    expect(res.find((r) => r.bidId === 'bid-b')!.rank).toBe(1);
    expect(events().some((e) => e.kind === 'bid_rejected' && e.refId === 'bid-a')).toBe(true);
  });
});

describe('close_round', () => {
  it('reveals bids ranked, disqualifies an open-box bid against a new goal, and applies a Shield block', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(699, { offeredCondition: 'open-box' })])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c', [line(720)])));
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-c', verdict: 'quarantine', ruleIds: ['payee_swap'], origin: 'SIM' }));
    expect(() => run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }))).toThrow(/still open/);
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const res = [...h.db.roundResult.iter()];
    expect(res.find((r) => r.bidId === 'bid-a')!.rank).toBe(1);
    expect(res.find((r) => r.bidId === 'bid-b')!.reasons.join(' ')).toMatch(/condition: offered open-box/);
    expect(res.find((r) => r.bidId === 'bid-c')!.reasons.join(' ')).toMatch(/Shield quarantine: payee_swap/);
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    expect(events().some((e) => e.kind === 'auction_closed')).toBe(true);
  });

  it('the deadline scheduler (the module itself) may close a round; nobody else may use its reducer', () => {
    setupRound();
    advance(16_000);
    expect(() => run(A, (ctx) => m.closeRoundOnDeadline(ctx, 'round-1'))).toThrow(/scheduler/);
    run(TestAuth.internal(), (ctx) => m.closeRoundOnDeadline(ctx, 'round-1'));
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
  });
});

// ============================================================================================
// INVARIANT 1 (00-shared): no payment row without an approval row for the same mandate hash.
// Idempotency on the mandate hash: a second approval is rejected and shown.
// Written by Vedant (Lane B). Reviewer: Vidyut. grep tag: INVARIANT-1
// ============================================================================================
describe('INVARIANT-1 approval before payment', () => {
  const mk = () => run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));

  it('INVARIANT-1: a payment without an approval row for the same hash is refused and no payment row exists', () => {
    mk();
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780 }))).toThrow(/no approval/);
    expect([...h.db.payment.iter()]).toHaveLength(0);
  });

  it('INVARIANT-1: an approval for a different hash does not unlock this one', () => {
    mk();
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h2', id: 'mdt-2', dealId: 'd2', amount: 10, payee: 'seller-b', nonce: 'n2' })));
    run(JOE, (ctx) => m.recordApproval(ctx, { mandateHash: 'h2', method: 'typed_code', approvedBy: 'joe' }));
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780 }))).toThrow(/no approval/);
  });

  it('INVARIANT-1: with an approval, one payment is recorded; the amount must equal the mandate', () => {
    mk();
    run(JOE, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'joe' }));
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 781 }))).toThrow(/amount/);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780 }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
  });

  it('INVARIANT-1: a second approval for the same hash is rejected and shown; a second payment too', () => {
    mk();
    run(JOE, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'joe' }));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }));
    expect([...h.db.approval.iter()]).toHaveLength(1);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_1', amount: 780 }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_2', amount: 780 }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
    expect([...h.db.rejectedAttempt.iter()].map((r) => r.kind)).toEqual(['approval', 'payment']);
  });

  it('INVARIANT-1: an expired mandate cannot be approved', () => {
    mk();
    advance(11 * 60_000);
    expect(() => run(JOE, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }))).toThrow(/expired/);
  });
});

// ============================================================================================
// SECURITY: every state-changing reducer checks who is calling (roles table, requireRole).
// ============================================================================================
describe('SECURITY caller identity', () => {
  // Each gated reducer, called by seller A. Every one must fail with a clear role error.
  const sellerCalls: [string, (ctx: any) => unknown][] = [
    ['post_need', (ctx) => m.postNeed(ctx, needArgs())],
    ['post_goal', (ctx) => m.postGoal(ctx, goalArgs())],
    ['open_round', (ctx) => m.openRound(ctx, { roundId: 'round-x', needId: 'need-1', windowS: 15 })],
    ['close_round', (ctx) => m.closeRound(ctx, { roundId: 'round-1' })],
    ['attach_verdict', (ctx) => m.attachVerdict(ctx, { bidId: 'bid-b', verdict: 'block', ruleIds: ['x'], origin: 'SIM' })],
    ['attach_claim_check', (ctx) => m.attachClaimCheck(ctx, { bidId: 'bid-b', claim: 'new', check: 'false', evidenceUrl: '', origin: 'SIM' })],
    ['create_mandate', (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h9' }))],
    ['record_approval', (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' })],
    ['record_payment', (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780 })],
    ['assign_role', (ctx) => m.assignRole(ctx, { identity: ctx.sender, role: 'referee', subjectId: 'market' })],
    ['reset_demo', (ctx) => m.resetDemoChecked(ctx)],
    ['seed_demo', (ctx) => m.seedDemoChecked(ctx)],
  ];

  it.each(sellerCalls)('SECURITY: a seller calling %s is refused', (_name, call) => {
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(760)])));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    run(JOE, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }));
    advance(16_000);
    expect(() => run(A, call)).toThrow(/not allowed/);
  });

  it('SECURITY: a stranger with no role cannot bid, post or approve', () => {
    setupRound();
    expect(() => run(STRANGER, (ctx) => m.placeBid(ctx, bidArgs('bid-x', [line(780)])))).toThrow(/not allowed/);
    expect(() => run(STRANGER, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-2' })))).toThrow(/not allowed/);
  });

  it('SECURITY: a buyer cannot bid; a seller bids only as its own seller id', () => {
    setupRound();
    expect(() => run(JOE, (ctx) => m.placeBid(ctx, bidArgs('bid-j', [line(780)])))).toThrow(/not allowed/);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    expect(h.db.bid.id.find('bid-a')!.sellerId).toBe('seller-a');
  });

  it('SECURITY: a buyer posts needs and goals only for its own buyer id', () => {
    expect(() => run(JOE, (ctx) => m.postNeed(ctx, needArgs({ buyerId: 'bob' })))).toThrow(/not allowed/);
    expect(() => run(JOE, (ctx) => m.postGoal(ctx, goalArgs({ buyerId: 'bob' })))).toThrow(/not allowed/);
  });

  it('SECURITY: a seller cannot approve or pay its own deal', () => {
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ payee: 'seller-a' })));
    expect(() => run(A, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }))).toThrow(/not allowed/);
    expect(() => run(A, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'seller-a' }))).toThrow(/not allowed/);
    run(JOE, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }));
    expect(() => run(A, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780 }))).toThrow(/not allowed/);
    expect([...h.db.payment.iter()]).toHaveLength(0);
  });

  it("SECURITY: seller A cannot attach a verdict or claim check against seller B's bid", () => {
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(760)])));
    expect(() => run(A, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-b', verdict: 'block', ruleIds: ['x'], origin: 'SIM' }))).toThrow(/not allowed/);
    expect(() => run(A, (ctx) => m.attachClaimCheck(ctx, { bidId: 'bid-b', claim: 'new', check: 'false', evidenceUrl: '', origin: 'SIM' }))).toThrow(/not allowed/);
    expect([...h.db.bidCheck.iter()]).toHaveLength(0);
  });

  it('SECURITY: approvedBy must equal the mandate buyer, even when the referee relays it', () => {
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'mallory' }))).toThrow(/approvedBy/);
    expect(() => run(JOE, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'bob' }))).toThrow(/approvedBy/);
    expect([...h.db.approval.iter()]).toHaveLength(0);
  });

  it("SECURITY: another buyer cannot approve or create a mandate for Joe's deal", () => {
    expect(() => run(BOB, (ctx) => m.createMandate(ctx, mandateArgs()))).toThrow(/not allowed/);
    run(JOE, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(() => run(BOB, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }))).toThrow(/not allowed/);
  });

  it('SECURITY: only the module owner assigns roles', () => {
    const stranger = idOf(STRANGER);
    expect(() => run(REF, (ctx) => m.assignRole(ctx, { identity: stranger, role: 'buyer', subjectId: 'joe' }))).toThrow(/not allowed/);
    expect(() => run(STRANGER, (ctx) => m.assignRole(ctx, { identity: stranger, role: 'referee', subjectId: 'm' }))).toThrow(/not allowed/);
  });

  it('SECURITY: a buyer screen pairs with the demo code only; a seller cannot pair', () => {
    run(OWNER, (ctx) => m.seedDemoChecked(ctx));
    const code = h.db.pairCode.buyerId.find('joe')!.code;
    const screen = as('joe-laptop');
    expect(() => run(screen, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'joe', code: 'wrong-code' }))).toThrow(/code/);
    expect(() => run(A, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'joe', code }))).toThrow(/not allowed/);
    run(screen, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'joe', code }));
    expect(m.myGoalsView(h.viewContext(screen) as any).length).toBe(1);
    expect(m.myGoalsView(h.viewContext(A) as any).length).toBe(0);
  });
});

describe('every state change writes a floor event', () => {
  it('need, round, bids, verdict, close, mandate, approval and payment each add one', () => {
    setupRound();
    const n0 = events().length;
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-a', verdict: 'allow', ruleIds: [], origin: 'SIM' }));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    run(JOE, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780 }));
    expect(events().slice(n0).map((e) => e.kind)).toEqual([
      'bid_sealed', 'verdict', 'auction_closed', 'mandate_created', 'approval_recorded', 'payment_recorded',
    ]);
  });
});

describe('goals (Lane A Goal contract)', () => {
  it('post_goal stores the goal with its items; only a paired buyer screen sees it', () => {
    run(JOE, (ctx) => m.postGoal(ctx, goalArgs()));
    const g = h.db.goal.id.find('goal-1')!;
    expect(g).toMatchObject({ state: 'ACTIVE', cap: 800, reservedAmount: 0, type: 'part_by_date' });
    const items = [...h.db.goalItem.goalId.filter('goal-1')];
    expect(items[0]).toMatchObject({ skuSpec: GPU, condition: 'new', variant: 'retail', quantity: 1 });
    expect(m.myGoalsView(h.viewContext(STRANGER) as any)).toHaveLength(0);
    expect(m.myGoalsView(h.viewContext(JOE) as any)).toHaveLength(1);
    expect(events().find((e) => e.kind === 'goal_posted')!.label).not.toMatch(/800/);
  });

  it('post_goal refuses a deadline that is not an ISO date', () => {
    expect(() => run(JOE, (ctx) => m.postGoal(ctx, goalArgs({ deadline: 'by friday' })))).toThrow(/deadline/);
  });
});
