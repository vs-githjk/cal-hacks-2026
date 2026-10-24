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
const advanceRaw = (ms: number) => h.clock.advance(TimeDuration.fromMillis(ms));
const advance = (ms: number) => { ensureTestMetadata(); advanceRaw(ms); };
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

function setupRound(windowS = 15, allowedConditions: string[] = []) {
  run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ auctionWindowS: windowS,
    items: [{ skuSpec: GPU, condition: 'new', allowedConditions, variant: 'retail', quantity: 1, unit: 'each' }],
  })));
  run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS }));
}

const bidArgs = (id: string, lines: ReturnType<typeof line>[]) => ({
  id, roundId: 'round-1', persona: 'p', lines, statedTotal: 0, perks: [], claims: [], origin: 'SIM', source: 'sim:fixture',
});

function ensureTestMetadata() {
  for (const b of [...h.db.bid.roundId.filter('round-1')]) {
    if ((b.lineMetaJson || '[]') !== '[]') continue;
    if (h.db.round.id.find(b.roundId)?.state !== 'open') continue;
    const seller = b.sellerId === 'seller-a' ? A : b.sellerId === 'seller-b' ? B : C;
    const lineMetaJson = JSON.stringify(b.lines.map((_line: any, lineIndex: number) => ({
      lineIndex, shipping: 0, listingId: `https://example.test/${b.id}/${lineIndex}`,
      listingHash: 'a'.repeat(64), source: 'test-fixture', snapshotId: 'snapshot-test',
      provenance: { origin: 'SIM' }, attrs: {},
    })));
    run(seller, (ctx) => m.setBidLineMeta(ctx, { bidId: b.id, lineMetaJson }));
  }
}

