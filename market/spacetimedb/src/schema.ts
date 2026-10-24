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
  variant: t.string(),
  quantity: t.f64(),
  unit: t.string(),
});

export const GoalItemArg = t.object('GoalItemArg', {
  category: t.string(),
  description: t.string(),
  skuSpec: t.string(),
  modelNumber: t.string(),
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
  },
);

export const goal = table(
  { name: 'goal' },
  {
    id: t.string().primaryKey(),
    buyerId: t.string().index('btree'),
    type: t.string(),
    text: t.string(),
    cap: t.f64(),
    deadline: t.timestamp(),
    state: t.string(),
    reservedAmount: t.f64(),
    poNumber: t.string(),
    origin: t.string(),
    createdAt: t.timestamp(),
  },
);

export const goalItem = table(
  { name: 'goal_item' },
  {
    id: t.u64().primaryKey().autoInc(),
    goalId: t.string().index('btree'),
    category: t.string(),
    description: t.string(),
    skuSpec: t.string(),
    modelNumber: t.string(),
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

/** Which identity is looking at which buyer's screen (demo sign-in, labelled SIM). */
export const buyerSession = table(
  { name: 'buyer_session' },
  { identity: t.identity().primaryKey(), buyerId: t.string() },
);

// ---- private: seller side ----
export const sellerIdentity = table(
  { name: 'seller_identity' },
  { identity: t.identity().primaryKey(), sellerId: t.string().unique() },
);

export const sellerFloor = table(
  { name: 'seller_floor' },
  {
    id: t.u64().primaryKey().autoInc(),
    sellerId: t.string().index('btree'),
    skuSpec: t.string(),
    floor: t.f64(),
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
  },
);

/** Shield verdicts and claim checks attached to a bid; revealed with the bid at close. */
export const bidCheck = table(
  { name: 'bid_check' },
  {
    id: t.u64().primaryKey().autoInc(),
    bidId: t.string().index('btree'),
    kind: t.string(), // shield | claim
    result: t.string(), // allow|quarantine|block or verified|unverified|false
    detail: t.string(),
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
    origin: t.string(),
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
    state: t.string(), // open | closed
    sealedCount: t.u32(),
    closedAt: t.option(t.timestamp()),
    origin: t.string(),
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
  need, needItem, goal, goalItem, notification, buyerSession,
  sellerIdentity, sellerFloor, bid, bidCheck,
  mandate, approval, payment,
  round, roundResult, rejectedAttempt, floorEvent, persona, roundTimer,
});
export default spacetimedb;
