// Reducer tests, run in-process against SpacetimeDB's module test harness (no server needed).
import { beforeEach, describe, expect, it } from 'vitest';
import { ConnectionId, TimeDuration, Timestamp } from 'spacetimedb';
import { createModuleTestHarness, TestAuth } from 'spacetimedb/server/test-utils';
import type { InferSchema } from 'spacetimedb/server';
import spacetimedb from './schema';
import * as mod from './index';
import * as m from './market';

const T0 = new Timestamp(1_761_300_000_000_000n);
let conn = 1n;
const as = (sub: string) =>
  TestAuth.fromJwtPayload(JSON.stringify({ iss: 'https://tech-bazaar.test', sub, aud: ['spacetimedb'] }), new ConnectionId(conn++));

let h: ReturnType<typeof createModuleTestHarness<InferSchema<typeof spacetimedb>>>;
const run = <T>(auth: ReturnType<typeof as>, f: (ctx: any) => T) => h.withReducerTx(auth, f);
const admin = () => TestAuth.internal();
const advance = (ms: number) => h.clock.advance(TimeDuration.fromMillis(ms));
const events = () => [...h.db.floorEvent.iter()];

const GPU = 'gpu-rtx5070ti-retail';
const line = (price: number, extra: Partial<{ offeredSpec: string; offeredCondition: string }> = {}) => ({
  skuSpec: GPU, offeredSpec: '', offeredCondition: '', unitPrice: price, quantity: 1, ...extra,
});

const sellerA = () => as('seller-a');
const sellerB = () => as('seller-b');
let A: ReturnType<typeof as>, B: ReturnType<typeof as>, C: ReturnType<typeof as>;

function setupRound(windowS = 15) {
  run(admin(), (ctx) =>
    m.postNeed(ctx, {
      id: 'need-1', buyerId: 'joe', goalId: 'goal-1', deliveryWindow: 'by Friday', spendLimit: 800, consent: true,
      auctionWindowS: windowS, origin: 'SIM',
      items: [{ skuSpec: GPU, condition: 'new', variant: 'retail', quantity: 1, unit: 'each' }],
    }),
  );
  run(admin(), (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS }));
}

const bidArgs = (id: string, lines: ReturnType<typeof line>[]) => ({
  id, roundId: 'round-1', persona: 'p', lines, statedTotal: 0, perks: [], claims: [], origin: 'SIM', source: 'sim:fixture',
});