function beginReview() {
  ensureTestMetadata();
  if (h.db.round.id.find('round-1')!.state === 'open') {
    advanceRaw(16_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
  }
}

const candidate = (bidId: string) => m.reviewCandidatesView(h.viewContext(REF) as any).find((row) => row.bidId === bidId)!;

function closeReadyRound() {
  beginReview();
  const candidates = new Map(m.reviewCandidatesView(h.viewContext(REF) as any).map((row) => [row.bidId, row]));
  for (const b of [...h.db.bid.roundId.filter('round-1')]) {
    const checks = [...h.db.bidCheck.bidId.filter(b.id)];
    const current = candidates.get(b.id);
    if (!checks.some((c) => c.kind === 'shield')) run(REF, (ctx) => m.attachVerdict(ctx, { bidId: b.id, verdict: 'allow', ruleIds: [], origin: 'SIM' }));
    if (current && !checks.some((c) => c.kind === 'advocate')) run(REF, (ctx) => m.attachAdvocateCard(ctx, {
      bidId: b.id, recommendation: 'buy', ruleId: '', text: '', sourceUrl: '', origin: 'SIM', bindingHash: current.bindingHash,
    }));
    if (current) for (const claim of b.claims) for (const selected of JSON.parse(current.linesJson)) {
      const exists = checks.some((c) => c.kind === 'claim' && c.detail === claim && c.bindingJson.includes(`"lineIndex":${selected.line_index}`));
      if (!exists) run(REF, (ctx) => m.attachClaimCheck(ctx, {
        bidId: b.id, claim, check: 'verified', evidenceUrl: '', origin: 'SIM', bindingHash: current.bindingHash,
        lineIndex: selected.line_index, listingId: selected.listing_id, listingHash: selected.listing_hash,
      }));
    }
  }
  advance(m.REVIEW_WINDOW_MS);
  run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
}

const mandateArgs = (over: Partial<Parameters<typeof m.createMandate>[1]> = {}) => ({
  hash: 'h1', id: 'mdt-1', dealId: 'round-1:bid-a', buyerId: 'vidyut', amount: 780, payee: 'seller-a', expiryMinutes: 10, nonce: 'n1', requestedBy: '', origin: 'SIM', goalId: '', needId: '', ...over,
});

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

describe('candidate SHA-256 binding', () => {
  it('uses the standard SHA-256 digest for UTF-8 canonical candidate data', () => {
    expect(m.sha256('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    expect(m.sha256('✓')).toBe('1dabba21cdad44541f6b15796f8d22978fc7ea10c46aeceeeeb66c23b3ac7604');
  });
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

describe('migration-safe bid line metadata', () => {
  it('requires seller-owned complete metadata, permits only exact retries, and blocks later changes', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('meta-bid', [line(780), line(760, { offeredCondition: 'open-box' })])));
    const mk = (shipping: number) => JSON.stringify([
      { lineIndex: 0, shipping, listingId: 'https://example.test/new', listingHash: 'a'.repeat(64), source: 'fixture', snapshotId: 'snap', provenance: { origin: 'SIM' }, attrs: {} },
      { lineIndex: 1, shipping: 0, listingId: 'https://example.test/open', listingHash: 'b'.repeat(64), source: 'fixture', snapshotId: 'snap', provenance: { origin: 'SIM' }, attrs: {} },
    ]);
    expect(() => run(B, (ctx) => m.setBidLineMeta(ctx, { bidId: 'meta-bid', lineMetaJson: mk(1) }))).toThrow(/no bid for this seller/);
    expect(() => run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'meta-bid', lineMetaJson: mk(-1) }))).toThrow(/shipping/);
    const value = mk(2);
    const prettyValue = JSON.stringify(JSON.parse(value), null, 2);
    run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'meta-bid', lineMetaJson: prettyValue }));
    run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'meta-bid', lineMetaJson: prettyValue }));
    expect(() => run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'meta-bid', lineMetaJson: mk(3) }))).toThrow(/immutable/);
    advance(15_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect(() => run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'meta-bid', lineMetaJson: prettyValue }))).not.toThrow();
  });

  it('accepts catalog scalar arrays and canonicalizes reordered metadata objects for retries after cutoff', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('catalog-meta', [line(780)])));
    const original = JSON.stringify([{
      lineIndex: 0, shipping: 12, listingId: 'https://example.test/gpu', listingHash: 'c'.repeat(64),
      source: 'catalog', snapshotId: 'catalog-1', provenance: { origin: 'SIM', source: 'catalog' },
      attrs: { power_connector: ['8pin', 1], chipset: 'RTX', category: 'gpu' },
    }]);
    run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'catalog-meta', lineMetaJson: original }));
    advance(15_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const reordered = JSON.stringify([{
      attrs: { category: 'gpu', chipset: 'RTX', power_connector: ['8pin', 1] },
      provenance: { source: 'catalog', origin: 'SIM' }, snapshotId: 'catalog-1', source: 'catalog',
      listingHash: 'c'.repeat(64), listingId: 'https://example.test/gpu', shipping: 12, lineIndex: 0,
    }]);
    expect(() => run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'catalog-meta', lineMetaJson: reordered }))).not.toThrow();
  });

  it('keeps a partial bid out of authoritative review and settlement when the need has multiple items', () => {
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ items: [
      { skuSpec: GPU, condition: 'new', allowedConditions: [], variant: 'retail', quantity: 1, unit: 'each' },
      { skuSpec: 'cpu-ryzen9', condition: 'new', allowedConditions: [], variant: 'retail', quantity: 1, unit: 'each' },
    ] })));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS: 15 }));
    run(A, (ctx) => m.placeBid(ctx, bidArgs('partial-bid', [line(780)])));
    advance(15_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect(m.reviewCandidatesView(h.viewContext(REF) as any)).toHaveLength(0);
    advance(m.REVIEW_WINDOW_MS);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect([...h.db.roundResult.iter()]).toMatchObject([
      { bidId: 'partial-bid', rank: 0 },
    ]);
    expect([...h.db.roundResult.iter()][0]!.reasons.join(' ')).toMatch(/does not cover (every )?requested item/);
  });

  it('uses the shared picker for the private review candidate and carries original line index and selected metadata', () => {
    setupRound(15, ['new', 'open-box']);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('meta-pick', [line(780), line(760, { offeredCondition: 'open-box' })])));
    const lineMetaJson = JSON.stringify([
      { lineIndex: 0, shipping: 30, listingId: 'https://example.test/new', listingHash: 'a'.repeat(64), source: 'fixture', snapshotId: 'snap', provenance: { origin: 'SIM' }, attrs: {} },
      { lineIndex: 1, shipping: 0, listingId: 'https://example.test/open', listingHash: 'b'.repeat(64), source: 'fixture', snapshotId: 'snap', provenance: { origin: 'SIM' }, attrs: {} },
    ]);
    run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'meta-pick', lineMetaJson }));
    advance(15_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const candidates = m.reviewCandidatesView(h.viewContext(REF) as any);
    expect(candidates).toHaveLength(1);
    expect(JSON.parse(candidates[0]!.linesJson)).toMatchObject([{ line_index: 1, listing_id: 'https://example.test/open', shipping: 0 }]);
    expect(m.reviewCandidatesView(h.viewContext(VIDYUT) as any)).toHaveLength(0);
  });

  it('binds requested quantity while preserving original stock quantity and one shipping charge', () => {
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs({ items: [
      { skuSpec: GPU, condition: 'new', allowedConditions: [], variant: 'retail', quantity: 2, unit: 'each' },
    ] })));
    run(REF, (ctx) => m.openRound(ctx, { roundId: 'round-1', needId: 'need-1', windowS: 15 }));
    run(A, (ctx) => m.setFloorForCondition(ctx, { skuSpec: GPU, condition: 'new', floor: 1 }));
    run(A, (ctx) => m.placeBid(ctx, bidArgs('quantity-binding', [line(40, { quantity: 5 })])));
    run(A, (ctx) => m.setBidLineMeta(ctx, { bidId: 'quantity-binding', lineMetaJson: JSON.stringify([{
      lineIndex: 0, shipping: 12, listingId: 'https://example.test/gpu', listingHash: 'd'.repeat(64),
      source: 'fixture', snapshotId: 'snapshot-1', provenance: { origin: 'SIM' }, attrs: {},
    }]) }));
    advance(15_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    const selected = candidate('quantity-binding');
    expect(selected.landed).toBe(92);
    expect(JSON.parse(selected.linesJson)[0]).toMatchObject({ quantity: 5, sku_spec: GPU, unit_price: 40, shipping: 12 });
    expect(selected.bindingHash).toBe(m.sha256(JSON.stringify({
      roundId: selected.roundId, needId: selected.needId, bidId: selected.bidId, sellerId: selected.sellerId,
      origin: 'SIM', landed: 92,
      needItems: [{ sku_spec: GPU, condition: 'new', allowed_conditions: [], variant: 'retail', quantity: 2, unit: 'each' }],
      lines: JSON.parse(selected.linesJson), lineMetaJson: selected.lineMetaJson,
    })));
  });

  it('hashes the exact selected slice and refuses a card bound to another candidate', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bound-card', [line(780)])));
    beginReview();
    const selected = candidate('bound-card');
    const expected = m.sha256(JSON.stringify({
      roundId: selected.roundId, needId: selected.needId, bidId: selected.bidId, sellerId: selected.sellerId,
      origin: 'SIM', landed: selected.landed,
      needItems: [{ sku_spec: GPU, condition: 'new', allowed_conditions: [], variant: 'retail', quantity: 1, unit: 'each' }],
      lines: JSON.parse(selected.linesJson), lineMetaJson: selected.lineMetaJson,
    }));
    expect(selected.bindingHash).toBe(expected);
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bound-card', verdict: 'allow', ruleIds: [], origin: 'SIM' }));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bound-card', recommendation: 'buy', ruleId: '', text: '', sourceUrl: '', origin: 'SIM', bindingHash: '0'.repeat(64) }));
    advance(m.REVIEW_WINDOW_MS);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect([...h.db.roundResult.iter()][0]).toMatchObject({ rank: 0 });
    expect([...h.db.roundResult.iter()][0]!.bindingHash).toBe(selected.bindingHash);
    expect([...h.db.roundResult.iter()][0]!.reasons.join(' ')).toMatch(/AdvocateCard bound to the selected candidate/);
  });

  it('requires claim evidence to identify the original line, exact listing, and candidate hash', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, { ...bidArgs('bound-claim', [line(780)]), claims: ['warranty'] }));
    beginReview();
    const selected = candidate('bound-claim');
    const lineEvidence = JSON.parse(selected.linesJson)[0]!;
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bound-claim', verdict: 'allow', ruleIds: [], origin: 'SIM' }));
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bound-claim', recommendation: 'buy', ruleId: '', text: '', sourceUrl: '', origin: 'SIM', bindingHash: selected.bindingHash }));
    const evidence = { bidId: 'bound-claim', claim: 'warranty', check: 'verified', evidenceUrl: 'https://example.test/warranty', origin: 'SIM',
      bindingHash: selected.bindingHash, lineIndex: lineEvidence.line_index, listingId: lineEvidence.listing_id, listingHash: lineEvidence.listing_hash };
    expect(() => run(REF, (ctx) => m.attachClaimCheck(ctx, { ...evidence, lineIndex: 1 }))).toThrow(/original listing and line index/);
    expect(() => run(REF, (ctx) => m.attachClaimCheck(ctx, { ...evidence, listingHash: 'b'.repeat(64) }))).toThrow(/original listing and line index/);
    run(REF, (ctx) => m.attachClaimCheck(ctx, evidence));
    advance(m.REVIEW_WINDOW_MS);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect([...h.db.roundResult.iter()][0]!.rank).toBe(1);
  });

  it('refuses to rank or finalize a bid with missing line metadata', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('missing-meta', [line(780)])));
    advanceRaw(15_000);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'missing-meta', verdict: 'allow', ruleIds: [], origin: 'SIM' }));
    advance(m.REVIEW_WINDOW_MS);
    run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }));
    expect([...h.db.roundResult.roundId.filter('round-1')][0]).toMatchObject({ rank: 0 });
    expect([...h.db.roundResult.roundId.filter('round-1')][0]!.reasons.join(' ')).toMatch(/line metadata/);
  });
});

