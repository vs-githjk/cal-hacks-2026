// Reducer tests, run in-process against SpacetimeDB's module test harness (no server needed).
import { beforeEach, describe, expect, it } from 'vitest';
import { ConnectionId, TimeDuration, Timestamp, type Identity } from 'spacetimedb';
import { createModuleTestHarness, TestAuth } from 'spacetimedb/server/test-utils';
import type { InferSchema } from 'spacetimedb/server';
import spacetimedb, { TelemetryAgentRow, TelemetryRow } from './schema';
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
const ms = (ts: Timestamp) => Number(ts.microsSinceUnixEpoch / 1000n);
const advance = (ms: number) => h.clock.advance(TimeDuration.fromMillis(ms));
const events = () => [...h.db.floorEvent.iter()];

const GPU = 'gpu-rtx5070ti-retail';
const line = (price: number, extra: Partial<{ offeredSpec: string; offeredCondition: string; quantity: number }> = {}) => ({
  skuSpec: GPU, offeredSpec: '', offeredCondition: '', unitPrice: price, quantity: 1, ...extra,
});

// Identities: the module owner, the referee (market service, Shield, advocate relay), Vidyut's buyer
// agent, another buyer, three sellers and a stranger with no role.
let OWNER: Auth, REF: Auth, VIDYUT: Auth, BOB: Auth, A: Auth, B: Auth, C: Auth, STRANGER: Auth;

const needArgs = (over: Partial<m.PostNeedArgs> = {}): m.PostNeedArgs => ({
  id: 'need-1', buyerId: 'vidyut', goalId: 'goal-1', deliveryWindow: 'by Friday', spendLimit: 800, consent: true,
  auctionWindowS: 15, origin: 'SIM',
  items: [{ skuSpec: GPU, condition: 'new', allowedConditions: [], variant: 'retail', quantity: 1, unit: 'each' }], ...over,
});

function setupRound(windowS = 15) {
  run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ auctionWindowS: windowS })));
  run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS }));
}

const bidArgs = (id: string, lines: ReturnType<typeof line>[]) => ({
  id, roundId: 'round-1', persona: 'p', lines, statedTotal: 0, perks: [], claims: [], origin: 'SIM', source: 'sim:fixture',
});

const mandateArgs = (over: Partial<Parameters<typeof m.createMandate>[1]> = {}) => ({
  hash: 'h1', id: 'mdt-1', dealId: 'round-1:bid-a', buyerId: 'vidyut', amount: 780, payee: 'seller-a', expiryMinutes: 10, nonce: 'n1', requestedBy: '', origin: 'SIM', ...over,
});

let wins = 0;
/** #191: a mandate needs a real winner. A fresh closed round where `seller` alone bids `price`; returns the matching mandate fields. */
function win(price = 780, seller: Auth = C, sellerId = 'seller-c', buyer: Auth = VIDYUT, buyerId = 'vidyut') {
  const n = ++wins;
  const needId = `need-w${n}`, roundId = `round-w${n}`, bidId = `bid-w${n}`;
  if (price < 100) run(seller, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'new', floor: price }));
  run(buyer, (ctx) => m.postNeed(ctx, needArgs({ id: needId, buyerId, spendLimit: Math.max(800, price) })));
  run(REF, (ctx) => m.openRound(ctx, { roundId, needId, windowS: 15 }));
  run(seller, (ctx) => m.placeBid(ctx, { ...bidArgs(bidId, [line(price, { quantity: 100 })]), roundId })); // stock for many deals
  advance(16_000);
  run(REF, (ctx) => m.closeRound(ctx, { roundId }));
  return { dealId: `${roundId}:${bidId}`, payee: sellerId, amount: price };
}

/** Create a mandate as the referee. Arguments are evaluated first, so a win() inside them runs in its own transactions. */
const mint = (args: ReturnType<typeof mandateArgs>) => run(REF, (ctx) => m.createMandate(ctx, args));

const goalArgs = (over: Partial<m.PostGoalArgs> = {}): m.PostGoalArgs => ({
  id: 'goal-1', buyerId: 'vidyut', type: 'part_by_date', cap: 800, deadline: '2025-10-27T23:59:00Z', poNumber: '', origin: 'SIM',
  items: [{ skuSpec: GPU, condition: 'new', variant: 'retail', quantity: 1, skippedOwnedPartId: '' }], ...over,
});

beforeEach(() => {
  h = createModuleTestHarness(spacetimedb, mod);
  h.clock.set(T0);
  OWNER = as('owner'); REF = as('referee'); VIDYUT = as('vidyut-agent'); BOB = as('bob-agent');
  A = as('seller-a'); B = as('seller-b'); C = as('seller-c'); STRANGER = as('stranger');
  run(OWNER, (ctx) => m.init(ctx));
  const grant = (who: Auth, role: string, subjectId: string) => {
    const identity = idOf(who); // outside the next transaction: the harness cannot nest them
    run(OWNER, (ctx) => m.assignRole(ctx, { identity, role, subjectId }));
  };
  grant(REF, 'referee', 'market');
  grant(VIDYUT, 'buyer', 'vidyut');
  grant(BOB, 'buyer', 'bob');
  grant(A, 'seller', 'seller-a');
  grant(B, 'seller', 'seller-b');
  grant(C, 'seller', 'seller-c');
  // Floors are per (seller, sku, condition). Open-box floors are low so they never bite by accident.
  run(A, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'new', floor: 700 }));
  run(A, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'open-box', floor: 100 }));
  run(B, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'new', floor: 650 }));
  run(B, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'open-box', floor: 100 }));
  run(C, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'new', floor: 100 }));
  run(C, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'open-box', floor: 100 }));
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
    expect(text).not.toMatch(/spendLimit|800|goal|vidyut/);
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

  it('#135 refuses a source that starts like a URL but is not one ("https://"), and keeps real URLs and plain labels', () => {
    setupRound();
    for (const bad of ['https://', 'http://', 'https:// x.example']) {
      expect(() => run(A, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-bad', [line(780)]), source: bad }))).toThrow(/source/);
    }
    expect(h.db.bid.id.find('bid-bad')).toBeFalsy();
    run(A, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-url', [line(780)]), source: 'https://example.com/listing?id=1' }));
    run(B, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-label', [line(760)]), source: 'sim:fixture' }));
    expect(h.db.round.id.find('round-1')?.sealedCount).toBe(2);
  });

  it('refuses a line whose SKU the need does not have, stores no bid, and the seller can still bid', () => {
    setupRound();
    expect(() => run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780), { ...line(10), skuSpec: 'junk' }])))).toThrow('bid refused: junk: not part of this need');
    expect(h.db.bid.id.find('bid-a')).toBeFalsy();
    expect(h.db.round.id.find('round-1')?.sealedCount).toBe(0);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a2', [line(780)])));
    expect(h.db.round.id.find('round-1')?.sealedCount).toBe(1);
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
  it.each([0, -1, NaN, Infinity])('place_bid refuses qty_available %s with a reason', (q) => {
    setupRound();
    expect(() => run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780, { quantity: q })])))).toThrow(/qty_available/);
    expect(h.db.bid.id.find('bid-a')).toBeFalsy();
  });

  it('more stock than the need is accepted, and the line is priced for the need quantity only', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780, { quantity: 4 })])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect([...h.db.roundResult.iter()][0]).toMatchObject({ rank: 1, landed: 780 });
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
  const mk = () => mint(mandateArgs(win()));

  it('INVARIANT-1: a payment without an approval row for the same hash is refused and no payment row exists', () => {
    mk();
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780, mode: 'sim' }))).toThrow(/no approval/);
    expect([...h.db.payment.iter()]).toHaveLength(0);
  });

  it('INVARIANT-1: an approval for a different hash does not unlock this one', () => {
    mk();
    mint(mandateArgs({ hash: 'h2', id: 'mdt-2', nonce: 'n2', ...win(10, B, 'seller-b') }));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h2', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' }))).toThrow(/no approval/);
  });

  it('INVARIANT-1: with an approval, one payment is recorded; the amount must equal the mandate', () => {
    mk();
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 781, mode: 'sim' }))).toThrow(/amount/);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780, mode: 'sim' }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
  });

  it('INVARIANT-1: a second approval for the same hash is rejected and shown; a second payment too', () => {
    mk();
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    expect([...h.db.approval.iter()]).toHaveLength(1);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_1', amount: 780, mode: 'sim' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_2', amount: 780, mode: 'sim' }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
    expect([...h.db.rejectedAttempt.iter()].map((r) => r.kind)).toEqual(['approval', 'payment']);
  });

  it('INVARIANT-1: an expired mandate cannot be approved', () => {
    mk();
    advance(11 * 60_000);
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }))).toThrow(/expired/);
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
    ['record_approval', (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' })],
    ['record_payment', (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' })],
    ['attach_advocate_card', (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b', recommendation: 'veto', ruleId: 'fit.gpu_length', text: 'x', sourceUrl: 'https://x', origin: 'SIM' })],
    ['assign_role', (ctx) => m.assignRole(ctx, { identity: ctx.sender, role: 'referee', subjectId: 'market' })],
    ['reset_demo', (ctx) => m.resetDemoChecked(ctx)],
    ['seed_demo', (ctx) => m.seedDemoChecked(ctx)],
  ];

  it.each(sellerCalls)('SECURITY: a seller calling %s is refused', (_name, call) => {
    mint(mandateArgs(win()));
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(760)])));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
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
    expect(() => run(VIDYUT, (ctx) => m.placeBid(ctx, bidArgs('bid-j', [line(780)])))).toThrow(/not allowed/);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    expect(h.db.bid.id.find('bid-a')!.sellerId).toBe('seller-a');
  });

  it('SECURITY: a buyer posts needs and goals only for its own buyer id', () => {
    expect(() => run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ buyerId: 'bob' })))).toThrow(/not allowed/);
    expect(() => run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs({ buyerId: 'bob' })))).toThrow(/not allowed/);
  });

  it('SECURITY: a seller cannot approve or pay its own deal', () => {
    mint(mandateArgs(win(780, A, 'seller-a')));
    expect(() => run(A, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }))).toThrow(/not allowed/);
    expect(() => run(A, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'seller-a', voiceApprovalId: 'va-1' }))).toThrow(/not allowed/);
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    expect(() => run(A, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' }))).toThrow(/not allowed/);
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
    mint(mandateArgs(win()));
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'mallory', voiceApprovalId: 'va-1' }))).toThrow(/approvedBy/);
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'bob', voiceApprovalId: 'va-1' }))).toThrow(/approvedBy/);
    expect([...h.db.approval.iter()]).toHaveLength(0);
  });

  it("SECURITY: another buyer cannot approve or create a mandate for Vidyut's deal", () => {
    const w = win();
    expect(() => run(BOB, (ctx) => m.createMandate(ctx, mandateArgs(w)))).toThrow(/not allowed/);
    expect(() => run(VIDYUT, (ctx) => m.createMandate(ctx, mandateArgs(w)))).toThrow(/not allowed/);
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs(w)));
    expect(() => run(BOB, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }))).toThrow(/not allowed/);
  });

  it('SECURITY: only the module owner assigns roles', () => {
    const stranger = idOf(STRANGER);
    expect(() => run(REF, (ctx) => m.assignRole(ctx, { identity: stranger, role: 'buyer', subjectId: 'vidyut' }))).toThrow(/not allowed/);
    expect(() => run(STRANGER, (ctx) => m.assignRole(ctx, { identity: stranger, role: 'referee', subjectId: 'm' }))).toThrow(/not allowed/);
  });

  it('SECURITY: a buyer screen pairs with the demo code only; a seller cannot pair', () => {
    run(OWNER, (ctx) => m.seedDemoChecked(ctx));
    const code = h.db.pairCode.buyerId.find('vidyut')!.code;
    const screen = as('vidyut-laptop');
    expect(run(screen, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'vidyut', code: 'wrong-code' }))).toMatchObject({ paired: false });
    expect(() => run(A, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'vidyut', code }))).toThrow(/not allowed/);
    run(screen, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'vidyut', code }));
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
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' }));
    expect(events().slice(n0).map((e) => e.kind)).toEqual([
      'bid_sealed', 'verdict', 'stock_held', 'auction_closed', 'mandate_created', 'approval_recorded', 'stock_sold', 'payment_recorded',
    ]);
  });
});

// ============================================================================================
// #H1 (red team): a Shield block, failed claim or advocate veto attached while a round is still open
// must not reach the public floor_event feed, or a rival still bidding learns which sellers are
// already out. The round close that reveals the result flushes every check's event at once.
// ============================================================================================
describe('#H1 per-bid check events wait for round close', () => {
  it("an open round's public events name no bid or seller, however many checks land on it", () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    const n0 = events().length;
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-a1', verdict: 'block', ruleIds: ['shield.x'], origin: 'SIM' }));
    run(REF, (ctx) => m.attachClaimCheck(ctx, { bidId: 'bid-a1', claim: 'new', check: 'false', evidenceUrl: 'https://x.test', origin: 'SIM' }));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b1', recommendation: 'veto', ruleId: 'fit.gpu_length', text: 'too long', sourceUrl: 'https://x.test/b', origin: 'SIM' }));
    // No public event at all for any of these three checks while the round stays open: not the bid id
    // (which embeds the seller id), not the rule, not the verdict, nothing.
    expect(events().slice(n0)).toHaveLength(0);
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const kinds = events().slice(n0).map((e) => e.kind);
    expect(kinds).toContain('verdict');
    expect(kinds).toContain('claim_checked');
    expect(kinds).toContain('advocate_card');
    const verdict = events().find((e) => e.kind === 'verdict')!;
    expect(verdict.refId).toBe('bid-a1');
    expect(verdict.label).toBe('Bazaar Shield: block');
  });

  it('a check attached after the round already closed (#389 defense in depth) is announced right away: it leaks nothing new', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const n0 = events().length;
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-a1', verdict: 'block', ruleIds: ['shield.late'], origin: 'SIM' }));
    expect(events().slice(n0).map((e) => e.kind)).toEqual(['verdict']);
  });
});

