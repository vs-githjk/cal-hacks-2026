// Tech Bazaar market tables. Private by default: anything a seller must not see (spend limit,
// goal text, cap, allowance, other sellers' bids before close) lives in a private table and
// reaches clients only through the views in index.ts.
import { schema, table, t } from 'spacetimedb/server';
import { Timestamp } from 'spacetimedb';

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

// ---- private: who may do what ----
/** The identity that published the module; only it assigns roles. Set once in init. */
export const owner = table({ name: 'owner' }, { id: t.u32().primaryKey(), identity: t.identity() });

/** One role per identity: buyer (subject = buyer_id), seller (subject = seller_id) or referee. */
export const role = table(
  { name: 'role' },
  { identity: t.identity().primaryKey(), role: t.string(), subjectId: t.string().index('btree') },
);

/**
 * Demo pairing code per buyer, so a browser screen can take the buyer role (SIM sign-in). The code is a
 * 10-character Crockford base32 string (no ambiguous characters), shown grouped as XXXXX-XXXXX.
 * windowStart/windowMisses/throttledUntil are the soft, code-wide brute-force throttle (#135): they never
 * lock the code, only make a caller wait, so the per-identity lock above stays the only permanent block.
 */
export const pairCode = table(
  { name: 'pair_code' },
  {
    buyerId: t.string().primaryKey(),
    code: t.string(),
    failedAttempts: t.u32().default(0), // appended last so a publish migrates in place
    locked: t.bool().default(false),
    windowStart: t.timestamp().default(Timestamp.UNIX_EPOCH),
    windowMisses: t.u32().default(0),
    throttledUntil: t.timestamp().default(Timestamp.UNIX_EPOCH),
  },
);

/**
 * The one-time word-pair code Lane D's approval service issued for a mandate that needs the buyer's call. Private: only the
 * mandate's buyer sees it (my_pending_approvals). A WHOLE-BUILD code (issue_build_approval_code) has no mandate row yet (the
 * build makes its mandates after the call), so it carries its own amount, label, origin and expiry: `expiry` after the epoch
 * marks a build row, and clearing one sets expiry back to the epoch (the row stays, so telemetry still counts the call).
 * The four trailing columns are appended with defaults so a publish migrates in place.
 */
export const approvalCode = table(
  { name: 'approval_code' },
  {
    mandateHash: t.string().primaryKey(), buyerId: t.string().index('btree'), code: t.string(), failures: t.u32(), locked: t.bool(), issuedAt: t.timestamp(),
    amount: t.f64().default(0),
    payee: t.string().default(''),
    expiry: t.timestamp().default(Timestamp.UNIX_EPOCH),
    origin: t.string().default(''),
  },
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
export const buyerProfile = table({ name: 'buyer_profile' }, { buyerId: t.string().primaryKey(), displayName: t.string(), origin: t.string(), phone: t.string().default('') }); // phone appended last so a publish migrates in place

/** #374: fixed-window counter for open sign-ups (single row, id 0). Private. */
export const signupThrottle = table({ name: 'signup_throttle' }, { id: t.u32().primaryKey(), windowStart: t.timestamp(), count: t.u32() });

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
    // #336: which knockout stage this offer belongs to. 1 for every non-knockout round (unchanged behavior).
    stage: t.u32().default(1),
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
    method: t.string(), // voice_code | allowance (#191: no typed fallback)
    approvedBy: t.string(),
    at: t.timestamp(),
    voiceApprovalId: t.string().default(''), // #191: the VoiceApproval id the call produced ('' for allowance); appended last
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
    state: t.string(), // open | closed
    sealedCount: t.u32(),
    closedAt: t.option(t.timestamp()),
    origin: t.string(),
    // #336: knockout rounds. maxStages 1 (the default) means a plain sealed round: close_round behaves exactly as before.
    stage: t.u32().default(1),
    maxStages: t.u32().default(1),
    stageWindowS: t.u32().default(0),
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
    // #135: the real quality-adjusted score rankBids used to order this row (equal to landed when not
    // ranked or when nothing adjusted it), plus the short reason it differs from landed. Appended last so a
    // publish migrates in place.
    adjustedTotal: t.f64().default(0),
    adjustmentReason: t.string().default(''),
    // #336: knockout rounds. stage 1 and status '' for every plain round_result (unchanged).
    stage: t.u32().default(1),
    status: t.string().default(''), // '' | knocked_out | advancing | champion
  },
);

/**
 * Private. A knockout stage that leaves the round open writes its knocked_out rows to the public round_result
 * with rank 0, landed 0 and no lines (a rival still bidding must not read a rival's price or place). The real
 * values wait here, keyed by the public row's id, and the stage close that finally closes the round copies
 * them back and deletes these rows.
 */
export const roundResultSealed = table(
  { name: 'round_result_sealed' },
  {
    resultId: t.u64().primaryKey(),
    roundId: t.string().index('btree'),
    rank: t.u32(),
    landed: t.f64(),
    lines: t.array(BidLine),
    adjustedTotal: t.f64(),
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

/**
 * One row per unit held for a round's winning line. Written at close, renewed when the mandate is made,
 * sold by the payment and released by a denial or by its 2 minute expiry. Public: seller, line and round
 * only (no buyer, amount or mandate). Available stock = a bid line's stated stock minus its active holds.
 */
export const stockHold = table(
  { name: 'stock_hold', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    sellerId: t.string().index('btree'),
    skuSpec: t.string(),
    condition: t.string(),
    qty: t.f64(),
    roundId: t.string().index('btree'),
    bidId: t.string().index('btree'),
    expiresAt: t.timestamp(),
    state: t.string(), // held | sold | released
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

/** #374 public telemetry row types: counts only, no money, names or per-user data. */
export const TelemetryRow = t.object('TelemetryRow', {
  accountsCreated: t.u32(), goalsPosted: t.u32(), roundsOpened: t.u32(), roundsClosed: t.u32(), bids: t.u32(),
  shieldCatches: t.u32(), callsPlaced: t.u32(), approvals: t.u32(), denials: t.u32(), errors: t.u32(),
  roundP50Ms: t.u32(), roundP95Ms: t.u32(),
});
export const AgentBuyerContactRow = t.object('AgentBuyerContactRow', { buyerId: t.string(), displayName: t.string(), phone: t.string() });
export const TelemetryAgentRow = t.object('TelemetryAgentRow', { agent: t.string(), events: t.u32() });

const spacetimedb = schema({
  need, needItem, goal, goalItem, notification, owner, role, pairCode, pairAttempt, buyerProfile, signupThrottle, approvalCode, lossReport,
  sellerFloor, bid, bidCheck,
  mandate, approval, payment, allowance, receivingEvent,
  round, roundResult, roundResultSealed, rejectedAttempt, floorEvent, agentEvent, stockHold, persona, roundTimer,
});
export default spacetimedb;
