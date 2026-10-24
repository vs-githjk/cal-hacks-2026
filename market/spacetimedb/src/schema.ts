// Tech Bazaar market tables. Private by default: anything a seller must not see (spend limit,
// goal text, cap, allowance, other sellers' bids before close) lives in a private table and
// reaches clients only through the views in index.ts.
import { schema, table, t } from 'spacetimedb/server';

export const BidLine = t.object('BidLine', {
  skuSpec: t.string(),
  offeredSpec: t.string(), // empty means the same as skuSpec
  offeredCondition: t.string(), // empty means the condition the need asked for
  unitPrice: t.f64(),
  quantity: t.f64(),
});

export const NeedItemArg = t.object('NeedItemArg', {
  skuSpec: t.string(),
  condition: t.string(),
  allowedConditions: t.array(t.string()), // empty means only `condition`
  variant: t.string(),
  quantity: t.f64(),
  unit: t.string(),
});

/** Lane A's Goal.items[] (contracts/Goal.schema.json). */
export const GoalItemArg = t.object('GoalItemArg', {
  skuSpec: t.string(),
  condition: t.string(),
  variant: t.string(),
  quantity: t.f64(),
  skippedOwnedPartId: t.string(),
});

// ---- private: buyer side ----
export const need = table(
  { name: 'need' },
  {
    id: t.string().primaryKey(),
    buyerId: t.string().index('btree'),
    goalId: t.string(),
    deliveryWindow: t.string(),
    spendLimit: t.f64(),
    consent: t.bool(),
    auctionWindowS: t.u32(),
    origin: t.string(),
    createdAt: t.timestamp(),
  },
);

export const needItem = table(
  { name: 'need_item' },
  {
    id: t.u64().primaryKey().autoInc(),
    needId: t.string().index('btree'),
    skuSpec: t.string(),
    condition: t.string(),
    variant: t.string(),
    quantity: t.f64(),
    unit: t.string(),
    allowedConditions: t.array(t.string()).default([]), // appended last so a publish migrates in place
  },
);

export const goal = table(
  { name: 'goal' },
  {
    id: t.string().primaryKey(),
    buyerId: t.string().index('btree'),
    type: t.string(),
    cap: t.f64(),
    deadline: t.timestamp(),
    state: t.string(),
    reservedAmount: t.f64(),
    reservedDealId: t.string().default(''),
    reservedMandateHash: t.string().default(''),
    poNumber: t.string(),
    origin: t.string(), // market-internal, for the badge; not in the Goal contract
    createdAt: t.timestamp(),
  },
);

export const goalItem = table(
  { name: 'goal_item' },
  {
    id: t.u64().primaryKey().autoInc(),
    goalId: t.string().index('btree'),
    skuSpec: t.string(),
    condition: t.string(),
    variant: t.string(),
    quantity: t.f64(),
    skippedOwnedPartId: t.string(),
  },
);

export const notification = table(
  { name: 'notification' },
  {
    id: t.u64().primaryKey().autoInc(),
    buyerId: t.string().index('btree'),
    goalId: t.string(),
    klass: t.string(), // deal_found | bid_in | veto | progress | state
    text: t.string(),
    push: t.bool(),
    at: t.timestamp(),
  },
);

/** Private buyer progress events; stableId makes caller retries idempotent. */
export const goalStepEvent = table(
  { name: 'goal_step_event' },
  {
    stableId: t.string().primaryKey(),
    buyerId: t.string().index('btree'),
    goalId: t.string(),
    klass: t.string(),
    text: t.string(),
    origin: t.string(),
    at: t.timestamp(),
  },
);

// ---- private: who may do what ----
/** The identity that published the module; only it assigns roles. Set once in init. */
export const owner = table({ name: 'owner' }, { id: t.u32().primaryKey(), identity: t.identity() });

/** One role per identity: buyer (subject = buyer_id), seller (subject = seller_id) or referee. */
export const role = table(
  { name: 'role' },
  { identity: t.identity().primaryKey(), role: t.string(), subjectId: t.string().index('btree') },
);

/** Demo pairing code per buyer, so a browser screen can take the buyer role (SIM sign-in). */
export const pairCode = table(
  { name: 'pair_code' },
  {
    buyerId: t.string().primaryKey(),
    code: t.string(),
    failedAttempts: t.u32().default(0), // appended last so a publish migrates in place
    locked: t.bool().default(false),
  },
);