describe('goal reservation and settlement', () => {
  it('reserves one current deal, records spend only on payment, and marks DONE only after the exact buyer settlement ack', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ dealId: 'deal-1', goalId: 'goal-1', needId: 'need-1' })));
    expect(h.db.goal.id.find('goal-1')).toMatchObject({ state: 'HOLD_FOR_CALL', reservedAmount: 780 });
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_deal_1', amount: 780, mode: 'stripe_test' }));
    expect(h.db.goal.id.find('goal-1')).toMatchObject({ state: 'HOLD_FOR_CALL', reservedAmount: 780 });
    expect(() => run(VIDYUT, (ctx) => m.settleGoal(ctx, { goalId: 'goal-1', dealId: 'deal-1', mandateHash: 'h1', paymentRef: 'pi_wrong' }))).toThrow(/exact recorded payment/);
    run(VIDYUT, (ctx) => m.settleGoal(ctx, { goalId: 'goal-1', dealId: 'deal-1', mandateHash: 'h1', paymentRef: 'pi_deal_1' }));
    expect(h.db.goal.id.find('goal-1')).toMatchObject({ state: 'DONE', reservedAmount: 0, poNumber: 'deal-1' });
    run(VIDYUT, (ctx) => m.settleGoal(ctx, { goalId: 'goal-1', dealId: 'deal-1', mandateHash: 'h1', paymentRef: 'pi_deal_1' }));
  });

  it('binds one hold to the exact deal and mandate and releases only an expired unapproved mandate', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ goalId: 'goal-1', needId: 'need-1', dealId: 'deal-1' })));
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h2', id: 'mdt-2', goalId: 'goal-1', needId: 'need-1', dealId: 'deal-2' })))).toThrow(/active deal reservation/);
    run(REF, (ctx) => m.reserveGoal(ctx, { goalId: 'goal-1', dealId: 'deal-1', mandateHash: 'h1', amount: 780 }));
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }));
    advance(10 * 60_000 + 1);
    expect(() => run(REF, (ctx) => m.releaseGoalReservation(ctx, { goalId: 'goal-1', dealId: 'deal-1', mandateHash: 'h1' }))).toThrow(/approved or charged/);
    expect(h.db.goal.id.find('goal-1')).toMatchObject({ reservedDealId: 'deal-1', reservedMandateHash: 'h1', reservedAmount: 780 });
  });

  it('releases an approved deal only on exact referee no-charge retirement proof and blocks stale callbacks', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ goalId: 'goal-1', needId: 'need-1', dealId: 'deal-retire' })));
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }));
    const attemptId = `req:${'a'.repeat(64)}`;
    expect(() => run(VIDYUT, (ctx) => m.resolveNoCharge(ctx, { dealId: 'deal-retire', mandateHash: 'h1', attemptId }))).toThrow(/not allowed/);
    expect(() => run(REF, (ctx) => m.resolveNoCharge(ctx, { dealId: 'other-deal', mandateHash: 'h1', attemptId }))).toThrow(/matching goal mandate/);
    expect(() => run(REF, (ctx) => m.resolveNoCharge(ctx, { dealId: 'deal-retire', mandateHash: 'h1', attemptId: 'refused' }))).toThrow(/request hash/);
    run(REF, (ctx) => m.resolveNoCharge(ctx, { dealId: 'deal-retire', mandateHash: 'h1', attemptId }));
    run(REF, (ctx) => m.resolveNoCharge(ctx, { dealId: 'deal-retire', mandateHash: 'h1', attemptId }));
    expect(h.db.goal.id.find('goal-1')).toMatchObject({ state: 'HUNTING', reservedAmount: 0, reservedDealId: '', reservedMandateHash: '' });
    expect(h.db.mandate.hash.find('h1')).toMatchObject({ retired: true, retirementAttemptId: attemptId });
    expect(() => run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }))).toThrow(/retired/);
    expect(() => run(REF, (ctx) => m.issueApprovalCode(ctx, { mandateHash: 'h1', code: 'apple river' }))).toThrow(/retired/);
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_late', amount: 780, mode: 'stripe_test' }))).toThrow(/retired/);
    expect(() => run(REF, (ctx) => m.resolveNoCharge(ctx, { dealId: 'deal-retire', mandateHash: 'h1', attemptId: `req:${'b'.repeat(64)}` }))).toThrow(/different request/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h2', id: 'm2', goalId: 'goal-1', needId: 'need-1', dealId: 'deal-next' })))).not.toThrow();
  });

  it('releases the exact expired unapproved hold and rejects non-finite goal or mandate values', () => {
    expect(() => run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs({ cap: Infinity })))).toThrow(/finite positive/);
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: Infinity })))).toThrow(/finite and positive/);
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ expiryMinutes: 11 })))).toThrow(/between 1 and 10/);
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ goalId: 'goal-1', needId: 'need-1', dealId: 'deal-1' })));
    advance(10 * 60_000 + 1);
    run(REF, (ctx) => m.releaseGoalReservation(ctx, { goalId: 'goal-1', dealId: 'deal-1', mandateHash: 'h1' }));
    expect(h.db.goal.id.find('goal-1')).toMatchObject({ state: 'HUNTING', reservedAmount: 0, reservedDealId: '', reservedMandateHash: '' });
  });

  it('does not let a late charge from an expired deal consume a newer same-amount reservation', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ goalId: 'goal-1', needId: 'need-1', dealId: 'deal-old' })));
    advance(10 * 60_000 + 1);
    run(REF, (ctx) => m.releaseGoalReservation(ctx, { goalId: 'goal-1', dealId: 'deal-old', mandateHash: 'h1' }));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({
      hash: 'h2', id: 'mdt-2', nonce: 'n2', dealId: 'deal-new', goalId: 'goal-1', needId: 'need-1',
    })));
    run(REF, (ctx) => ctx.db.approval.insert({ id: 0n, mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut', at: ctx.timestamp }));
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_late', amount: 780, mode: 'stripe_test' })))
      .toThrow(/active goal reservation/);
    expect(h.db.payment.mandateHash.find('h1')).toBeFalsy();
  });

  it('does not let a one-item Need mark a multi-item parent goal done', () => {
    const psu = 'psu-850w-gold';
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs({ items: [
      { skuSpec: GPU, condition: 'new', variant: 'retail', quantity: 1, skippedOwnedPartId: '' },
      { skuSpec: psu, condition: 'new', variant: 'retail', quantity: 1, skippedOwnedPartId: '' },
    ] })));
    run(VIDYUT, (ctx) => m.postNeed(ctx, needArgs()));
    expect(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ goalId: 'goal-1', needId: 'need-1' })))).toThrow(/complete goal/);
    expect(h.db.goal.id.find('goal-1')!.reservedAmount).toBe(0);
  });

  it('makes step events buyer-private and stable-ID idempotent', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    const args = { stableId: 'goal-1:deal-found:1', goalId: 'goal-1', klass: 'deal found', text: 'Candidate found.', origin: 'SIM' };
    run(VIDYUT, (ctx) => m.recordStepEvent(ctx, args));
    run(VIDYUT, (ctx) => m.recordStepEvent(ctx, args));
    expect(m.myGoalStepEventsView(h.viewContext(VIDYUT) as any)).toHaveLength(1);
    expect(m.myGoalStepEventsView(h.viewContext(BOB) as any)).toHaveLength(0);
    expect(() => run(BOB, (ctx) => m.recordStepEvent(ctx, args))).toThrow(/no goal for this buyer/);
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
    closeReadyRound();
    expect([...h.db.roundResult.iter()][0]).toMatchObject({ rank: 1, landed: 780 });
  });

  it('a bid with the need quantity is accepted and ranks', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780, { quantity: 1 })])));
    advance(16_000);
    closeReadyRound();
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
    closeReadyRound();
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
    beginReview();
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-c', verdict: 'quarantine', ruleIds: ['payee_swap'], origin: 'SIM' }));
    expect(() => run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }))).toThrow(/still open/);
    advance(16_000);
    closeReadyRound();
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
    expect(h.db.round.id.find('round-1')!.state).toBe('review');
    advance(m.REVIEW_WINDOW_MS);
    run(TestAuth.internal(), (ctx) => m.closeRoundOnDeadline(ctx, 'round-1'));
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
  });
});