describe('goals (Lane A Goal contract)', () => {
  it('post_goal stores the goal with its items; only a paired buyer screen sees it', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    const g = h.db.goal.id.find('goal-1')!;
    expect(g).toMatchObject({ state: 'ACTIVE', cap: 800, reservedAmount: 0, type: 'part_by_date' });
    const items = [...h.db.goalItem.goalId.filter('goal-1')];
    expect(items[0]).toMatchObject({ skuSpec: GPU, condition: 'new', variant: 'retail', quantity: 1 });
    expect(m.myGoalsView(h.viewContext(STRANGER) as any)).toHaveLength(0);
    expect(m.myGoalsView(h.viewContext(VIDYUT) as any)).toHaveLength(1);
    expect(events().find((e) => e.kind === 'goal_posted')!.label).not.toMatch(/800/);
  });

  it('post_goal refuses a deadline that is not an ISO date', () => {
    expect(() => run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs({ deadline: 'by friday' })))).toThrow(/deadline/);
  });
});

// ============================================================================================
// b2 ALLOWANCE LADDER (D's Allowance shape). Starts at $0; only the buyer's own clean receiving
// check raises it; inside the allowance a buy auto-approves with a receipt; requester never approves.
// ============================================================================================
describe('b2 allowance ladder', () => {
  const allowance = () => h.db.allowance.buyerId.find('vidyut');
  const paidDeal = (hash: string, amount: number) => {
    mint(mandateArgs({ hash, id: `m-${hash}`, nonce: hash, ...win(amount) }));
    if (!h.db.approval.mandateHash.find(hash)) run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: hash, method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: hash, paymentRef: `pi_${hash}`, amount, mode: 'sim' }));
  };
  let n = 0;
  const receive = (who: Auth, hash: string, result = 'accepted') =>
    run(who, (ctx) => m.recordReceiving(ctx, { id: `rcv-${hash}-${result}-${++n}`, orderId: hash, skuSpec: GPU, photoUrl: 'sim://photo', expectedSpecId: 'spec-gpu', result, reasons: result === 'accepted' ? [] : ['box shows open-box seal'], checkedBy: 'owner', origin: 'SIM' }));

  it('a buyer starts at step 0 with $0 limits, so the first buy needs the call (no auto approval)', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    expect(allowance()).toMatchObject({ ladderStep: 0, perPurchaseLimit: 0, periodLimit: 0, currency: 'USD', period: 'week' });
    mint(mandateArgs(win(5)));
    expect(h.db.mandate.hash.find('h1')!.withinAllowance).toBe(false);
    expect(h.db.approval.mandateHash.find('h1')).toBeFalsy();
  });

  it('one clean receiving check by the buyer raises the ladder one step, once per deal', () => {
    paidDeal('d1', 780);
    receive(VIDYUT, 'd1');
    expect(allowance()!.ladderStep).toBe(1);
    expect(allowance()!.perPurchaseLimit).toBeGreaterThan(0);
    receive(VIDYUT, 'd1');
    expect(allowance()!.ladderStep).toBe(1);
    expect(events().some((e) => e.kind === 'allowance_raised')).toBe(true);
    expect(events().some((e) => e.kind === 'delivery_checked')).toBe(true);
  });

  it('a failed receiving check does not raise the ladder and opens a credit request', () => {
    paidDeal('d1', 780);
    receive(VIDYUT, 'd1', 'rejected');
    expect(allowance()?.ladderStep ?? 0).toBe(0);
    const ev = [...h.db.receivingEvent.orderId.filter('d1')][0]!;
    expect(ev.creditRequestId).not.toBe('');
  });

  it('only the buyer may record receiving; a seller or the referee cannot raise the allowance', () => {
    paidDeal('d1', 780);
    expect(() => receive(A, 'd1')).toThrow(/not allowed/);
    expect(() => receive(REF, 'd1')).toThrow(/not allowed/);
    expect(() => receive(BOB, 'd1')).toThrow(/not allowed/);
    expect(allowance()?.ladderStep ?? 0).toBe(0);
  });

  it('receiving needs a paid deal', () => {
    mint(mandateArgs(win()));
    expect(() => receive(VIDYUT, 'h1')).toThrow(/not paid/);
  });

  it('inside the allowance a buy auto-approves with a receipt and counts against the period; above it, it calls', () => {
    paidDeal('d1', 780);
    receive(VIDYUT, 'd1');
    const per = allowance()!.perPurchaseLimit;
    mint(mandateArgs({ hash: 'small', id: 'm-small', nonce: 's', ...win(per) }));
    expect(h.db.mandate.hash.find('small')!.withinAllowance).toBe(true);
    expect(h.db.approval.mandateHash.find('small')!.method).toBe('allowance');
    expect(allowance()!.spentThisPeriod).toBe(per);
    expect([...h.db.notification.buyerId.filter('vidyut')].some((n) => n.text.includes('within your allowance'))).toBe(true);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'small', paymentRef: 'pi_small', amount: per, mode: 'sim' }));
    mint(mandateArgs({ hash: 'big', id: 'm-big', nonce: 'b', ...win(per + 1) }));
    expect(h.db.mandate.hash.find('big')!.withinAllowance).toBe(false);
    expect(h.db.approval.mandateHash.find('big')).toBeFalsy();
  });

  it('the requester can never approve their own purchase', () => {
    mint(mandateArgs({ requestedBy: 'vidyut', ...win() }));
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }))).toThrow(/requester/);
    expect(h.db.approval.mandateHash.find('h1')).toBeFalsy();
  });

  const setAllow = (who: Auth, buyerId: string, per: number, lim: number, period = 'week') =>
    run(who, (ctx) => m.setAllowanceChecked(ctx, { buyerId, perPurchaseLimit: per, periodLimit: lim, period }));

  it('set_allowance: the referee sets Vidyut\'s demo allowance, creating the row and an event; the starting $0 stays for others', () => {
    setAllow(REF, 'vidyut', 250, 500);
    expect(allowance()).toMatchObject({ perPurchaseLimit: 250, periodLimit: 500, ladderStep: 2, period: 'week' });
    expect(events().some((e) => e.kind === 'allowance_set' && e.refId === 'vidyut')).toBe(true);
    expect(h.db.allowance.buyerId.find('bob')).toBeFalsy();
  });

  it('set_allowance: the public floor event label never carries a ladder step or a dollar amount', () => {
    setAllow(REF, 'vidyut', 250, 500);
    const labels = events().filter((e) => e.kind === 'allowance_set').map((e) => e.label);
    expect(labels).toHaveLength(1);
    for (const l of labels) expect(l).not.toMatch(/step|\d|\$/i);
  });

  it('set_allowance: only the buyer (for their own id) or the referee may call it; a seller, a stranger and another buyer cannot', () => {
    setAllow(REF, 'vidyut', 250, 500);
    expect(() => setAllow(A, 'vidyut', 1, 1)).toThrow(/not allowed/);
    expect(() => setAllow(STRANGER, 'vidyut', 1, 1)).toThrow(/not allowed/);
    expect(() => setAllow(BOB, 'vidyut', 1, 1)).toThrow(/not allowed/);
    expect(allowance()).toMatchObject({ perPurchaseLimit: 250, periodLimit: 500 });
  });

  it('set_allowance: the buyer can lower their own allowance but not raise it, and a fresh $0 stays $0 so the first buy calls', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    expect(() => setAllow(VIDYUT, 'vidyut', 50, 150)).toThrow(/clean deliveries/);
    expect(allowance()).toMatchObject({ perPurchaseLimit: 0, ladderStep: 0 });
    setAllow(REF, 'vidyut', 250, 500);
    setAllow(VIDYUT, 'vidyut', 100, 300);
    expect(allowance()).toMatchObject({ perPurchaseLimit: 100, periodLimit: 300, ladderStep: 1 });
    expect(() => setAllow(VIDYUT, 'vidyut', 101, 300)).toThrow(/clean deliveries/);
  });

  it('set_allowance: bad numbers are refused with the reason, and nothing changes', () => {
    setAllow(REF, 'vidyut', 250, 500);
    expect(() => setAllow(REF, 'vidyut', -1, 500)).toThrow(/per_purchase_limit/);
    expect(() => setAllow(REF, 'vidyut', 600, 500)).toThrow(/above period_limit/);
    expect(() => setAllow(REF, 'vidyut', 601, 1500)).toThrow(/top step/);
    expect(() => setAllow(REF, 'vidyut', 10, 100, 'year')).toThrow(/week or month/);
    expect(() => setAllow(REF, '', 10, 100)).toThrow(/buyer id/);
    expect(allowance()).toMatchObject({ perPurchaseLimit: 250, periodLimit: 500 });
  });

  it('a set allowance drives the buy decision, and a clean delivery then raises it without ever lowering it', () => {
    setAllow(REF, 'vidyut', 250, 500);
    mint(mandateArgs({ hash: 'in', id: 'm-in', nonce: 'in', ...win(250) }));
    expect(h.db.mandate.hash.find('in')!.withinAllowance).toBe(true);
    mint(mandateArgs({ hash: 'over', id: 'm-over', nonce: 'over', ...win(251) }));
    expect(h.db.mandate.hash.find('over')!.withinAllowance).toBe(false);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'in', paymentRef: 'pi_in', amount: 250, mode: 'sim' }));
    receive(VIDYUT, 'in');
    expect(allowance()).toMatchObject({ ladderStep: 3 });
    expect(allowance()!.perPurchaseLimit).toBeGreaterThanOrEqual(250);
  });

  it('the buyer screen sees its allowance; a seller sees none', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    expect(m.myAllowanceView(h.viewContext(VIDYUT) as any)).toHaveLength(1);
    expect(m.myAllowanceView(h.viewContext(A) as any)).toHaveLength(0);
  });
});

// ============================================================================================
// Lane D #37: advocate veto, allowed conditions, alternative lines, the cap, payment mode.
// ============================================================================================
describe('attach_advocate_card (the advocate relay, referee only)', () => {
  const veto = { recommendation: 'veto', ruleId: 'fit.gpu_length', text: 'The card is longer than your case allows', sourceUrl: 'https://example.com/spec', origin: 'SIM' };
  const closeIt = () => {
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    return [...h.db.roundResult.iter()];
  };

  it('a veto takes the cheapest bid out of the result with the cited reason, and the next bid ranks first', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(700)])));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b', ...veto }));
    const res = closeIt();
    const b = res.find((r) => r.bidId === 'bid-b')!;
    expect(b.rank).toBe(0);
    expect(b.reasons.join(' ')).toMatch(/advocate veto/i);
    expect(b.reasons.join(' ')).toContain('fit.gpu_length');
    expect(b.reasons.join(' ')).toContain('The card is longer than your case allows');
    expect(b.reasons.join(' ')).toContain('https://example.com/spec');
    expect(res.find((r) => r.bidId === 'bid-a')!.rank).toBe(1);
  });

  it('a caution or buy card is recorded and does not disqualify', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { ...veto, bidId: 'bid-a', recommendation: 'caution', ruleId: 'advocate.fit_unknown' }));
    const res = closeIt();
    expect(res[0]!.rank).toBe(1);
    expect([...h.db.bidCheck.iter()].map((c) => [c.kind, c.result])).toEqual([['advocate', 'caution']]);
  });

  it('#H1 defers the floor event (no seller, no text) until the round closes; the veto notification is immediate', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    const n0 = events().length;
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto }));
    expect(events().slice(n0)).toHaveLength(0); // no public event while the round stays open
    const feed = m.myNotificationsView(h.viewContext(VIDYUT) as any);
    const v = feed.filter((n: any) => n.klass === 'veto');
    expect(v).toHaveLength(1); // the private veto notification is never deferred
    expect(v[0]!.text).toContain('The card is longer than your case allows');
    expect(v[0]!.text).toContain('https://example.com/spec');
    expect(m.myNotificationsView(h.viewContext(BOB) as any).filter((n: any) => n.klass === 'veto')).toHaveLength(0);
    closeIt();
    const e = events().slice(n0).filter((x) => x.kind === 'advocate_card');
    expect(e).toHaveLength(1);
    expect(e[0]!.label).toMatch(/veto/);
    expect(e[0]!.sellerId).toBe('');
  });

  it('a veto must cite a source, the recommendation must be known, and the bid must exist', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto, sourceUrl: '' }))).toThrow(/source/);
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto, recommendation: 'maybe' }))).toThrow(/recommendation/);
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'nope', ...veto }))).toThrow(/no bid/);
    expect([...h.db.bidCheck.iter()]).toHaveLength(0);
  });

  it('refuses a card for a round that has already closed', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    closeIt();
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto }))).toThrow(/closed/);
  });

  it('SECURITY: a buyer cannot attach a card either', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    expect(() => run(VIDYUT, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto }))).toThrow(/not allowed/);
  });
});