/** The one-time word-pair code Lane D's approval service issued for a mandate that needs the buyer's call. Private: only the mandate's buyer sees it (my_pending_approvals). */
export const approvalCode = table(
  { name: 'approval_code' },
  { mandateHash: t.string().primaryKey(), buyerId: t.string().index('btree'), code: t.string(), failures: t.u32(), locked: t.bool(), issuedAt: t.timestamp() },
);

/** LossReport contract, plus the seller's strategy diff and Claude's one line. Private: each seller sees only its own (my_loss_reports). */
export const StrategyStep = t.object('StrategyStep', { key: t.string(), from: t.string(), to: t.string() });
export const lossReport = table(
  { name: 'loss_report' },
  {
    id: t.string().primaryKey(),
    roundId: t.string(),
    sellerId: t.string().index('btree'),
    won: t.bool(),
    gapBand: t.string(), // within5 | within10 | within20 | over20
    reason: t.string(), // price | fit | condition | delivery | record | advocate_veto
    sourceUrl: t.string(),
    strategyDiff: t.array(StrategyStep),
    whatToChange: t.string(),
    whatToChangeOrigin: t.string(),
    origin: t.string(),
    createdAt: t.timestamp(),
  },
);

/** The buyer's display name for screens (#37 item 9). Private: only that buyer sees it (my_buyer_profile). */
export const buyerProfile = table({ name: 'buyer_profile' }, { buyerId: t.string().primaryKey(), displayName: t.string(), origin: t.string() });

/** Failed pairing attempts per caller, across every code. */
export const pairAttempt = table({ name: 'pair_attempt' }, { identity: t.identity().primaryKey(), failures: t.u32() });

// ---- private: seller side ----

export const sellerFloor = table(
  { name: 'seller_floor' },
  {
    id: t.u64().primaryKey().autoInc(),
    sellerId: t.string().index('btree'),
    skuSpec: t.string(),
    floor: t.f64(),
    condition: t.string().default('*'), // per (seller, sku, condition); '*' means any condition; appended last
  },
);

/** Sealed until the round closes. Only the bidder sees it before then (my_bids view). */
export const bid = table(
  { name: 'bid' },
  {
    id: t.string().primaryKey(),
    roundId: t.string().index('btree'),
    needId: t.string(),
    sellerId: t.string(),
    bidder: t.identity(),
    persona: t.string(),
    lines: t.array(BidLine),
    statedTotal: t.f64(),
    perks: t.array(t.string()),
    claims: t.array(t.string()),
    floorCheckPassed: t.bool(),
    rejectReason: t.string(), // floor rejection, kept private to the bidder (it names the floor)
    origin: t.string(),
    source: t.string(),
    sealedAt: t.timestamp(),
    lineRejects: t.array(t.string()).default([]), // per line: '' or why it cannot be picked (no floor set)
  },
);

/** Shield verdicts and claim checks attached to a bid; revealed with the bid at close. */
export const bidCheck = table(
  { name: 'bid_check' },
  {
    id: t.u64().primaryKey().autoInc(),
    bidId: t.string().index('btree'),
    kind: t.string(), // shield | claim | advocate
    result: t.string(), // allow|quarantine|block, verified|unverified|false, or buy|caution|veto
    detail: t.string(), // advocate: the rule id, then the text
    evidenceUrl: t.string(),
    origin: t.string(),
    at: t.timestamp(),
  },
);

// ---- private: money ----
/** MOCK shape from 00-shared until Vidyut's Mandate lands. */
export const mandate = table(
  { name: 'mandate' },
  {
    hash: t.string().primaryKey(),
    id: t.string(),
    dealId: t.string(),
    buyerId: t.string(),
    amount: t.f64(),
    payee: t.string(),
    expiry: t.timestamp(),
    nonce: t.string(),
    withinAllowance: t.bool(), // true: auto-approved inside the allowance; false: needs the call
    requestedBy: t.string(), // who asked for the buy (IT seat); empty for a consumer's own buy
    origin: t.string(),
    goalId: t.string().default(''),
    needId: t.string().default(''),
  },
);