describe('two-phase bid and review lifecycle', () => {
  it('freezes bids at cutoff, refuses early finalization, and cannot rank a bid with missing independent review', () => {
    setupRound(1);
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));

    advance(16_000);
    run(TestAuth.internal(), (ctx) => m.closeRoundOnDeadline(ctx, 'round-1'));
    expect(h.db.round.id.find('round-1')!.state).toBe('review');
    expect(() => run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-late', [line(700)])))).toThrow(/closed|review/);
    expect(h.db.bid.id.find('bid-late')).toBeFalsy();
    expect(() => run(REF, (ctx) => m.closeRound(ctx, { roundId: 'round-1' }))).toThrow(/review|deadline/);

    advance(21_000);
    run(TestAuth.internal(), (ctx) => m.closeRoundOnDeadline(ctx, 'round-1'));
    expect(h.db.round.id.find('round-1')!.state).toBe('closed');
    expect([...h.db.roundResult.iter()].find((r) => r.bidId === 'bid-a')!.rank).toBe(0);
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
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780, mode: 'sim' }))).toThrow(/no approval/);
    expect([...h.db.payment.iter()]).toHaveLength(0);
  });

  it('INVARIANT-1: an approval for a different hash does not unlock this one', () => {
    mk();
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h2', id: 'mdt-2', dealId: 'd2', amount: 10, payee: 'seller-b', nonce: 'n2' })));
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h2', method: 'typed_code', approvedBy: 'vidyut' }));
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' }))).toThrow(/no approval/);
  });

  it('INVARIANT-1: with an approval, one payment is recorded; the amount must equal the mandate', () => {
    mk();
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut' }));
    expect(() => run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 781, mode: 'sim' }))).toThrow(/amount/);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_test_1', amount: 780, mode: 'sim' }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
  });

  it('INVARIANT-1: a second approval for the same hash is rejected and shown; a second payment too', () => {
    mk();
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut' }));
    run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }));
    expect([...h.db.approval.iter()]).toHaveLength(1);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_1', amount: 780, mode: 'sim' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi_2', amount: 780, mode: 'sim' }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
    expect([...h.db.rejectedAttempt.iter()].map((r) => r.kind)).toEqual(['approval', 'payment']);
  });

  it('INVARIANT-1: an expired mandate cannot be approved', () => {
    mk();
    advance(11 * 60_000);
    expect(() => run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }))).toThrow(/expired/);
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
    ['attach_claim_check', (ctx) => m.attachClaimCheck(ctx, { bidId: 'bid-b', claim: 'new', check: 'false', evidenceUrl: '', origin: 'SIM', bindingHash: '', lineIndex: 0, listingId: '', listingHash: '' })],
    ['create_mandate', (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'h9' }))],
    ['record_approval', (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' })],
    ['record_payment', (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' })],
    ['attach_advocate_card', (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b', recommendation: 'veto', ruleId: 'fit.gpu_length', text: 'x', sourceUrl: 'https://x', origin: 'SIM', bindingHash: '' })],
    ['assign_role', (ctx) => m.assignRole(ctx, { identity: ctx.sender, role: 'referee', subjectId: 'market' })],
    ['reset_demo', (ctx) => m.resetDemoChecked(ctx)],
    ['seed_demo', (ctx) => m.seedDemoChecked(ctx)],
  ];

  it.each(sellerCalls)('SECURITY: a seller calling %s is refused', (_name, call) => {
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(760)])));
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }));
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
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ payee: 'seller-a' })));
    expect(() => run(A, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }))).toThrow(/not allowed/);
    expect(() => run(A, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'seller-a' }))).toThrow(/not allowed/);
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }));
    expect(() => run(A, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' }))).toThrow(/not allowed/);
    expect([...h.db.payment.iter()]).toHaveLength(0);
  });

  it("SECURITY: seller A cannot attach a verdict or claim check against seller B's bid", () => {
    setupRound();
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(760)])));
    expect(() => run(A, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-b', verdict: 'block', ruleIds: ['x'], origin: 'SIM' }))).toThrow(/not allowed/);
    expect(() => run(A, (ctx) => m.attachClaimCheck(ctx, { bidId: 'bid-b', claim: 'new', check: 'false', evidenceUrl: '', origin: 'SIM', bindingHash: '', lineIndex: 0, listingId: '', listingHash: '' }))).toThrow(/not allowed/);
    expect([...h.db.bidCheck.iter()]).toHaveLength(0);
  });

  it('SECURITY: approvedBy must equal the mandate buyer, even when the referee relays it', () => {
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(() => run(REF, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'mallory' }))).toThrow(/approvedBy/);
    expect(() => run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'bob' }))).toThrow(/approvedBy/);
    expect([...h.db.approval.iter()]).toHaveLength(0);
  });

  it("SECURITY: another buyer cannot approve or create a mandate for Vidyut's deal", () => {
    expect(() => run(BOB, (ctx) => m.createMandate(ctx, mandateArgs()))).toThrow(/not allowed/);
    run(VIDYUT, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(() => run(BOB, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }))).toThrow(/not allowed/);
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
    beginReview();
    run(REF, (ctx) => m.attachVerdict(ctx, { bidId: 'bid-a', verdict: 'allow', ruleIds: [], origin: 'SIM' }));
    advance(16_000);
    closeReadyRound();
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' }));
    expect(events().slice(n0).map((e) => e.kind)).toEqual([
      'bid_sealed', 'review_opened', 'verdict', 'advocate_card', 'auction_closed', 'mandate_created', 'approval_recorded', 'payment_recorded',
    ]);
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
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash, id: `m-${hash}`, amount, nonce: hash })));
    if (!h.db.approval.mandateHash.find(hash)) run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: hash, method: 'typed_code', approvedBy: 'vidyut' }));
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: hash, paymentRef: `pi_${hash}`, amount, mode: 'sim' }));
  };
  let n = 0;
  const receive = (who: Auth, hash: string, result = 'accepted') =>
    run(who, (ctx) => m.recordReceiving(ctx, { id: `rcv-${hash}-${result}-${++n}`, orderId: hash, skuSpec: GPU, photoUrl: 'sim://photo', expectedSpecId: 'spec-gpu', result, reasons: result === 'accepted' ? [] : ['box shows open-box seal'], checkedBy: 'owner', origin: 'SIM' }));

  it('a buyer starts at step 0 with $0 limits, so the first buy needs the call (no auto approval)', () => {
    run(VIDYUT, (ctx) => m.postGoal(ctx, goalArgs()));
    expect(allowance()).toMatchObject({ ladderStep: 0, perPurchaseLimit: 0, periodLimit: 0, currency: 'USD', period: 'week' });
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ amount: 5 })));
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
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    expect(() => receive(VIDYUT, 'h1')).toThrow(/not paid/);
  });

  it('inside the allowance a buy auto-approves with a receipt and counts against the period; above it, it calls', () => {
    paidDeal('d1', 20);
    receive(VIDYUT, 'd1');
    const per = allowance()!.perPurchaseLimit;
    expect(allowance()!.spentThisPeriod).toBe(20);
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'small', id: 'm-small', amount: per, nonce: 's' })));
    expect(h.db.mandate.hash.find('small')!.withinAllowance).toBe(true);
    expect(h.db.approval.mandateHash.find('small')!.method).toBe('allowance');
    expect(allowance()!.spentThisPeriod).toBe(20);
    expect([...h.db.notification.buyerId.filter('vidyut')].some((n) => n.text.includes('within your allowance'))).toBe(true);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'small', paymentRef: 'pi_small', amount: per, mode: 'sim' }));
    expect(allowance()!.spentThisPeriod).toBe(20 + per);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'small', paymentRef: 'pi_replay', amount: per, mode: 'sim' }));
    expect(allowance()!.spentThisPeriod).toBe(20 + per);
    expect(events().some((e) => e.kind === 'payment_rejected' && e.refId === 'small')).toBe(true);
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ hash: 'big', id: 'm-big', amount: per + 1, nonce: 'b' })));
    expect(h.db.mandate.hash.find('big')!.withinAllowance).toBe(false);
    expect(h.db.approval.mandateHash.find('big')).toBeFalsy();
  });

  it('the requester can never approve their own purchase', () => {
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs({ requestedBy: 'vidyut' })));
    expect(() => run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'typed_code', approvedBy: 'vidyut' }))).toThrow(/requester/);
    expect(h.db.approval.mandateHash.find('h1')).toBeFalsy();
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
    closeReadyRound();
    return [...h.db.roundResult.iter()];
  };

  it('a veto takes the cheapest bid out of the result with the cited reason, and the next bid ranks first', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(700)])));
    beginReview();
    const selected = candidate('bid-b');
    run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-b', ...veto, bindingHash: selected.bindingHash }));
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
    beginReview();
    const selected = candidate('bid-a');
    expect(selected.bindingHash).toMatch(/^[a-f0-9]{64}$/);
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { ...veto, bidId: 'bid-a', recommendation: 'caution', ruleId: 'advocate.fit_unknown', bindingHash: selected.bindingHash }))).not.toThrow();
    const res = closeIt();
    expect(res[0]!.rank).toBe(1);
    expect([...h.db.bidCheck.iter()].filter((c) => c.kind === 'advocate').map((c) => [c.kind, c.result])).toEqual([['advocate', 'caution']]);
  });

  it('writes a floor event without the seller or the text, and a veto line on the buyer feed', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    beginReview();
    const n0 = events().length;
    const selected = candidate('bid-a');
    expect(selected.bindingHash).toMatch(/^[a-f0-9]{64}$/);
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto, bindingHash: selected.bindingHash }))).not.toThrow();
    const e = events().slice(n0);
    expect(e.map((x) => x.kind)).toEqual(['advocate_card']);
    expect(e[0]!.label).toMatch(/veto/);
    expect(e[0]!.sellerId).toBe('');
    const feed = m.myNotificationsView(h.viewContext(VIDYUT) as any);
    const v = feed.filter((n: any) => n.klass === 'veto');
    expect(v).toHaveLength(1);
    expect(v[0]!.text).toContain('The card is longer than your case allows');
    expect(v[0]!.text).toContain('https://example.com/spec');
    expect(m.myNotificationsView(h.viewContext(BOB) as any).filter((n: any) => n.klass === 'veto')).toHaveLength(0);
  });

  it('a veto must cite a source, the recommendation must be known, and the bid must exist', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    beginReview();
    const bindingHash = candidate('bid-a').bindingHash;
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto, sourceUrl: '', bindingHash }))).toThrow(/source/);
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto, recommendation: 'maybe', bindingHash }))).toThrow(/recommendation/);
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'nope', ...veto, bindingHash }))).toThrow(/no bid/);
    expect([...h.db.bidCheck.iter()]).toHaveLength(0);
  });

  it('refuses a card for a round that has already closed', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    closeIt();
    expect(() => run(REF, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto, bindingHash: '' }))).toThrow(/closed/);
  });

  it('SECURITY: a buyer cannot attach a card either', () => {
    setupRound();
    run(A, (ctx) => m.placeBid(ctx, bidArgs('bid-a', [line(780)])));
    expect(() => run(VIDYUT, (ctx) => m.attachAdvocateCard(ctx, { bidId: 'bid-a', ...veto, bindingHash: '' }))).toThrow(/not allowed/);
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
    closeReadyRound();
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
    closeReadyRound();
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
});