describe('allowed conditions, alternative lines and the cap at close', () => {
  const openBoxNeed = () =>
    needArgs({ items: [{ skuSpec: GPU, condition: 'new', allowedConditions: ['new', 'open-box'], variant: 'retail', quantity: 1, unit: 'each' }] });
  const setup = (over: Partial<m.PostNeedArgs> = {}) => {
    run(VIDYUT, (ctx) => m.postNeed(ctx, { ...openBoxNeed(), ...over }));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS: 15 }));
  };
  const closeIt = () => {
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    return [...h.db.roundResult.iter()];
  };

  it('post_need stores allowed_conditions on the need item', () => {
    setup();
    expect([...h.db.needItem.iter()][0]!.allowedConditions).toEqual(['new', 'open-box']);
  });

  it('an open-box bid is ranked when the need allows new or open-box, and out when it does not', () => {
    setup();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780, { offeredCondition: 'open-box' })])));
    expect(closeIt().find((r) => r.bidId === 'bid-a')!.rank).toBe(1);
  });

  it('a new-only need still rejects the open-box bid', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780, { offeredCondition: 'open-box' })])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect([...h.db.roundResult.iter()][0]!.reasons.join(' ')).toMatch(/condition: offered open-box/);
  });

  it('a bid with two condition lines ranks on the cheapest allowed line, not the sum', () => {
    setup();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(900, { offeredCondition: 'new' }), line(760, { offeredCondition: 'open-box' })])));
    const r = closeIt()[0]!;
    expect(r.rank).toBe(1);
    expect(r.landed).toBe(760);
    expect(r.lines.map((l: any) => l.unitPrice)).toEqual([760]);
  });

  it('a bid over the buyer cap is out with over_cap and the public reason never states the cap', () => {
    setup({ spendLimit: 800 });
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(850)])));
    const res = closeIt();
    expect(res.find((r) => r.bidId === 'bid-a')!.rank).toBe(1);
    const over = res.find((r) => r.bidId === 'bid-b')!;
    expect(over.rank).toBe(0);
    expect(over.reasons.join(' ')).toMatch(/over_cap/);
    expect(JSON.stringify(res.map((r) => r.reasons))).not.toContain('800');
    expect(over.landed).toBe(850);
  });

  it('ranks on quality-adjusted price: a no-returns open-box bid loses to a slightly dearer new bid with returns', () => {
    setup();
    run(A, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-a', [line(760, { offeredCondition: 'open-box' })]), perks: ['free shipping'] }));
    run(B, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-b', [line(780)]), perks: ['30-day returns'] }));
    const res = closeIt();
    expect(res.find((r) => r.bidId === 'bid-b')!.rank).toBe(1);
    expect(res.find((r) => r.bidId === 'bid-a')!.rank).toBe(2);
  });

  it('#135 the stored adjusted_total is the real score rankBids used, with a reason, and rows land in adjusted order', () => {
    setup();
    run(A, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-a', [line(760, { offeredCondition: 'open-box' })]), perks: ['free shipping'] }));
    run(B, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-b', [line(780)]), perks: ['30-day returns'] }));
    const res = closeIt();
    const a = res.find((r) => r.bidId === 'bid-a')!;
    const b = res.find((r) => r.bidId === 'bid-b')!;
    // 760 open-box, no returns: condition +4%, no-returns +2% -> 760 * 1.06 = 805.6. 780 new with returns: no adjustment.
    expect(a.adjustedTotal).toBeCloseTo(805.6, 5);
    expect(a.adjustedTotal).not.toBe(a.landed);
    expect(a.adjustmentReason).toBe('open-box condition, +4%; under 30-day returns, +2%');
    expect(b.adjustedTotal).toBe(b.landed);
    expect(b.adjustmentReason).toBe('');
    expect([a, b].sort((x, y) => x.rank - y.rank).map((r) => r.adjustedTotal)).toEqual([b.adjustedTotal, a.adjustedTotal].sort((x, y) => x - y));
  });

  it('#135 a disqualified row stores its landed price as adjusted_total, with no reason (it was never ranked)', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(760, { offeredCondition: 'open-box' })])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const r = [...h.db.roundResult.iter()][0]!;
    expect(r.rank).toBe(0);
    expect(r.adjustedTotal).toBe(r.landed);
    expect(r.adjustmentReason).toBe('');
  });
});

describe('record_payment mode (sim or stripe_test)', () => {
  const ready = () => {
    mint(mandateArgs(win()));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
  };
  const last = () => events().filter((e) => e.kind === 'payment_recorded').pop()!;

  it('a SIM payment is labelled as a SIM stub, never as Stripe test mode', () => {
    ready();
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'ch_sim_1', amount: 780, mode: 'sim' }));
    expect(last().label).toMatch(/SIM/);
    expect(last().label).not.toMatch(/Stripe/);
    expect(last().origin).toBe('SIM');
    expect(h.db.payment.mandateHash.find('h1')!.mode).toBe('sim');
  });

  it('a Stripe test payment says Stripe test mode and is tagged LIVE', () => {
    ready();
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780, mode: 'stripe_test' }));
    expect(last().label).toMatch(/Stripe test mode/);
    expect(last().origin).toBe('LIVE');
    expect(h.db.payment.mandateHash.find('h1')!.mode).toBe('stripe_test');
  });

  it('refuses an unknown mode and writes nothing', () => {
    ready();
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'visa' }))).toThrow(/mode/);
    expect([...h.db.payment.iter()]).toHaveLength(0);
  });
});

describe('seller model: floor per condition and alternative lines', () => {
  it('[new 300, open-box 260] on a need that allows only new: the round closes with 300 chosen', () => {
    setupRound();
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c', [line(300), line(260, { offeredCondition: 'open-box' })])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const r = [...h.db.roundResult.iter()][0]!;
    expect(r).toMatchObject({ rank: 1, landed: 300 });
    expect(r.lines.map((l) => [l.offeredCondition || 'new', l.unitPrice])).toEqual([['new', 300]]);
  });

  it('a line below the floor for its condition rejects the whole bid, even when another line is fine', () => {
    setupRound();
    run(A, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'open-box', floor: 600 }));
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(760), line(590, { offeredCondition: 'open-box' })])));
    expect((m.myBidsView(h.viewContext(A) as any)[0] as any).rejectReason).toMatch(/open-box.*below this seller's floor/);
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect([...h.db.roundResult.iter()][0]!.rank).toBe(0);
  });

  it('a line with no floor set for its condition is skipped with the reason; another line can still win', () => {
    setupRound();
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c', [line(200, { offeredCondition: 'refurbished' }), line(720)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(650, { offeredCondition: 'refurbished' })])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const res = [...h.db.roundResult.iter()];
    expect(res.find((r) => r.bidId === 'bid-c')).toMatchObject({ rank: 1, landed: 720 });
    expect(res.find((r) => r.bidId === 'bid-b')!.reasons.join(' ')).toMatch(/no floor set/);
  });

  it('set_floor_for_condition refuses an unknown condition', () => {
    expect(() => run(A, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'mint', floor: 10 }))).toThrow(/condition/);
  });

  it('set_floor without a condition (the Lane D bridge call) covers every condition; an exact floor wins', () => {
    setupRound();
    run(B, (ctx) => m.setFloor(ctx, { skuSpec: GPU, floor: 640 }));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(645, { offeredCondition: 'refurbished' }), line(700)])));
    expect((m.myBidsView(h.viewContext(B) as any)[0] as any).lineRejects).toEqual(['', '']);
    run(C, (ctx) => m.setFloor(ctx, { skuSpec: GPU, floor: 900 }));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c', [line(720)])));
    expect((m.myBidsView(h.viewContext(C) as any)[0] as any).floorCheckPassed).toBe(true);
  });
});

// ============================================================================================
// PAIR CODE ATTEMPT LIMIT: 5 failures lock a code (and a caller); only the owner reissues.
// The code never appears in an error, event or notification.
// ============================================================================================
describe('pair code attempt limit', () => {
  let code = '';
  const tryPair = (who: Auth, c: string) => run(who, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'vidyut', code: c }));
  beforeEach(() => {
    run(OWNER, (ctx) => m.seedDemoChecked(ctx));
    code = h.db.pairCode.buyerId.find('vidyut')!.code;
  });
  const wrong = () => (code === '111111' ? '222222' : '111111');

  it('5 wrong attempts lock that identity, not the code; the caller sees its own failure count', () => {
    const first = as('first-screen');
    tryPair(first, wrong());
    expect(m.myPairAttemptsView(h.viewContext(first) as any)[0]!.failures).toBe(1);
    for (let i = 0; i < 4; i++) expect(tryPair(first, wrong())).toMatchObject({ paired: false });
    expect(() => tryPair(first, code)).toThrow(/locked/);
    expect(m.myRoleView(h.viewContext(first) as any)).toHaveLength(0);
    expect(h.db.pairCode.buyerId.find('vidyut')).toMatchObject({ locked: false, failedAttempts: 5 });
  });

  it('#135 one identity cannot burn other identities tries: a stranger with 5 misses leaves the owner screen free to pair', () => {
    const stranger = as('stranger-screen');
    for (let i = 0; i < 5; i++) tryPair(stranger, wrong());
    for (let i = 0; i < 4; i++) tryPair(as(`other-${i}`), wrong());
    const owner = as('stage-screen');
    expect(m.myPairAttemptsView(h.viewContext(owner) as any)).toHaveLength(0);
    expect(tryPair(owner, code)).toMatchObject({ paired: true });
    expect(m.myRoleView(h.viewContext(owner) as any)[0]).toMatchObject({ role: 'buyer', subjectId: 'vidyut' });
  });

  it('#135 failures still count per code across identities, for the operator', () => {
    for (let i = 0; i < 3; i++) tryPair(as(`screen-${i}`), wrong());
    expect(h.db.pairCode.buyerId.find('vidyut')!.failedAttempts).toBe(3);
  });

  it('one caller is stopped after 5 failures even across different codes', () => {
    run(OWNER, (ctx) => m.reissuePairCode(ctx, { buyerId: 'bob' }));
    const attacker = as('attacker');
    for (let i = 0; i < 3; i++) run(attacker, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'vidyut', code: wrong() }));
    for (let i = 0; i < 2; i++) run(attacker, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'bob', code: '000001' }));
    const bobCode = h.db.pairCode.buyerId.find('bob')!.code;
    expect(() => run(attacker, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'bob', code: bobCode }))).toThrow(/locked/);
    expect(h.db.pairCode.buyerId.find('vidyut')!.locked).toBe(false);
  });

  it('the operator can reissue a fresh code that works', () => {
    for (let i = 0; i < 5; i++) tryPair(as('screen-0'), wrong());
    run(OWNER, (ctx) => m.reissuePairCode(ctx, { buyerId: 'vidyut' }));
    const row = h.db.pairCode.buyerId.find('vidyut')!;
    expect(row).toMatchObject({ locked: false, failedAttempts: 0 });
    expect(tryPair(as('fresh-screen'), row.code)).toMatchObject({ paired: true });
  });

  it('reissue unlocks the same screen that locked itself; it pairs with the new code', () => {
    const screen = as('stage-screen');
    for (let i = 0; i < 5; i++) tryPair(screen, wrong());
    expect(() => tryPair(screen, code)).toThrow(/locked/);
    run(OWNER, (ctx) => m.reissuePairCode(ctx, { buyerId: 'vidyut' }));
    expect(tryPair(screen, h.db.pairCode.buyerId.find('vidyut')!.code)).toMatchObject({ paired: true });
  });

  it('a non-owner cannot reissue', () => {
    for (const who of [REF, VIDYUT, A, STRANGER]) {
      expect(() => run(who, (ctx) => m.reissuePairCode(ctx, { buyerId: 'vidyut' }))).toThrow(/not allowed/);
    }
  });

  it('a successful pair resets nothing for other codes', () => {
    run(OWNER, (ctx) => m.reissuePairCode(ctx, { buyerId: 'bob' }));
    for (let i = 0; i < 3; i++) run(as(`b-${i}`), (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'bob', code: '000001' }));
    tryPair(as('vidyut-screen'), code);
    expect(h.db.pairCode.buyerId.find('bob')!.failedAttempts).toBe(3);
  });

  it('the code never appears in an error, a floor event or a notification', () => {
    const x = as('x');
    for (let i = 0; i < 5; i++) tryPair(x, wrong());
    let msg = '';
    try { tryPair(x, code); } catch (e) { msg = String(e); }
    expect(msg).not.toContain(code);
    const text = JSON.stringify([...h.db.floorEvent.iter()].map((e) => e.label)) + JSON.stringify([...h.db.notification.iter()].map((n) => n.text));
    expect(text).not.toContain(code);
  });
});

describe('#135 pairing code format and code-wide throttle', () => {
  let code = '';
  const tryPair = (who: Auth, c: string) => run(who, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'vidyut', code: c }));
  const GUESS = 'ZZZZZ-ZZZZZ'; // never the real code: Crockford base32 excludes I L O U, so Z is valid but this exact string is astronomically unlikely to be drawn
  beforeEach(() => {
    run(OWNER, (ctx) => m.seedDemoChecked(ctx));
    code = h.db.pairCode.buyerId.find('vidyut')!.code;
  });

  it('the code is 10-character Crockford base32 (no I L O U), grouped as XXXXX-XXXXX', () => {
    expect(code).toMatch(/^[0-9A-Z]{5}-[0-9A-Z]{5}$/);
    expect(code).not.toMatch(/[ILOU]/);
  });

  it('pairing is case-insensitive and ignores the grouping dash', () => {
    expect(tryPair(as('lower'), code.toLowerCase())).toMatchObject({ paired: true });
    expect(tryPair(as('nodash'), code.replace('-', ''))).toMatchObject({ paired: true });
  });

  it('rotating 30 identities cannot pair by guessing: the code-wide throttle blocks guesses well before 30 identities run out', () => {
    let blocked = 0;
    for (let i = 0; i < 30; i++) {
      try {
        expect(tryPair(as(`rot-${i}`), GUESS)).toMatchObject({ paired: false });
      } catch (e) {
        blocked++;
        expect(String(e)).toMatch(/wait/);
      }
    }
    expect(blocked).toBeGreaterThan(0);
    for (let i = 0; i < 30; i++) expect(m.myRoleView(h.viewContext(as(`rot-${i}`)) as any)).toHaveLength(0);
  });

  it('the throttle engages at 20 misses on a code and releases after 60 s', () => {
    for (let i = 0; i < 20; i++) expect(tryPair(as(`m-${i}`), GUESS)).toMatchObject({ paired: false });
    expect(() => tryPair(as('m-throttled'), GUESS)).toThrow(/wait/);
    advance(59_000);
    expect(() => tryPair(as('m-still-throttled'), GUESS)).toThrow(/wait/);
    advance(1_000);
    expect(tryPair(as('m-released'), GUESS)).toMatchObject({ paired: false }); // normal miss again, not a throttle error
  });

  it('the owner still pairs with the real code once the throttle window passes', () => {
    for (let i = 0; i < 20; i++) tryPair(as(`n-${i}`), GUESS);
    const owner = as('owner-screen');
    expect(() => tryPair(owner, code)).toThrow(/wait/);
    advance(60_000);
    expect(tryPair(owner, code)).toMatchObject({ paired: true });
    expect(m.myRoleView(h.viewContext(owner) as any)[0]).toMatchObject({ role: 'buyer', subjectId: 'vidyut' });
  });

  it('a throttled wait never names the code', () => {
    for (let i = 0; i < 20; i++) tryPair(as(`q-${i}`), GUESS);
    let msg = '';
    try { tryPair(as('q-20'), code); } catch (e) { msg = String(e); }
    expect(msg).toMatch(/wait/);
    expect(msg).not.toContain(code);
  });
});