beforeEach(() => {
  h = createModuleTestHarness(spacetimedb, mod, { clock: undefined });
  h.clock.set(T0);
  A = sellerA(); B = sellerB(); C = as('seller-c');
  run(A, (ctx) => m.registerSeller(ctx, { sellerId: 'seller-a' }));
  run(B, (ctx) => m.registerSeller(ctx, { sellerId: 'seller-b' }));
  run(C, (ctx) => m.registerSeller(ctx, { sellerId: 'seller-c' }));
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

  it('only a registered seller may bid, and only as itself', () => {
    setupRound();
    expect(() => run(as('stranger'), (ctx) => m.placeBid(ctx, bidArgs('bid-x', [line(780)])))).toThrow(/registered seller/);
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
    run(admin(), (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
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
    run(admin(), (ctx) => m.attachVerdict(ctx, { bidId: 'bid-c', verdict: 'quarantine', ruleIds: ['payee_swap'], origin: 'SIM' }));
    expect(() => run(admin(), (ctx) => m.closeRound(ctx, { roundId: 'round-1' }))).toThrow(/still open/);
    advance(16_000);
    run(admin(), (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const res = [...h.db.roundResult.iter()];
    expect(res.find((r) => r.bidId === 'bid-a')!.rank).toBe(1);
    expect(res.find((r) => r.bidId === 'bid-b')!.reasons.join(' ')).toMatch(/condition: offered open-box/);
    expect(res.find((r) => r.bidId === 'bid-c')!.reasons.join(' ')).toMatch(/Shield quarantine: payee_swap/);
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    expect(events().some((e) => e.kind === 'auction_closed')).toBe(true);
  });
});

// ============================================================================================
// INVARIANT 1 (00-shared): no payment row without an approval row for the same mandate hash.
// Idempotency on the mandate hash: a second approval is rejected and shown.
// Written by Vedant (Lane B). Reviewer: Vidyut. grep tag: INVARIANT-1
// ============================================================================================
describe('INVARIANT-1 approval before payment', () => {
  const mk = () =>
    run(admin(), (ctx) =>
      m.createMandate(ctx, { hash: 'h1', id: 'mdt-1', dealId: 'round-1:bid-a', buyerId: 'joe', amount: 780, payee: 'seller-a', expiryMinutes: 10, nonce: 'n1', origin: 'SIM' }),
    );

  it('INVARIANT-1: a payment without an approval row for the same hash is refused and no payment row exists', () => {
    mk();
    expect(() => run(admin(), (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780 }))).toThrow(/no approval/);
    expect([...h.db.payment.iter()]).toHaveLength(0);
  });

  it('INVARIANT-1: an approval for a different hash does not unlock this one', () => {
    mk();
    run(admin(), (ctx) => m.createMandate(ctx, { hash: 'h2', id: 'mdt-2', dealId: 'd2', buyerId: 'joe', amount: 10, payee: 'seller-b', expiryMinutes: 10, nonce: 'n2', origin: 'SIM' }));
    run(admin(), (ctx) => m.recordApproval(ctx, { mandateHash: 'h2', method: 'typed_code', approvedBy: 'joe' }));
    expect(() => run(admin(), (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780 }))).toThrow(/no approval/);
  });

  it('INVARIANT-1: with an approval, one payment is recorded; the amount must equal the mandate', () => {
    mk();
    run(admin(), (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'joe' }));
    expect(() => run(admin(), (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 781 }))).toThrow(/amount/);
    run(admin(), (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780 }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
  });

  it('INVARIANT-1: a second approval for the same hash is rejected and shown; a second payment too', () => {
    mk();
    run(admin(), (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'joe' }));
    run(admin(), (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }));
    expect([...h.db.approval.iter()]).toHaveLength(1);
    run(admin(), (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_1', amount: 780 }));
    run(admin(), (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_2', amount: 780 }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
    const rej = [...h.db.rejectedAttempt.iter()].map((r) => r.kind);
    expect(rej).toEqual(['approval', 'payment']);
  });

  it('INVARIANT-1: an expired mandate cannot be approved', () => {
    mk();
    advance(11 * 60_000);
    expect(() => run(admin(), (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }))).toThrow(/expired/);
  });
});

describe('every state change writes a floor event', () => {
  it('need, round, bids, verdict, close, mandate, approval and payment each add one', () => {
    setupRound();
    const n0 = events().length;
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(admin(), (ctx) => m.attachVerdict(ctx, { bidId: 'bid-a', verdict: 'allow', ruleIds: [], origin: 'SIM' }));
    advance(16_000);
    run(admin(), (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    run(admin(), (ctx) => m.createMandate(ctx, { hash: 'h1', id: 'mdt-1', dealId: 'x', buyerId: 'joe', amount: 780, payee: 'seller-a', expiryMinutes: 10, nonce: 'n', origin: 'SIM' }));
    run(admin(), (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'joe' }));
    run(admin(), (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780 }));
    expect(events().slice(n0).map((e) => e.kind)).toEqual([
      'bid_sealed', 'verdict', 'auction_closed', 'mandate_created', 'approval_recorded', 'payment_recorded',
    ]);
  });
});

describe('goals', () => {
  it('post_goal stores the goal privately and the buyer sees it only through a buyer session', () => {
    run(admin(), (ctx) =>
      m.postGoal(ctx, {
        id: 'goal-1', buyerId: 'joe', type: 'part_by_date', text: 'a GPU for 1440p that fits my case and PSU, under $800, by Friday',
        cap: 800, deadlineMinutes: 60 * 24 * 3, poNumber: '', origin: 'SIM',
        items: [{ category: 'gpu', description: 'GPU for 1440p', skuSpec: '', modelNumber: '' }],
      }),
    );
    const joe = as('joe-screen');
    expect(m.myGoalsView(h.viewContext(joe) as any)).toHaveLength(0);
    run(joe, (ctx) => m.openBuyerSession(ctx, { buyerId: 'joe' }));
    const g = m.myGoalsView(h.viewContext(joe) as any);
    expect(g).toHaveLength(1);
    expect(g[0]).toMatchObject({ state: 'ACTIVE', cap: 800, reservedAmount: 0 });
    expect(events().find((e) => e.kind === 'goal_posted')!.label).not.toMatch(/800|1440p/);
  });

  it('a registered seller cannot open a buyer session', () => {
    expect(() => run(A, (ctx) => m.openBuyerSession(ctx, { buyerId: 'joe' }))).toThrow(/seller/);
  });
});