describe('record_payment mode (sim or stripe_test)', () => {
  const ready = () => {
    run(REF, (ctx) => m.createMandate(ctx, mandateArgs()));
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut' }));
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
    closeReadyRound();
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
    closeReadyRound();
    expect([...h.db.roundResult.iter()][0]!.rank).toBe(0);
  });

  it('a line with no floor set for its condition is skipped with the reason; another line can still win', () => {
    setupRound();
    run(C, (ctx) => m.placeBid(ctx, bidArgs('bid-c', [line(200, { offeredCondition: 'refurbished' }), line(720)])));
    run(B, (ctx) => m.placeBid(ctx, bidArgs('bid-b', [line(650, { offeredCondition: 'refurbished' })])));
    advance(16_000);
    closeReadyRound();
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

  it('5 wrong attempts lock the code; the caller sees its own failure count', () => {
    const first = as('first-screen');
    tryPair(first, wrong());
    expect(m.myPairAttemptsView(h.viewContext(first) as any)[0]!.failures).toBe(1);
    for (let i = 0; i < 4; i++) expect(tryPair(as(`screen-${i}`), wrong())).toMatchObject({ paired: false });
    expect(h.db.pairCode.buyerId.find('vidyut')!.locked).toBe(true);
  });

  it('the correct code after the lock still fails', () => {
    for (let i = 0; i < 5; i++) tryPair(as(`screen-${i}`), wrong());
    const late = as('late-screen');
    expect(() => tryPair(late, code)).toThrow(/locked/);
    expect(m.myRoleView(h.viewContext(late) as any)).toHaveLength(0);
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
    for (let i = 0; i < 5; i++) tryPair(as(`screen-${i}`), wrong());
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
    for (let i = 0; i < 5; i++) tryPair(as(`screen-${i}`), wrong());
    let msg = '';
    try { tryPair(as('x'), code); } catch (e) { msg = String(e); }
    expect(msg).not.toContain(code);
    const text = JSON.stringify([...h.db.floorEvent.iter()].map((e) => e.label)) + JSON.stringify([...h.db.notification.iter()].map((n) => n.text));
    expect(text).not.toContain(code);
  });
});

describe('b5 approval code on the buyer screen, typed fallback bound to the same mandate', () => {
  const CODE = 'velvet falcon';
  const issue = (code = CODE) => run(REF, (ctx) => m.issueApprovalCode(ctx, { mandateHash: 'h1', code }));
  const typed = (who: Auth, code: string) => run(who, (ctx) => m.approveTyped(ctx, { mandateHash: 'h1', code }));
  beforeEach(() => run(REF, (ctx) => m.createMandate(ctx, mandateArgs())));

  it('only the referee issues the code; only the mandate buyer sees it, with amount, payee and expiry', () => {
    for (const who of [VIDYUT, A, STRANGER]) expect(() => run(who, (ctx) => m.issueApprovalCode(ctx, { mandateHash: 'h1', code: CODE }))).toThrow(/not allowed/);
    issue();
    const mine = m.myPendingApprovalsView(h.viewContext(VIDYUT) as any);
    expect(mine).toHaveLength(1);
    expect(mine[0]).toMatchObject({ mandateHash: 'h1', mandateId: 'mdt-1', amount: 780, payee: 'seller-a', code: CODE, origin: 'SIM' });
    expect(mine[0].codeExpiresAt.microsSinceUnixEpoch).toBe(mine[0].issuedAt.microsSinceUnixEpoch + 300_000_000n);
    for (const who of [BOB, A, STRANGER]) expect(m.myPendingApprovalsView(h.viewContext(who) as any)).toHaveLength(0);
  });

  it('an approved mandate never gets a code (nothing to approve)', () => {
    run(VIDYUT, (ctx) => m.recordApproval(ctx, { mandateHash: 'h1', method: 'voice_code', approvedBy: 'vidyut' }));
    expect(() => issue()).toThrow(/already approved/);
  });

  it('the typed code approves the same mandate the call would (method typed_code), case and spacing ignored', () => {
    issue();
    expect(typed(VIDYUT, '  Velvet   FALCON ')).toMatchObject({ approved: true });
    expect(h.db.approval.mandateHash.find('h1')).toMatchObject({ method: 'typed_code', approvedBy: 'vidyut' });
    expect(m.myPendingApprovalsView(h.viewContext(VIDYUT) as any)).toHaveLength(0);
    run(REF, (ctx) => m.recordPayment(ctx, { mandateHash: 'h1', paymentRef: 'pi', amount: 780, mode: 'sim' }));
    expect([...h.db.payment.iter()]).toHaveLength(1);
  });

  it('a wrong typed code is counted, never echoed, and 5 lock the code', () => {
    issue();
    expect(typed(VIDYUT, 'copper marble')).toMatchObject({ approved: false });
    expect(m.myPendingApprovalsView(h.viewContext(VIDYUT) as any)[0]).toMatchObject({ failures: 1, locked: false });
    for (let i = 0; i < 4; i++) typed(VIDYUT, 'copper marble');
    expect(() => typed(VIDYUT, CODE)).toThrow(/locked/);
    expect(h.db.approval.mandateHash.find('h1')).toBeFalsy();
    const text = JSON.stringify([...h.db.floorEvent.iter()].map((e) => e.label)) + JSON.stringify([...h.db.notification.iter()].map((n) => n.text));
    expect(text).not.toContain('velvet');
  });

  it('another buyer, a seller or the referee cannot type the code for this mandate; no code issued means no typed approval', () => {
    for (const who of [BOB, A, REF]) expect(() => typed(who, CODE)).toThrow(/not allowed/);
    expect(() => typed(VIDYUT, CODE)).toThrow(/no code issued/);
  });

  it('hides and rejects a typed approval at the shared 300-second voice-code TTL', () => {
    expect(m.APPROVAL_CODE_TTL_MS).toBe(300_000); // parity with pay.approval.CALL_CODE_TTL_S=300
    issue();
    advance(300_000);
    expect(m.myPendingApprovalsView(h.viewContext(VIDYUT) as any)[0].codeExpiresAt.microsSinceUnixEpoch)
      .toBeLessThanOrEqual(h.clock.now().microsSinceUnixEpoch);
    expect(() => typed(VIDYUT, CODE)).toThrow(/approval code expired/);
    expect(h.db.approval.mandateHash.find('h1')).toBeFalsy();
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