describe('b5 approval code on the buyer screen (shown only; the call approves, #191)', () => {
  const CODE = 'velvet falcon';
  const issue = (code = CODE) => run(REF, (ctx) => m.issueApprovalCode(ctx, { mandateHash: 'h1', code }));
  beforeEach(() => mint(mandateArgs(win())));

  it('only the referee issues the code; only the mandate buyer sees it, with amount, payee and expiry', () => {
    for (const who of [VIDYUT, A, STRANGER]) expect(() => run(who, (ctx) => m.issueApprovalCode(ctx, { mandateHash: 'h1', code: CODE }))).toThrow(/not allowed/);
    issue();
    const mine = m.myPendingApprovalsView(h.viewContext(VIDYUT) as any);
    expect(mine).toHaveLength(1);
    expect(mine[0]).toMatchObject({ mandateHash: 'h1', mandateId: 'mdt-1', amount: 780, payee: 'seller-c', code: CODE, origin: 'SIM' });
    for (const who of [BOB, A, STRANGER]) expect(m.myPendingApprovalsView(h.viewContext(who) as any)).toHaveLength(0);
  });

  it('an approved mandate never gets a code (nothing to approve)', () => {
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    expect(() => issue()).toThrow(/already approved/);
  });

  it('the shown code approves nothing by itself: the buyer screen cannot record an approval, the call relay can', () => {
    issue();
    expect(() => run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: CODE }))).toThrow(/not allowed/);
    expect(h.db.approval.mandateHash.find('h1')).toBeFalsy();
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    expect(m.myPendingApprovalsView(h.viewContext(VIDYUT) as any)).toHaveLength(0);
  });
});

describe('whole-build approval code on the buyer screen (issued before the call, no mandate exists yet)', () => {
  const CODE = 'amber harbor';
  const BUILD = 'agg-hash-1';
  const buildArgs = (over: Partial<Parameters<typeof m.issueBuildApprovalCode>[1]> = {}) => ({
    mandateHash: BUILD, buyerId: 'vidyut', amount: 3412.5, payee: 'your whole build (8 parts, 4 sellers)', expiryMinutes: 5, code: CODE, origin: 'LIVE', ...over,
  });
  const issue = (over: Partial<Parameters<typeof m.issueBuildApprovalCode>[1]> = {}) => run(REF, (ctx) => m.issueBuildApprovalCode(ctx, buildArgs(over)));
  const clear = (hash = BUILD) => run(REF, (ctx) => m.clearBuildApprovalCode(ctx, { mandateHash: hash }));
  const seen = (who: Auth) => m.myPendingApprovalsView(h.viewContext(who) as any);

  it('only the referee issues or clears; only the paired buyer sees the code, with amount, label and expiry', () => {
    for (const who of [VIDYUT, A, STRANGER]) {
      expect(() => run(who, (ctx) => m.issueBuildApprovalCode(ctx, buildArgs()))).toThrow(/not allowed/);
    }
    issue();
    for (const who of [VIDYUT, A, STRANGER]) expect(() => run(who, (ctx) => m.clearBuildApprovalCode(ctx, { mandateHash: BUILD }))).toThrow(/not allowed/);
    const mine = seen(VIDYUT);
    expect(mine).toHaveLength(1);
    expect(mine[0]).toMatchObject({ mandateHash: BUILD, amount: 3412.5, payee: 'your whole build (8 parts, 4 sellers)', code: CODE, origin: 'LIVE', failures: 0, locked: false });
    expect(ms(mine[0]!.expiry)).toBe(ms(T0) + 5 * 60_000);
    for (const who of [BOB, A, STRANGER]) expect(seen(who)).toHaveLength(0);
  });

  it('clearing hides it at once for the buyer and keeps the row (the call still counts as placed)', () => {
    issue();
    expect(seen(VIDYUT)).toHaveLength(1);
    clear();
    expect(seen(VIDYUT)).toHaveLength(0);
    expect(h.db.approvalCode.mandateHash.find(BUILD)).toBeTruthy();
    clear(); // idempotent: the runner clears in a finally and must never throw there
    clear('never-issued');
  });

  it('a new build code retires the buyer\'s earlier one, so exactly one code is ever on screen', () => {
    issue();
    issue({ mandateHash: 'agg-hash-2', code: 'copper meadow', amount: 900 });
    const rows = seen(VIDYUT);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ mandateHash: 'agg-hash-2', code: 'copper meadow' });
  });

  it('refuses bad input: empty code, no amount, expiry outside 1 to 10 minutes, a hash that is a real mandate, an unknown buyer', () => {
    expect(() => issue({ code: '   ' })).toThrow(/empty code/);
    expect(() => issue({ amount: 0 })).toThrow(/amount/);
    expect(() => issue({ amount: Number.NaN })).toThrow(/amount/);
    expect(() => issue({ expiryMinutes: 0 })).toThrow(/expiry/);
    expect(() => issue({ expiryMinutes: 11 })).toThrow(/expiry/);
    expect(() => issue({ buyerId: 'nobody' })).toThrow(/buyer/);
    mint(mandateArgs(win()));
    expect(() => issue({ mandateHash: 'h1' })).toThrow(/real mandate/);
    expect(seen(VIDYUT)).toHaveLength(0);
  });

  it('shows the code to the buyer and approves nothing: no approval row, no payment, the call relay needs a mandate', () => {
    issue();
    expect(() => run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: BUILD, method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: CODE }))).toThrow(/not allowed/);
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: BUILD, method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }))).toThrow(/no mandate/);
    expect([...h.db.approval.iter()]).toHaveLength(0);
  });

  it('per-deal codes are untouched: one buyer can have a deal code and a build code, and each clears on its own terms', () => {
    mint(mandateArgs(win()));
    run(REF, (ctx) => m.issueApprovalCode(ctx, { mandateHash: 'h1', code: 'velvet falcon' }));
    issue();
    expect(seen(VIDYUT).map((r) => r.mandateHash).sort()).toEqual(['agg-hash-1', 'h1']);
    clear();
    expect(seen(VIDYUT).map((r) => r.mandateHash)).toEqual(['h1']);
  });

  it('reset_demo wipes build codes with the rest', () => {
    issue();
    run(OWNER, (ctx) => m.resetDemoChecked(ctx));
    expect(seen(VIDYUT)).toHaveLength(0);
    expect([...h.db.approvalCode.iter()]).toHaveLength(0);
  });
});

describe('b6 seller screen: pooled lot band, own loss reports, strategy diff', () => {
  const report = (over: Partial<Parameters<typeof m.recordLossReport>[1]> = {}) => ({
    id: 'lr-1', roundId: 'round-1', sellerId: 'seller-a', won: false, gapBand: 'within5', reason: 'price', sourceUrl: 'https://example.com/sim/a',
    strategyDiff: [{ key: 'price_step', from: '0.00', to: '0.03' }], whatToChange: 'Lower your price by about 3%.', whatToChangeOrigin: 'SIM template', origin: 'SIM', ...over,
  });

  it('only the referee records a loss report; band and reason must be from the contract', () => {
    for (const who of [A, VIDYUT, STRANGER]) expect(() => run(who, (ctx) => m.recordLossReport(ctx, report()))).toThrow(/not allowed/);
    expect(() => run(REF, (ctx) => m.recordLossReport(ctx, report({ gapBand: '3.2%' })))).toThrow(/gap_band/);
    expect(() => run(REF, (ctx) => m.recordLossReport(ctx, report({ reason: 'secret threshold' })))).toThrow(/reason/);
    run(REF, (ctx) => m.recordLossReport(ctx, report()));
  });

  it('a seller sees only its own loss reports', () => {
    run(REF, (ctx) => m.recordLossReport(ctx, report()));
    run(REF, (ctx) => m.recordLossReport(ctx, report({ id: 'lr-2', sellerId: 'seller-b', reason: 'fit' })));
    expect(m.myLossReportsView(h.viewContext(A) as any).map((r: any) => r.id)).toEqual(['lr-1']);
    expect(m.myLossReportsView(h.viewContext(A) as any)[0]).toMatchObject({ gapBand: 'within5', reason: 'price', whatToChange: 'Lower your price by about 3%.' });
    expect(m.myLossReportsView(h.viewContext(B) as any).map((r: any) => r.id)).toEqual(['lr-2']);
    expect(m.myLossReportsView(h.viewContext(VIDYUT) as any)).toHaveLength(0);
  });

  it('a seller screen pairs with its own code, sees its reports, and can never bid', () => {
    run(OWNER, (ctx) => m.reissueSellerScreenCode(ctx, { sellerId: 'seller-a' }));
    expect(() => run(A, (ctx) => m.reissueSellerScreenCode(ctx, { sellerId: 'seller-a' }))).toThrow(/not allowed/);
    const code = h.db.pairCode.buyerId.find('seller:seller-a')!.code;
    const screen = as('seller-a-laptop');
    expect(run(screen, (ctx) => m.pairSellerScreen(ctx, { sellerId: 'seller-a', code: 'nope' }))).toMatchObject({ paired: false });
    expect(run(screen, (ctx) => m.pairSellerScreen(ctx, { sellerId: 'seller-a', code }))).toMatchObject({ paired: true });
    expect(m.myRoleView(h.viewContext(screen) as any)[0]).toMatchObject({ role: 'seller_screen', subjectId: 'seller-a' });
    run(REF, (ctx) => m.recordLossReport(ctx, report()));
    expect(m.myLossReportsView(h.viewContext(screen) as any)).toHaveLength(1);
    setupRound();
    expect(() => run(screen, (ctx) => m.placeBid(ctx, bidArgs('bid-x', [line(780)])))).toThrow(/not allowed/);
    expect(() => run(screen, (ctx) => m.pairBuyerScreen(ctx, { buyerId: 'vidyut', code: 'x' }))).toThrow(/not allowed/);
  });

  it('the pooled lot shows a ceiling band, never the spend limit', () => {
    setupRound();
    const v = m.sellerNeedsView(h.viewContext(A) as any);
    expect(v[0]).toMatchObject({ skuSpec: GPU, quantity: 1, ceilingBand: '$500 to $1,000' });
    expect(JSON.stringify(v, (_, x) => (typeof x === 'bigint' ? String(x) : x))).not.toMatch(/800/);
  });
});

describe('#60 agent events for the Fetch agents tile', () => {
  const ev = (over: Partial<Parameters<typeof m.recordAgentEvent>[1]> = {}) => ({
    agentName: 'Tech Bazaar Buyer', address: 'agent1qwxhy93uzmw5prlqldm8a2mz9gsmc2563um6th2l6z0pudw63juej97nmj8', text: 'Round open, 3 sellers invited', ts: '2026-10-24T08:00:00Z', origin: 'LIVE', ...over,
  });

  it('a seller, a buyer or a stranger cannot record an agent event', () => {
    for (const who of [A, VIDYUT, STRANGER]) expect(() => run(who, (ctx) => m.recordAgentEvent(ctx, ev()))).toThrow(/not allowed/);
    expect([...h.db.agentEvent.iter()]).toHaveLength(0);
  });

  it('the referee records one, public, with the given ts; an unknown origin is stored as SIM', () => {
    run(REF, (ctx) => m.recordAgentEvent(ctx, ev()));
    run(REF, (ctx) => m.recordAgentEvent(ctx, ev({ origin: 'REAL', text: 'x' })));
    const rows = [...h.db.agentEvent.iter()];
    expect(rows[0]).toMatchObject({ agentName: 'Tech Bazaar Buyer', text: 'Round open, 3 sellers invited', origin: 'LIVE' });
    expect(rows[0].ts.toDate().toISOString()).toBe('2026-10-24T08:00:00.000Z');
    expect(rows[1].origin).toBe('SIM');
  });

  it('refuses an address that is not an agent address and a bad ts', () => {
    expect(() => run(REF, (ctx) => m.recordAgentEvent(ctx, ev({ address: '0xabc' })))).toThrow(/address/);
    expect(() => run(REF, (ctx) => m.recordAgentEvent(ctx, ev({ ts: 'yesterday' })))).toThrow(/ts/);
  });
});