/** D's Allowance contract. Private: sellers never see it. */
export const allowance = table(
  { name: 'allowance' },
  {
    buyerId: t.string().primaryKey(),
    currency: t.string(),
    perPurchaseLimit: t.f64(),
    periodLimit: t.f64(),
    period: t.string(),
    spentThisPeriod: t.f64(),
    ladderStep: t.u32(),
    updatedAt: t.timestamp(),
  },
);

/** ReceivingEvent contract; orderId is the paid mandate hash. */
export const receivingEvent = table(
  { name: 'receiving_event' },
  {
    id: t.string().primaryKey(),
    orderId: t.string().index('btree'),
    skuSpec: t.string(),
    photoUrl: t.string(),
    expectedSpecId: t.string(),
    result: t.string(), // accepted | rejected
    reasons: t.array(t.string()),
    creditRequestId: t.string(),
    checkedBy: t.string(), // photo_check | owner
    raisedAllowance: t.bool(),
    origin: t.string(),
    at: t.timestamp(),
  },
);

export const approval = table(
  { name: 'approval' },
  {
    id: t.u64().primaryKey().autoInc(),
    mandateHash: t.string().unique(),
    method: t.string(), // voice_code | typed_code | allowance
    approvedBy: t.string(),
    at: t.timestamp(),
  },
);

export const payment = table(
  { name: 'payment' },
  {
    id: t.u64().primaryKey().autoInc(),
    mandateHash: t.string().unique(),
    paymentRef: t.string(),
    amount: t.f64(),
    at: t.timestamp(),
    mode: t.string().default('sim'), // sim | stripe_test
  },
);

// ---- public ----
export const round = table(
  { name: 'round', public: true },
  {
    id: t.string().primaryKey(),
    needId: t.string().index('btree'),
    openedAt: t.timestamp(),
    deadline: t.timestamp(),
    extensions: t.u32(),
    state: t.string(), // open | review | closed
    sealedCount: t.u32(),
    closedAt: t.option(t.timestamp()),
    origin: t.string(),
    reviewDeadline: t.option(t.timestamp()),
  },
);

/** Written at close: every bid, revealed, with its rank (0 means disqualified) and reasons. */
export const roundResult = table(
  { name: 'round_result', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    roundId: t.string().index('btree'),
    bidId: t.string(),
    sellerId: t.string(),
    persona: t.string(),
    rank: t.u32(),
    landed: t.f64(),
    reasons: t.array(t.string()),
    lines: t.array(BidLine),
    origin: t.string(),
    source: t.string(),
  },
);

/** Shown on screen: a rejected approval, payment or bid attempt. No amounts or floors. */
export const rejectedAttempt = table(
  { name: 'rejected_attempt', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    kind: t.string(),
    refId: t.string(),
    reason: t.string(),
    at: t.timestamp(),
  },
);

/** Every state change writes one. Labels never carry a buyer's cap, limit or goal text. */
/** What each Fetch.ai agent said last, for the agents tile. Public: names, addresses and messages are public demo text. */
export const agentEvent = table(
  { name: 'agent_event', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    agentName: t.string(),
    address: t.string().index('btree'),
    text: t.string(),
    ts: t.timestamp(),
    origin: t.string(),
  },
);

export const floorEvent = table(
  { name: 'floor_event', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    kind: t.string(),
    refTable: t.string(),
    refId: t.string(),
    sellerId: t.string(),
    label: t.string(),
    origin: t.string(),
    at: t.timestamp(),
  },
);

export const persona = table(
  { name: 'persona', public: true },
  {
    sellerId: t.string().primaryKey(),
    name: t.string(),
    archetype: t.string(),
    voiceId: t.string(),
    modelUrl: t.string(),
    origin: t.string(),
  },
);

export const roundTimer = table(
  { name: 'round_timer' },
  {
    scheduledId: t.u64().primaryKey().autoInc(),
    scheduledAt: t.scheduleAt(),
    roundId: t.string(),
  },
);

const spacetimedb = schema({
  need, needItem, goal, goalItem, notification, goalStepEvent, owner, role, pairCode, pairAttempt, buyerProfile, approvalCode, lossReport,
  sellerFloor, bid, bidCheck,
  mandate, approval, payment, allowance, receivingEvent,
  round, roundResult, rejectedAttempt, floorEvent, agentEvent, persona, roundTimer,
});
export default spacetimedb;