describe('#37 item 9 buyer display name', () => {
  it('seed_demo gives the buyer the display name Vidyut; only that buyer sees it', () => {
    run(OWNER, (ctx) => m.seedDemoChecked(ctx));
    expect(m.myBuyerProfileView(h.viewContext(VIDYUT) as any)).toEqual([expect.objectContaining({ buyerId: 'vidyut', displayName: 'Vidyut' })]);
    for (const who of [BOB, A, REF, STRANGER]) expect(m.myBuyerProfileView(h.viewContext(who) as any)).toHaveLength(0);
  });

  it('only the referee or the owner sets a display name; a seller or the buyer cannot', () => {
    for (const who of [A, VIDYUT, STRANGER]) expect(() => run(who, (ctx) => m.setBuyerProfile(ctx, { buyerId: 'vidyut', displayName: 'X' }))).toThrow(/not allowed/);
    expect(() => run(REF, (ctx) => m.setBuyerProfile(ctx, { buyerId: 'vidyut', displayName: '  ' }))).toThrow(/display name/);
    run(REF, (ctx) => m.setBuyerProfile(ctx, { buyerId: 'vidyut', displayName: 'Vidyut' }));
    expect(h.db.buyerProfile.buyerId.find('vidyut')?.displayName).toBe('Vidyut');
  });
});

describe('#108 demo seller personas and the ceiling band formatter', () => {
  it('seed_demo writes persona rows for the bridge sellers, with the learner named Gadget Grove (Vedant), all SIM', () => {
    run(OWNER, (ctx) => m.seedDemoChecked(ctx));
    const want: Record<string, string> = {
      'gadget-grove': 'Gadget Grove (Vedant)', 'bargain-bin': 'Bargain Bin Hardware (SIM)', lowball: 'Lowball Direct (SIM)',
      'fair-price-pc': 'Fair Price PC (SIM)', 'renew-refurb': 'ReNew Refurb (SIM)', 'shady-sam': "Shady Sam's Deals (SIM)",
    };
    for (const [id, name] of Object.entries(want)) expect(h.db.persona.sellerId.find(id)).toMatchObject({ name, origin: 'SIM' });
  });

  it('the ceiling band uses its own comma formatter (no Intl in the view)', () => {
    expect(m.ceilingBand(800)).toBe('$500 to $1,000');
    expect(m.ceilingBand(10_250)).toBe('$10,000 to $10,500');
    expect(m.ceilingBand(1_234_567)).toBe('$1,234,500 to $1,235,000');
    expect(m.ceilingBand(120)).toBe('under $500');
  });
});

describe('T11 contention: two buyers, one unit (stock holds)', () => {
  // Vidyut's round-1 and Bob's round-2 want the same SKU. Every seller states one unit in stock.
  const bidIn = (who: Auth, roundId: string, id: string, price: number, extra: Partial<{ offeredCondition: string; quantity: number }> = {}, more: ReturnType<typeof line>[] = []) =>
    run(who, (ctx) => m.placeBid(ctx, { ...bidArgs(id, [line(price, extra), ...more]), roundId }));
  const close = (roundId: string) => run(REF, (ctx) => m.closeRound(ctx, { roundId }));
  const resultOf = (bidId: string) => [...h.db.roundResult.iter()].find((r) => r.bidId === bidId)!;
  const holds = () => [...h.db.stockHold.iter()];

  function twoBuyerRounds(bobItems?: m.PostNeedArgs['items']) {
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(BOB, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-2', buyerId: 'bob', goalId: 'goal-2', ...(bobItems ? { items: bobItems } : {}) })));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS: 15 }));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-2', needId: 'need-2', windowS: 15 }));
    for (const r of ['1', '2']) {
      bidIn(A, `round-${r}`, `bid-a${r}`, 700);
      bidIn(B, `round-${r}`, `bid-b${r}`, 760);
      bidIn(C, `round-${r}`, `bid-c${r}`, 780);
    }
    advance(16_000);
  }

  it('the round that closes first wins the last unit and holds it; the later round skips that line and awards the next best bid', () => {
    twoBuyerRounds();
    close('round-1');
    expect(resultOf('bid-a1').rank).toBe(1);
    expect(holds()).toHaveLength(1);
    expect(holds()[0]).toMatchObject({ sellerId: 'seller-a', skuSpec: GPU, condition: 'new', qty: 1, roundId: 'round-1', bidId: 'bid-a1', state: 'held' });
    expect(Number(holds()[0]!.expiresAt.microsSinceUnixEpoch - h.db.round.id.find('round-1')!.closedAt!.microsSinceUnixEpoch)).toBe(120_000_000);

    close('round-2');
    expect(resultOf('bid-a2')).toMatchObject({ rank: 0, reasons: ['sold out to an earlier round'] });
    expect(resultOf('bid-b2').rank).toBe(1);
    expect(resultOf('bid-b1').rank).toBe(2);
    expect(holds().filter((x) => x.sellerId === 'seller-a' && x.state === 'held')).toHaveLength(1); // nobody is oversold
    expect(holds().find((x) => x.roundId === 'round-2')).toMatchObject({ sellerId: 'seller-b', state: 'held' });
  });

  it('close order decides who gets the unit: the same bids in the other order give the other outcome', () => {
    twoBuyerRounds();
    close('round-2');
    expect(resultOf('bid-a2').rank).toBe(1);
    close('round-1');
    expect(resultOf('bid-a1')).toMatchObject({ rank: 0, reasons: ['sold out to an earlier round'] });
    expect(resultOf('bid-b1').rank).toBe(1);
  });

  it('is deterministic: replaying the same two rounds gives the same ranks', () => {
    const ranks = () => {
      twoBuyerRounds();
      close('round-1');
      close('round-2');
      return [...h.db.roundResult.iter()].map((r) => `${r.bidId}:${r.rank}`).sort();
    };
    const first = ranks();
    h = createModuleTestHarness(spacetimedb, mod);
    h.clock.set(T0);
    // a fresh harness has no roles; rebuild them the way beforeEach does
    run(OWNER, (ctx) => m.init(ctx));
    for (const [who, role, sub] of [[REF, 'referee', 'market'], [VIDYUT, 'buyer', 'vidyut'], [BOB, 'buyer', 'bob'], [A, 'seller', 'seller-a'], [B, 'seller', 'seller-b'], [C, 'seller', 'seller-c']] as const) {
      const identity = idOf(who);
      run(OWNER, (ctx) => m.assignRole(ctx, { identity, role, subjectId: sub }));
    }
    for (const [who, cond, floor] of [[A, 'new', 700], [A, 'open-box', 100], [B, 'new', 650], [B, 'open-box', 100], [C, 'new', 100], [C, 'open-box', 100]] as const) {
      run(who, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: cond, floor }));
    }
    expect(ranks()).toEqual(first);
  });

  it('a seller with spare stock is not skipped: two units serve both rounds', () => {
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(BOB, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-2', buyerId: 'bob', goalId: 'goal-2' })));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS: 15 }));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-2', needId: 'need-2', windowS: 15 }));
    bidIn(A, 'round-1', 'bid-a1', 700, { quantity: 2 });
    bidIn(A, 'round-2', 'bid-a2', 700, { quantity: 2 });
    advance(16_000);
    close('round-1');
    close('round-2');
    expect(resultOf('bid-a1').rank).toBe(1);
    expect(resultOf('bid-a2').rank).toBe(1);
    expect(holds()).toHaveLength(2);
  });

  it('a denied approval releases the unit, so the later round can award it', () => {
    twoBuyerRounds();
    close('round-1');
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    run(VIDYUT, (ctx) => m.denyApproval(ctx, { mandateHash: 'h1', reason: 'wrong code' }));
    expect(holds()[0]!.state).toBe('released');
    expect(h.db.approval.mandateHash.find('h1')).toBeFalsy();
    expect(events().some((e) => e.kind === 'stock_released')).toBe(true);
    close('round-2');
    expect(resultOf('bid-a2').rank).toBe(1);
  });

  it('an unanswered hold expires after 2 minutes and the unit is released', () => {
    twoBuyerRounds();
    close('round-1');
    advance(119_000);
    expect(h.db.round.id.find('round-2')!.state).toBe('open'); // not closed yet: round 2 still waits
    advance(2_000);
    close('round-2');
    expect(resultOf('bid-a2').rank).toBe(1);
    expect(holds().find((x) => x.roundId === 'round-1')!.state).toBe('released');
  });

  it('a hold still inside its 2 minutes blocks the later round', () => {
    twoBuyerRounds();
    close('round-1');
    advance(100_000);
    close('round-2');
    expect(resultOf('bid-a2').rank).toBe(0);
  });

  it('a recorded payment sells the unit for good: it stays out of every later round', () => {
    twoBuyerRounds();
    close('round-1');
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    expect(holds()[0]!.state).toBe('held');
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 700, mode: 'sim' }));
    expect(holds()[0]!.state).toBe('sold');
    advance(3_600_000);
    close('round-2');
    expect(resultOf('bid-a2')).toMatchObject({ rank: 0, reasons: ['sold out to an earlier round'] });
    expect(events().some((e) => e.kind === 'stock_sold')).toBe(true);
  });

  it('replaying the same need after its own sale does not compete with itself: the seller is not sold out to its own earlier round', () => {
    twoBuyerRounds();
    close('round-1');
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 700, mode: 'sim' }));
    expect(holds()[0]!.state).toBe('sold');
    // The demo's round 2: the same need again, the same sellers, minutes later.
    advance(600_000);
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-r2', needId: 'need-1', windowS: 15 }));
    bidIn(A, 'round-r2', 'bid-a1-r2', 700);
    bidIn(B, 'round-r2', 'bid-b1-r2', 760);
    advance(16_000);
    close('round-r2');
    expect(resultOf('bid-a1-r2')).toMatchObject({ rank: 1, reasons: [] });
    expect(resultOf('bid-b1-r2').rank).toBe(2);
    // The second buyer's round still meets the sold unit, so two buyers keep competing for the last one.
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-r3', needId: 'need-2', windowS: 15 }));
    bidIn(A, 'round-r3', 'bid-a2-r3', 700);
    bidIn(B, 'round-r3', 'bid-b2-r3', 760);
    advance(16_000);
    close('round-r3');
    expect(resultOf('bid-a2-r3')).toMatchObject({ rank: 0, reasons: ['sold out to an earlier round'] });
    expect(resultOf('bid-b2-r3').rank).toBe(1);
  });

  it('the call starts the 2 minutes: creating the mandate renews the hold, so a slow stage does not lose the unit', () => {
    twoBuyerRounds();
    close('round-1');
    advance(110_000);
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    advance(100_000); // 210 s after the close, 100 s after the mandate
    close('round-2');
    expect(resultOf('bid-a2').rank).toBe(0);
  });

  it('a mandate for a unit that was released and then taken by another round is refused, never oversold', () => {
    twoBuyerRounds();
    close('round-1');
    advance(130_000);
    close('round-2'); // A's unit went to round 2
    expect(resultOf('bid-a2').rank).toBe(1);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })))).toThrow(/sold out to an earlier round/);
    expect(h.db.mandate.hash.find('h1')).toBeFalsy();
  });

  it('a released unit nobody took can be claimed again by its own mandate', () => {
    twoBuyerRounds();
    close('round-1');
    advance(130_000);
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    expect(holds().find((x) => x.roundId === 'round-1')!.state).toBe('held');
  });

  it('a sold-out line falls to the seller\'s other allowed line instead of dropping the whole bid', () => {
    twoBuyerRounds([{ skuSpec: GPU, condition: 'new', allowedConditions: ['new', 'open-box'], variant: 'retail', quantity: 1, unit: 'each' }]);
    // seller A also stated an open-box line in round 2 only: it needs its own bid, so re-open the case with a fresh round
    close('round-1'); // A's new line is held
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-3', needId: 'need-2', windowS: 15 }));
    run(A, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-a3', [line(700), line(650, { offeredCondition: 'open-box' })]), roundId: 'round-3' }));
    advance(16_000);
    close('round-3');
    const r = resultOf('bid-a3');
    expect(r.rank).toBeGreaterThan(0);
    expect(r.lines.map((l) => l.offeredCondition)).toEqual(['open-box']);
  });

  it('deny_approval: the mandate buyer or the referee only, never after an approval, and the public label names no amount', () => {
    twoBuyerRounds();
    close('round-1');
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    expect(() => run(BOB, (ctx) => m.denyApproval(ctx, { mandateHash: 'h1', reason: 'x' }))).toThrow(/not allowed/);
    expect(() => run(A, (ctx) => m.denyApproval(ctx, { mandateHash: 'h1', reason: 'x' }))).toThrow(/not allowed/);
    expect(() => run(REF, (ctx) => m.denyApproval(ctx, { mandateHash: 'nope', reason: 'x' }))).toThrow(/no mandate/);
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    expect(() => run(REF, (ctx) => m.denyApproval(ctx, { mandateHash: 'h1', reason: 'x' }))).toThrow(/already approved/);
    expect(holds()[0]!.state).toBe('held');
  });

  it('a referee denial releases too, writes one rejected attempt, and the public labels carry no amount or buyer', () => {
    twoBuyerRounds();
    close('round-1');
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    run(REF, (ctx) => m.denyApproval(ctx, { mandateHash: 'h1', reason: 'silence on the call' }));
    expect(holds()[0]!.state).toBe('released');
    expect([...h.db.rejectedAttempt.iter()].filter((x) => x.kind === 'approval')).toHaveLength(1);
    const text = JSON.stringify([...events().map((e) => e.label), ...[...h.db.rejectedAttempt.iter()].map((x) => x.reason)]);
    expect(text).not.toMatch(/780|vidyut|bob/i);
  });

  it('a mandate that names no awarded bid is refused (#191) and touches no hold', () => {
    twoBuyerRounds();
    close('round-1');
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ dealId: 'some-other-deal' })))).toThrow(/rank 1/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
    expect(holds()[0]!.state).toBe('held');
  });

  it('one unit is sold once: a second mandate on a sold deal is refused, and no second payment row is written', () => {
    twoBuyerRounds();
    close('round-1');
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 700, mode: 'sim' }));
    expect(holds()[0]!.state).toBe('sold');
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h2', id: 'mdt-2', nonce: 'n2', amount: 700, dealId: 'deal-bid-a1' })))).toThrow(/sold out to an earlier round/);
    expect([...h.db.mandate.iter()].map((x) => x.hash)).toEqual(['h1']);
    expect([...h.db.payment.iter()]).toHaveLength(1);
    expect(holds()).toHaveLength(1);
  });

  it('a mandate made before the sale cannot pay for the same unit afterwards', () => {
    twoBuyerRounds();
    close('round-1');
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h2', id: 'mdt-2', nonce: 'n2', amount: 700, dealId: 'deal-bid-a1' })));
    for (const hash of ['h1', 'h2']) run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: hash, method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi1', amount: 700, mode: 'sim' }));
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h2', paymentRef: 'pi2', amount: 700, mode: 'sim' }))).toThrow(/sold out to an earlier round/);
    expect([...h.db.payment.iter()].map((x) => x.mandateHash)).toEqual(['h1']);
    expect(holds()).toHaveLength(1);
  });

  it('another buyer cannot take or lock a rival\'s deal: a mandate on it is refused as not your deal', () => {
    twoBuyerRounds();
    close('round-1');
    expect(() => run(BOB, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'hb', id: 'mdt-b', nonce: 'nb', buyerId: 'bob', amount: 700, dealId: 'deal-bid-a1' })))).toThrow(/not allowed/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'hb', id: 'mdt-b', nonce: 'nb', buyerId: 'bob', amount: 700, dealId: 'deal-bid-a1' })))).toThrow(/not your deal/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
    expect(holds()[0]!.expiresAt.microsSinceUnixEpoch - h.db.round.id.find('round-1')!.closedAt!.microsSinceUnixEpoch).toBe(120_000_000n);
    // The owner of the deal is unaffected and still buys the unit.
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 700, mode: 'sim' }));
    expect([...h.db.payment.iter()].map((x) => x.mandateHash)).toEqual(['h1']);
  });

  it('a rival cannot make a mandate on your bid before any hold exists, so it cannot later deny that mandate to free your unit', () => {
    twoBuyerRounds();
    // Bid ids are public while the round is open; the round has not closed, so no hold exists yet.
    expect(holds()).toHaveLength(0);
    expect(() => run(BOB, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'hb', id: 'mdt-b', nonce: 'nb', buyerId: 'bob', amount: 700, dealId: 'deal-bid-a1' })))).toThrow(/not allowed/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'hb', id: 'mdt-b', nonce: 'nb', buyerId: 'bob', amount: 700, dealId: 'deal-bid-a1' })))).toThrow(/rank 1/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
    close('round-1');
    expect(holds().map((x) => [x.bidId, x.state])).toEqual([['bid-a1', 'held']]);
    // The same refusal with every deal id spelling, and for the referee relaying Bob.
    for (const dealId of ['bid-a1', 'deal-bid-a1', 'round-1:bid-a1']) {
      expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: `hx-${dealId}`, id: `mdt-${dealId}`, nonce: `nx-${dealId}`, buyerId: 'bob', amount: 700, dealId })))).toThrow(/not your deal/);
    }
    // Bob cannot free Vidyut's unit by denying: there is no mandate of his to deny.
    expect(() => run(BOB, (ctx) => m.denyApproval(ctx, { mandateHash: 'hb', reason: 'no' }))).toThrow(/no mandate/);
    expect(holds()[0]!.state).toBe('held');
    // Bob's own round is untouched: his round-2 winner is the next best bid and holds a different line.
    close('round-2');
    expect(holds().filter((x) => x.state === 'held').map((x) => x.bidId).sort()).toEqual(['bid-a1', 'bid-b2']);
    // The unit still goes to Vidyut.
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    expect(holds().find((x) => x.bidId === 'bid-a1')!.state).toBe('held');
  });

  it('a rival mandate made before any bid exists cannot free your held unit: denying releases only holds the denier owns', () => {
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(BOB, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-2', buyerId: 'bob', goalId: 'goal-2' })));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS: 15 }));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-2', needId: 'need-2', windowS: 15 }));
    // Bob names Vidyut's bid id before it exists: since #191 no mandate is made at all (not the referee, no rank 1 bid).
    expect(() => run(BOB, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'hb', id: 'mdt-b', nonce: 'nb', buyerId: 'bob', amount: 700, dealId: 'deal-bid-a1' })))).toThrow(/not allowed/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'hb', id: 'mdt-b', nonce: 'nb', buyerId: 'bob', amount: 700, dealId: 'deal-bid-a1' })))).toThrow(/rank 1/);
    for (const r of ['1', '2']) {
      bidIn(A, `round-${r}`, `bid-a${r}`, 700);
      bidIn(B, `round-${r}`, `bid-b${r}`, 760);
      bidIn(C, `round-${r}`, `bid-c${r}`, 780);
    }
    advance(16_000);
    close('round-1');
    expect(holds().map((x) => [x.bidId, x.state])).toEqual([['bid-a1', 'held']]);
    // Bob has no mandate to deny, so the hold on Vidyut's bid is not Bob's to release.
    expect(() => run(BOB, (ctx) => m.denyApproval(ctx, { mandateHash: 'hb', reason: 'no' }))).toThrow(/no mandate/);
    expect(holds().find((x) => x.bidId === 'bid-a1')!.state).toBe('held');
    expect(events().some((e) => e.kind === 'stock_released')).toBe(false);
    close('round-2');
    expect(resultOf('bid-a2')).toMatchObject({ rank: 0, reasons: ['sold out to an earlier round'] });
    expect(holds().find((x) => x.bidId === 'bid-a1')!.state).toBe('held');
    // The unit still goes to Vidyut.
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 700, dealId: 'deal-bid-a1' })));
    expect(holds().find((x) => x.bidId === 'bid-a1')!.state).toBe('held');
  });

  it('a line short of the need with no holds keeps its true quantity reason, not a false sold-out one', () => {
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ items: [{ skuSpec: GPU, condition: 'new', allowedConditions: [], variant: 'retail', quantity: 2, unit: 'each' }] })));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS: 15 }));
    bidIn(A, 'round-1', 'bid-a1', 700, { quantity: 1 });
    bidIn(B, 'round-1', 'bid-b1', 760, { quantity: 2 });
    advance(16_000);
    close('round-1');
    const short = resultOf('bid-a1');
    expect(short.rank).toBe(0);
    expect(short.reasons.join(' ')).toMatch(/qty_available 1 is below the 2 needed/);
    expect(short.reasons).not.toContain('sold out to an earlier round');
    expect(events().some((e) => e.kind === 'stock_sold_out')).toBe(false);
    expect(holds().filter((x) => x.sellerId === 'seller-a')).toHaveLength(0);
  });

  it('reset_demo clears every hold', () => {
    twoBuyerRounds();
    close('round-1');
    run(OWNER, (ctx) => m.resetDemoChecked(ctx));
    expect(holds()).toHaveLength(0);
  });

  it('public hold rows carry the seller, line and round only: no buyer id, amount or mandate', () => {
    twoBuyerRounds();
    close('round-1');
    expect(Object.keys(holds()[0]!).sort()).toEqual(['bidId', 'condition', 'expiresAt', 'id', 'qty', 'roundId', 'sellerId', 'skuSpec', 'state']);
  });
});

// ============================================================================================
// #191 red team and judge: approval by phone call only, one winner, mandates only for the real winner.
// ============================================================================================
describe('#191 approval and mandate holes', () => {
  /** A closed round where seller A bids 780 (rank 1 unless something below says otherwise). */
  const wonByA = () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
  };
  const voice = (over: Partial<Parameters<typeof m.recordApproval>[1]> = {}) =>
    ({ mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1', ...over });

  it('#191-1 a buyer cannot record an approval; only the referee relays the call', () => {
    wonByA();
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(() => run(VIDYUT, (ctx) => m.recordApproval(ctx, voice()))).toThrow(/not allowed/);
    expect([...h.db.approval.iter()]).toHaveLength(0);
  });

  it('#191-1 the method is voice_code or allowance only (typed_code is refused)', () => {
    wonByA();
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    for (const method of ['typed_code', 'sms', '']) expect(() => run(REF, (ctx) => m.recordApproval(ctx, voice({ method })))).toThrow(/method/);
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, voice({ method: 'allowance' })))).toThrow(/allowance/);
    expect([...h.db.approval.iter()]).toHaveLength(0);
  });

  it('#191-1 a voice approval needs the VoiceApproval id, and the approval row keeps it', () => {
    wonByA();
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, voice({ voiceApprovalId: '' })))).toThrow(/VoiceApproval/);
    run(REF, (ctx) => m.recordApproval(ctx, voice()));
    expect(h.db.approval.mandateHash.find('h1')).toMatchObject({ method: 'voice_code', voiceApprovalId: 'va-1' });
  });

  it('#191-2 approve_typed is gone: no reducer and no function (no typed-code fallback)', () => {
    expect('approve_typed' in mod).toBe(false);
    expect('approveTyped' in m).toBe(false);
    expect('issue_approval_code' in mod).toBe(true);
  });

  it('#191-3 only the referee creates a mandate', () => {
    wonByA();
    expect(() => run(VIDYUT, (ctx) => m.createMandate(ctx, mandateArgs()))).toThrow(/not allowed/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
  });

  it('#191-3 a Shield blocked rank 0 bid, or a bid that is not rank 1, gets no mandate', () => {
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(700)])));
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c', [line(790)])));
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-b', verdict: 'block', ruleIds: ['shield.payee.swap'], origin: 'SIM' }));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ dealId: 'round-1:bid-b', payee: 'seller-b', amount: 700 })))).toThrow(/rank 1/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ dealId: 'round-1:bid-c', payee: 'seller-c', amount: 790 })))).toThrow(/rank 1/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ dealId: 'no-such-deal' })))).toThrow(/rank 1/);
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect([...h.db.mandate.iter()].map((x) => x.payee)).toEqual(['seller-a']);
  });

  it('#191-3 payee must be the winning seller, amount its landed price, expiry 1 to 10 minutes', () => {
    wonByA();
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ payee: 'mallory@payout.example.test' })))).toThrow(/payee/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 9999 })))).toThrow(/amount/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ expiryMinutes: 10_000_000 })))).toThrow(/expiry/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ expiryMinutes: 0 })))).toThrow(/expiry/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(h.db.mandate.hash.find('h1')).toMatchObject({ payee: 'seller-a', amount: 780 });
  });

  it('#191-4 one winner: a cheaper bid the advocate flags caution (fit unconfirmed) is held back below a confirmed fit, with its reason', () => {
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(700)])));
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b', recommendation: 'caution', ruleId: 'fit.unconfirmed', text: 'card length not on the listing', sourceUrl: 'https://x.test/b', origin: 'SIM' }));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', recommendation: 'buy', ruleId: '', text: 'all checks pass', sourceUrl: '', origin: 'SIM' }));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const res = [...h.db.roundResult.iter()];
    expect(res.find((r) => r.bidId === 'bid-a')).toMatchObject({ rank: 1, reasons: [] });
    const held = res.find((r) => r.bidId === 'bid-b')!;
    expect(held.rank).toBe(2);
    expect(held.reasons).toEqual(['held back: advocate caution (fit.unconfirmed: card length not on the listing)']);
    expect(events().find((e) => e.kind === 'auction_closed')!.sellerId).toBe('seller-a');
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ dealId: 'round-1:bid-b', payee: 'seller-b', amount: 700 })))).toThrow(/rank 1/);
  });

  it('#191-6 the public mandate_created label is the same inside and outside the allowance', () => {
    run(REF, (ctx) => m.setAllowanceChecked(ctx, { buyerId: 'vidyut', perPurchaseLimit: 600, periodLimit: 1500, period: 'month' }));
    wonByA(); // 780: over the per-buy limit, needs the call
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-2' })));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-2', needId: 'need-2', windowS: 15 }));
    run(C, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-c2', [line(200)]), roundId: 'round-2' }));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-2' }));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h2', id: 'mdt-2', nonce: 'n2', dealId: 'round-2:bid-c2', payee: 'seller-c', amount: 200 })));
    expect(h.db.mandate.hash.find('h1')!.withinAllowance).toBe(false);
    expect(h.db.mandate.hash.find('h2')!.withinAllowance).toBe(true);
    const labels = events().filter((e) => e.kind === 'mandate_created').map((e) => e.label);
    expect(labels).toEqual(['Deal ready for approval', 'Deal ready for approval']);
  });

  it('#325-1 a NaN amount is refused, not treated as equal to the landed price', () => {
    wonByA();
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: NaN })))).toThrow(/amount/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: Infinity })))).toThrow(/amount/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
  });

  it('#325-2 a Shield block or failed claim on the winning bid refuses the mandate, however the card reached it', () => {
    wonByA();
    // A card reaching the bid outside attach_claim_check (eg. a row written directly, as a stand-in for any
    // path other than the reducer): create_mandate must still catch it, not trust that ranking screened it.
    run(REF, (ctx) => ctx.db.bidCheck.insert({ id: 0n, bidId: 'bid-a', kind: 'claim', result: 'false', detail: 'card fits', evidenceUrl: 'https://x.test', origin: 'SIM', at: ctx.timestamp }));
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs()))).toThrow(/Shield block|claim check|veto/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
  });

  it('#389 (#396-1) create_mandate names a failed claim on the winning bid, not just a generic refusal', () => {
    wonByA();
    run(REF, (ctx) => ctx.db.bidCheck.insert({ id: 0n, bidId: 'bid-a', kind: 'claim', result: 'false', detail: 'card fits', evidenceUrl: 'https://x.test', origin: 'SIM', at: ctx.timestamp }));
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs()))).toThrow(/failed claim/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
  });

  it('#389 (#396-1a) attach_verdict and attach_claim_check succeed on an already-closed round (the demo\'s beat 3: open, bid, close, then attach a Shield block); create_mandate still refuses', () => {
    wonByA();
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-a', verdict: 'block', ruleIds: ['shield.x'], origin: 'SIM' }));
    expect([...h.db.bidCheck.iter()].filter((c) => c.bidId === 'bid-a' && c.kind === 'shield')).toHaveLength(1);
    // attach_claim_check on the same already-closed round's bid: also succeeds, and still blocks the mandate.
    run(REF, (ctx) => m.attachClaimCheck(ctx, { bidId: 'bid-a', claim: 'c', check: 'false', evidenceUrl: '', origin: 'SIM' }));
    expect([...h.db.bidCheck.iter()].filter((c) => c.bidId === 'bid-a' && c.kind === 'claim')).toHaveLength(1);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs()))).toThrow(/Shield block/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
  });

  it('#389 (#396-1b) create_mandate refuses a Shield quarantine, not only a block', () => {
    wonByA();
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-a', verdict: 'quarantine', ruleIds: ['shield.y'], origin: 'SIM' }));
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs()))).toThrow(/Shield block/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
  });

  it('#389 (#396-1c) create_mandate refuses a bid the advocate vetoed', () => {
    wonByA();
    // The advocate card's own attach reducer still refuses a closed round (unchanged), so this stands in for
    // a veto that reached the bid before close but was missed by ranking (eg. a race on the same tick).
    run(REF, (ctx) => ctx.db.bidCheck.insert({ id: 0n, bidId: 'bid-a', kind: 'advocate', result: 'veto', detail: 'fit.x: too long', evidenceUrl: 'https://x.test', origin: 'SIM', at: ctx.timestamp }));
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs()))).toThrow(/veto/);
    expect([...h.db.mandate.iter()]).toHaveLength(0);
  });

  it('#325-3 the public approval_recorded label is the same for the allowance path and the voice-code call', () => {
    run(REF, (ctx) => m.setAllowanceChecked(ctx, { buyerId: 'vidyut', perPurchaseLimit: 600, periodLimit: 1500, period: 'month' }));
    wonByA(); // 780: over the per-buy limit, needs the call
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', voiceApprovalId: 'va-1' }));
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-2' })));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-2', needId: 'need-2', windowS: 15 }));
    run(C, (ctx) => m.placeBid(ctx, { ...bidArgs('bid-c2', [line(200)]), roundId: 'round-2' }));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-2' }));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h2', id: 'mdt-2', nonce: 'n2', dealId: 'round-2:bid-c2', payee: 'seller-c', amount: 200 })));
    const labels = events().filter((e) => e.kind === 'approval_recorded').map((e) => e.label);
    expect(labels).toEqual(['Deal approved', 'Deal approved']);
  });

  it('#191-5 my_bid_checks: the buyer sees the veto, Shield and claim rows on bids in its own rounds; nobody else does', () => {
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(700)])));
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-b', verdict: 'block', ruleIds: ['shield.payee.swap', 'shield.hidden.instruction'], origin: 'LIVE' }));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b', recommendation: 'veto', ruleId: 'fit.gpu_length', text: '336 mm card, case allows 305 mm', sourceUrl: 'https://x.test/b', origin: 'SIM' }));
    const mine = m.myBidChecksView(h.viewContext(VIDYUT) as any);
    expect(mine.map((c) => [c.bidId, c.kind, c.result, c.sellerId])).toEqual([['bid-b', 'shield', 'block', 'seller-b'], ['bid-b', 'advocate', 'veto', 'seller-b']]);
    expect(mine[1]).toMatchObject({ detail: 'fit.gpu_length: 336 mm card, case allows 305 mm', evidenceUrl: 'https://x.test/b', persona: 'p', bidOrigin: 'SIM' });
    for (const who of [BOB, A, B, STRANGER]) expect(m.myBidChecksView(h.viewContext(who) as any)).toHaveLength(0);
  });

  it('#191-5 my_deals: the buyer sees its own mandate with the approval and payment rows; nobody else does', () => {
    wonByA();
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(m.myDealsView(h.viewContext(VIDYUT) as any)[0]).toMatchObject({ mandateHash: 'h1', amount: 780, payee: 'seller-a', approvalMethod: '', paymentRef: '' });
    run(REF, (ctx) => m.recordApproval(ctx, voice()));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'ch_sim_1', amount: 780, mode: 'sim' }));
    const d = m.myDealsView(h.viewContext(VIDYUT) as any);
    expect(d).toHaveLength(1);
    expect(d[0]).toMatchObject({ dealId: 'round-1:bid-a', approvalMethod: 'voice_code', voiceApprovalId: 'va-1', paymentRef: 'ch_sim_1', paymentMode: 'sim' });
    expect(d[0]!.approvedAt).toBeDefined();
    expect(d[0]!.paidAt).toBeDefined();
    for (const who of [BOB, A, STRANGER]) expect(m.myDealsView(h.viewContext(who) as any)).toHaveLength(0);
  });
});

// ============================================================================================
// #336: sealed knockout rounds, up to maxStages best-and-final-offer stages.
// ============================================================================================
describe('#336 sealed knockout rounds', () => {
  function openKnockout(maxStages = 3, stageWindowS = 15) {
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(REF, (ctx) => m.openKnockoutRound(ctx, { roundId: 'round-1', needId: 'need-1', stageWindowS, maxStages }));
  }

  it('#336-1 deterministic knockout: the worst clean offer goes out each stage; champion before the last stage is an early finish', () => {
    openKnockout(3, 15);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' }));
    const stage1 = [...h.db.roundResult.roundId.filter('round-1')].filter((x) => x.stage === 1);
    expect(stage1.find((x) => x.sellerId === 'seller-a')!.status).toBe('knocked_out'); // highest price: last placed
    expect(stage1.find((x) => x.sellerId === 'seller-b')!.status).toBe('advancing');
    expect(stage1.find((x) => x.sellerId === 'seller-c')!.status).toBe('advancing');
    expect(h.db.round.id.find('round-1')).toMatchObject({ stage: 2, state: 'open' });

    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b2', [line(740)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c2', [line(690)])));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' }));
    expect(h.db.round.id.find('round-1')!.state).toBe('closed'); // champion reached before stage 3 of 3
    const stage2 = [...h.db.roundResult.roundId.filter('round-1')].filter((x) => x.stage === 2);
    expect(stage2.find((x) => x.sellerId === 'seller-b')!.status).toBe('knocked_out');
    expect(stage2.find((x) => x.sellerId === 'seller-c')).toMatchObject({ status: 'champion', rank: 1 });
  });

  it('#336-2 stage 2 refuses a non-survivor, a non-strictly-lower offer, and a second offer in the same stage', () => {
    openKnockout(3, 15);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' })); // seller-a knocked out
    expect(() => run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a2', [line(600)])))).toThrow(/surviving/);
    expect(() => run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b2', [line(760)])))).toThrow(/strictly below/);
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b2', [line(740)])));
    expect(() => run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b3', [line(720)])))).toThrow(/one offer per seller per stage/);
  });

  it('#336-3 a floor break at stage 2 still knocks the seller out, even on the cheapest offer', () => {
    openKnockout(3, 15);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)]))); // seller-b floor (new) is 650
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' })); // seller-a knocked out
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b2', [line(600)]))); // strictly lower than 760, but below its own floor
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c2', [line(690)])));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' }));
    const stage2 = [...h.db.roundResult.roundId.filter('round-1')].filter((x) => x.stage === 2);
    expect(stage2.find((x) => x.sellerId === 'seller-b')).toMatchObject({ status: 'knocked_out', reasons: ['below this seller floor'] });
    expect(stage2.find((x) => x.sellerId === 'seller-c')!.status).toBe('champion');
  });

  it('#336-4 the only bidder breaking a rule ends the round with no deal; no mandate is possible', () => {
    openKnockout(3, 15);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-a1', verdict: 'block', ruleIds: ['shield.x'], origin: 'SIM' }));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' }));
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    const results = [...h.db.roundResult.roundId.filter('round-1')];
    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({ sellerId: 'seller-a', status: 'knocked_out' });
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ dealId: 'round-1:bid-a1', payee: 'seller-a', amount: 790 })))).toThrow(/rank 1/);
  });

  it("#336-5 my_standing shows only the seller's own round, never another seller's price", () => {
    openKnockout(3, 15);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    const bStanding = m.myStandingView(h.viewContext(B) as any);
    expect(bStanding).toEqual([{ roundId: 'round-1', stillIn: true, reason: '', lastOfferSkuSpec: GPU, lastOfferPrice: 760 }]);
    expect(JSON.stringify(bStanding)).not.toContain('790'); // never seller A's price
    const aStanding = m.myStandingView(h.viewContext(A) as any);
    expect(aStanding[0]).toMatchObject({ lastOfferPrice: 790 });
    expect(m.myStandingView(h.viewContext(STRANGER) as any)).toHaveLength(0);
  });

  it('#266-1 a caution-flagged lone bidder is still crowned champion, but carries the held-back reason', () => {
    openKnockout(3, 15);
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(700)])));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b1', recommendation: 'caution', ruleId: 'fit.unconfirmed', text: 'card length not on the listing', sourceUrl: 'https://x.test/b', origin: 'SIM' }));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' })); // only bidder: no one to knock out, crowned at once
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    const champ = [...h.db.roundResult.roundId.filter('round-1')].find((x) => x.sellerId === 'seller-b')!;
    expect(champ.status).toBe('champion');
    expect(champ.reasons).toEqual(['held back: advocate caution (fit.unconfirmed: card length not on the listing)']);
  });

  it('#266-2 a mid-round advancing row never reveals the survivor\'s price', () => {
    openKnockout(3, 15);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' })); // seller-a knocked out; b and c advance (not the final stage)
    const advancing = [...h.db.roundResult.roundId.filter('round-1')].filter((x) => x.status === 'advancing');
    expect(advancing).toHaveLength(2);
    for (const row of advancing) {
      expect(row.landed).toBe(0);
      expect(row.lines).toEqual([]);
      expect(row.adjustedTotal).toBe(0);
    }
    const prices = advancing.map((row) => ({ landed: row.landed, lines: row.lines, adjustedTotal: row.adjustedTotal }));
    expect(JSON.stringify(prices)).not.toContain('760');
    expect(JSON.stringify(prices)).not.toContain('700');
  });

  it('#363 a mid-round advancing row never reveals relative standing either; rank stays 0 until a stage crowns a champion', () => {
    openKnockout(3, 15);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' })); // seller-a knocked out; b and c advance (not the final stage)
    const advancing = [...h.db.roundResult.roundId.filter('round-1')].filter((x) => x.status === 'advancing');
    expect(advancing).toHaveLength(2);
    for (const row of advancing) expect(row.rank).toBe(0);
  });

  it('#266-3 create_mandate refuses a stale advancing-stage row from a round still open', () => {
    openKnockout(3, 15);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    advance(16_000);
    run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' })); // seller-a knocked out; b and c advancing, round open (stage 2 of 3)
    expect(h.db.round.id.find('round-1')!.state).toBe('open');
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ dealId: 'round-1:bid-c1', payee: 'seller-c', amount: 700 }))))
      .toThrow(/closed round/);
  });
});

// ============================================================================================
// Lane D takeover of #416 (red team H1/H2, reviewer findings 1 to 3): a sealed round leaks nothing
// public before it closes, and every path that closes a knockout round reveals what was held back.
// ============================================================================================
describe('sealed rounds leak nothing before close (supersedes #416)', () => {
  function openKnockout(maxStages = 3, stageWindowS = 15) {
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(REF, (ctx) => m.openKnockoutRound(ctx, { roundId: 'round-1', needId: 'need-1', stageWindowS, maxStages }));
  }
  const closeStage = () => run(REF, (ctx) => m.closeStage(ctx, { roundId: 'round-1' }));
  const resultOf = (sellerId: string, stage = 1) => [...h.db.roundResult.roundId.filter('round-1')].find((x) => x.sellerId === sellerId && x.stage === stage)!;
  const shieldBlock = (bidId: string) => run(REF, (ctx) => m.attachVerdict(ctx, { bidId, verdict: 'block', ruleIds: ['shield.x'], origin: 'SIM' }));
  const json = (v: unknown) => JSON.stringify(v, (_k, x) => (typeof x === 'bigint' ? x.toString() : x));

  it('1 (H): close_stage that crowns a champion flushes the deferred Shield verdict of the knocked-out seller', () => {
    openKnockout();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    const n0 = events().length;
    shieldBlock('bid-a1');
    expect(events().slice(n0)).toHaveLength(0); // deferred while open
    advance(16_000);
    closeStage();
    expect(h.db.round.id.find('round-1')).toMatchObject({ state: 'closed' });
    expect(resultOf('seller-b')).toMatchObject({ status: 'champion', rank: 1 });
    const verdicts = events().filter((e) => e.kind === 'verdict');
    expect(verdicts).toHaveLength(1);
    expect(verdicts[0]).toMatchObject({ refId: 'bid-a1', label: 'Bazaar Shield: block' });
    expect(events().filter((e) => e.kind === 'auction_closed')).toHaveLength(1);
  });

  it('1 (H): close_stage with no survivor (the only bidder is blocked) flushes the verdict too', () => {
    openKnockout();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    shieldBlock('bid-a1');
    advance(16_000);
    closeStage();
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    expect(events().filter((e) => e.kind === 'verdict').map((e) => e.refId)).toEqual(['bid-a1']);
  });

  it('1 (H): a knockout stage that leaves the round open keeps the checks deferred, and the final close flushes each once', () => {
    openKnockout();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b1', recommendation: 'buy', ruleId: 'advocate.fit_ok', text: 'fits', sourceUrl: 'https://x.test/b', origin: 'SIM' }));
    advance(16_000);
    closeStage(); // a knocked out, b and c advance, round stays open
    expect(h.db.round.id.find('round-1')!.state).toBe('open');
    expect(events().filter((e) => e.kind === 'advocate_card')).toHaveLength(0);
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b2', [line(740)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c2', [line(690)])));
    advance(16_000);
    closeStage();
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    expect(events().filter((e) => e.kind === 'advocate_card').map((e) => e.refId)).toEqual(['bid-b1']);
  });

  it("2 (M): an open round's public events name no bid and no seller, even for a below-floor bid", () => {
    setupRound();
    const n0 = events().length;
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(690)]))); // below seller-a's 700 floor
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-b1', verdict: 'block', ruleIds: ['shield.x'], origin: 'SIM' }));
    const open = events().slice(n0);
    expect(json(open)).not.toMatch(/bid-a1|bid-b1|seller-a|seller-b|floor/i);
    for (const e of open) {
      expect(e.sellerId).toBe('');
      expect(['bid', 'bid_check']).not.toContain(e.refTable);
    }
    expect(h.db.round.id.find('round-1')!.sealedCount).toBe(2); // the count stays public
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const after = events().slice(n0);
    expect(after.find((e) => e.kind === 'bid_rejected')).toMatchObject({ refId: 'bid-a1', sellerId: 'seller-a' });
    expect(after.find((e) => e.kind === 'bid_sealed')).toMatchObject({ refId: 'bid-b1', sellerId: 'seller-b' });
  });

  it('2 (M): the revealed bid events keep the moment each bid arrived, in arrival order', () => {
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    const tB = h.db.bid.id.find('bid-b1')!.sealedAt;
    advance(4_000);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    const tA = h.db.bid.id.find('bid-a1')!.sealedAt;
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const arrivals = events().filter((e) => e.kind === 'bid_sealed');
    expect(arrivals.map((e) => e.refId)).toEqual(['bid-b1', 'bid-a1']);
    expect(arrivals.map((e) => e.at.microsSinceUnixEpoch)).toEqual([tB.microsSinceUnixEpoch, tA.microsSinceUnixEpoch]);
  });

  it('2 (M): a knockout stage close reveals that stage bids; the next stage bids stay hidden until their own close', () => {
    openKnockout();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    expect(events().some((e) => e.kind === 'bid_sealed' || e.kind === 'bid_rejected')).toBe(false);
    advance(16_000);
    closeStage();
    expect(events().filter((e) => e.kind === 'bid_sealed').map((e) => e.refId).sort()).toEqual(['bid-a1', 'bid-b1', 'bid-c1']);
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b2', [line(740)])));
    expect(events().some((e) => e.refId === 'bid-b2')).toBe(false);
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c2', [line(690)])));
    advance(16_000);
    closeStage();
    expect(events().filter((e) => e.kind === 'bid_sealed').map((e) => e.refId).sort()).toEqual(['bid-a1', 'bid-b1', 'bid-b2', 'bid-c1', 'bid-c2']);
  });

  it('3 (M): a knocked-out row of a stage that leaves the round open shows no rank, price or lines until the round closes', () => {
    openKnockout();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    advance(16_000);
    closeStage();
    expect(h.db.round.id.find('round-1')!.state).toBe('open');
    const a = resultOf('seller-a');
    expect(a.status).toBe('knocked_out');
    expect(a).toMatchObject({ rank: 0, landed: 0, adjustedTotal: 0 });
    expect(a.lines).toHaveLength(0);
    for (const sid of ['seller-b', 'seller-c']) expect(resultOf(sid)).toMatchObject({ status: 'advancing', rank: 0, landed: 0 });
    for (const row of h.db.roundResult.roundId.filter('round-1')) expect(json(row)).not.toMatch(/790|760|700/);

    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b2', [line(740)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c2', [line(690)])));
    advance(16_000);
    closeStage();
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    const revealed = resultOf('seller-a');
    expect(revealed).toMatchObject({ status: 'knocked_out', rank: 3, landed: 790, reasons: ['knocked out: last placed this stage'] });
    expect(revealed.adjustedTotal).toBeGreaterThanOrEqual(790); // the real quality-adjusted score, not the blank 0
    expect(revealed.lines.map((l) => l.unitPrice)).toEqual([790]);
    expect([...h.db.roundResultSealed.iter()]).toHaveLength(0); // nothing left held back
  });

  it('3 (M): a rule-breaker knocked out while the round stays open hides its price too, and shows it at close', () => {
    const D = as('seller-d');
    const dIdentity = idOf(D);
    run(OWNER, (ctx) => m.assignRole(ctx, { identity: dIdentity, role: 'seller', subjectId: 'seller-d' }));
    run(D, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'new', floor: 100 }));
    openKnockout();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a1', [line(790)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b1', [line(760)])));
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c1', [line(700)])));
    run(D, (ctx) => m.placeBid(ctx, bidArgs('bid-d1', [line(720)])));
    shieldBlock('bid-b1');
    advance(16_000);
    closeStage(); // b blocked, a last placed among the clean: c and d advance, round stays open
    expect(h.db.round.id.find('round-1')!.state).toBe('open');
    expect(resultOf('seller-b')).toMatchObject({ status: 'knocked_out', rank: 0, landed: 0, adjustedTotal: 0 });
    expect(resultOf('seller-b').lines).toHaveLength(0);
    expect(resultOf('seller-b').reasons.join(' ')).toContain('Shield');
    expect(resultOf('seller-a')).toMatchObject({ status: 'knocked_out', rank: 0, landed: 0 });
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c2', [line(690)])));
    run(D, (ctx) => m.placeBid(ctx, bidArgs('bid-d2', [line(710)])));
    advance(16_000);
    closeStage();
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    expect(resultOf('seller-b')).toMatchObject({ status: 'knocked_out', rank: 0, landed: 760 }); // never ranked; its landed price shows now
    expect(resultOf('seller-b').lines.map((l) => l.unitPrice)).toEqual([760]);
    expect(resultOf('seller-a')).toMatchObject({ status: 'knocked_out', rank: 3, landed: 790 });
  });
});

describe('#374 sign_up_buyer', () => {
  const signUp = (who: Auth, a: { displayName: string; phone?: string } = { displayName: 'Ana' }) =>
    run(who, (ctx) => m.signUpBuyer(ctx, a)) as string;

  it('creates a b_<8> buyer bound to the caller with a $0 per-buy allowance', () => {
    const who = as('new-1');
    const buyerId = signUp(who, { displayName: '  Ana  ', phone: '+1 415 555 0100' });
    expect(buyerId).toMatch(/^b_[a-z0-9]{8}$/);
    const r = h.db.role.identity.find(idOf(who))!;
    expect({ role: r.role, subjectId: r.subjectId }).toEqual({ role: 'buyer', subjectId: buyerId });
    const p = h.db.buyerProfile.buyerId.find(buyerId)!;
    expect(p.displayName).toBe('Ana');
    expect(p.phone).toBe('+14155550100');
    expect(h.db.allowance.buyerId.find(buyerId)!.perPurchaseLimit).toBe(0);
  });

  it('a deal for the new buyer needs their call', () => {
    const who = as('new-1');
    const buyerId = signUp(who);
    const w = win(780, C, 'seller-c', who, buyerId);
    mint(mandateArgs({ ...w, buyerId, hash: 'hx', id: 'mdt-x', nonce: 'nx' }));
    expect(h.db.mandate.hash.find('hx')!.withinAllowance).toBe(false);
  });

  it('refuses a second sign-up, an existing buyer and the owner', () => {
    const who = as('new-2');
    signUp(who);
    expect(() => signUp(who)).toThrow(/already/);
    expect(() => signUp(VIDYUT)).toThrow(/already/);
    expect(() => signUp(OWNER)).toThrow(/already/);
  });

  it('phone is optional and validated; the name is required and capped', () => {
    const a = signUp(as('new-3'), { displayName: 'Bo' });
    expect(h.db.buyerProfile.buyerId.find(a)!.phone).toBe('');
    for (const bad of ['abc', '4155550100', '+0123456789'])
      expect(() => signUp(as(`bad-${bad}`), { displayName: 'Bo', phone: bad })).toThrow('phone must start with + and a country code, like +14155550100');
    expect(() => signUp(as('new-5'), { displayName: '   ' })).toThrow();
    const b = signUp(as('new-6'), { displayName: 'x'.repeat(100) });
    expect(h.db.buyerProfile.buyerId.find(b)!.displayName).toHaveLength(60);
  });

  it('throttles at 30 per 10 minutes', () => {
    for (let i = 0; i < m.SIGNUP_MAX; i++) signUp(as(`t-${i}`));
    expect(() => signUp(as('t-over'))).toThrow(/try again/);
    advance(10 * 60 * 1000 + 1);
    expect(signUp(as('t-later'))).toMatch(/^b_/);
  });

  it('my_role shows the owner, nothing for a stranger', () => {
    const v = m.myRoleView(h.viewContext(OWNER) as any);
    expect(v).toHaveLength(1);
    expect(v[0]!.role).toBe('owner');
    expect(m.myRoleView(h.viewContext(STRANGER) as any)).toEqual([]);
  });
});

describe('#374 telemetry', () => {
  const AGENT = 'agent1q' + 'a'.repeat(24);
  const telemetry = () => run(STRANGER, (ctx) => m.telemetryView(ctx));
  const fieldNames = (row: any): string[] => {
    const els = row.algebraicType.value.elements ?? [];
    return els.map((e: any) => (typeof e.name === 'string' ? e.name : e.name?.value));
  };

  it('counts the market with one row and no per-user data', () => {
    run(as('tel-1'), (ctx) => m.signUpBuyer(ctx, { displayName: 'Ana' }));
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(760)])));
    advance(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const rows = telemetry();
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ accountsCreated: 1, roundsOpened: 1, roundsClosed: 1, bids: 2, approvals: 0, denials: 0 });
    expect(rows[0]!.roundP50Ms).toBeGreaterThan(0);
    expect(rows[0]!.roundP95Ms).toBeGreaterThanOrEqual(rows[0]!.roundP50Ms);
  });

  it('telemetry_agent counts events per agent, sorted', () => {
    for (const [name, n] of [['zed', 1], ['ada', 2]] as const)
      for (let i = 0; i < n; i++) run(REF, (ctx) => m.recordAgentEvent(ctx, { agentName: name, address: AGENT, text: 't', ts: '', origin: 'SIM' }));
    expect(run(STRANGER, (ctx) => m.telemetryAgentView(ctx))).toEqual([{ agent: 'ada', events: 2 }, { agent: 'zed', events: 1 }]);
  });

  it('row types carry no money, phone or name field', () => {
    for (const row of [TelemetryRow, TelemetryAgentRow]) {
      const names = fieldNames(row);
      expect(names.length).toBeGreaterThan(1);
      for (const n of names) expect(n).not.toMatch(/amount|price|total|cap|spend|limit|payee|phone|name|card|email/i);
    }
  });
});

describe('#374 agent views', () => {
  const views = (who: Auth) => {
    const v = h.viewContext(who) as any;
    return [m.agentBuyerContactView(v), m.agentOpenGoalsView(v), m.agentGoalItemsView(v)];
  };
  let NEW: Auth, buyerId: string;
  beforeEach(() => {
    NEW = as('agent-new');
    buyerId = run(NEW, (ctx) => m.signUpBuyer(ctx, { displayName: 'Ana', phone: '+1 415 555 0100' }));
    run(NEW, (ctx) => m.postGoal(ctx, goalArgs({ buyerId, id: 'goal-n' })));
  });

  it('the referee sees contacts, open goals and their items', () => {
    const [contacts, goals, items] = views(REF);
    expect(contacts).toContainEqual({ buyerId, displayName: 'Ana', phone: '+14155550100' });
    expect(goals.map((g: any) => g.id)).toContain('goal-n');
    expect(items.length).toBeGreaterThan(0);
    expect(items.every((i: any) => goals.some((g: any) => g.id === i.goalId))).toBe(true);
  });

  it('everyone else gets nothing, the owner and the buyer included', () => {
    for (const who of [STRANGER, VIDYUT, NEW, OWNER]) for (const v of views(who)) expect(v).toEqual([]);
  });
});

describe('#374 post_need referee path', () => {
  const NOT_ONLY = /only for one of that buyer/;
  let NEW: Auth, buyerId: string;
  beforeEach(() => {
    NEW = as('need-new');
    buyerId = run(NEW, (ctx) => m.signUpBuyer(ctx, { displayName: 'Ana' }));
    run(NEW, (ctx) => m.postGoal(ctx, goalArgs({ id: 'goal-r', buyerId })));
  });

  it('the referee posts a need for the buyer\'s own goal', () => {
    run(REF, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-r', buyerId, goalId: 'goal-r' })));
    expect(h.db.need.id.find('need-r')?.buyerId).toBe(buyerId);
  });

  it('refuses an unknown goal and another buyer\'s goal', () => {
    expect(() => run(REF, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-r', buyerId, goalId: 'nope' })))).toThrow(NOT_ONLY);
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs({ id: 'goal-v' })));
    expect(() => run(REF, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-r', buyerId, goalId: 'goal-v' })))).toThrow(NOT_ONLY);
  });

  it('another buyer still cannot post for this buyer', () => {
    expect(() => run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ id: 'need-r', buyerId, goalId: 'goal-r' })))).toThrow(/acts only for/);
  });
});
