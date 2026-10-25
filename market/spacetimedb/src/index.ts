// Module entry: registers reducers and views. Bodies live in market.ts (tested in market.test.ts).
import { t } from 'spacetimedb/server';
import spacetimedb, { AgentBuyerContactRow, BidLine, GoalItemArg, NeedItemArg, StrategyStep, TelemetryAgentRow, TelemetryRow, allowance, bid, buyerProfile, goal, goalItem, lossReport, notification, pairAttempt, role, roundTimer } from './schema';
import * as m from './market';

export default spacetimedb;

export const init = spacetimedb.init((ctx) => m.init(ctx));

export const assign_role = spacetimedb.reducer(
  { identity: t.identity(), role: t.string(), subjectId: t.string() },
  (ctx, a) => m.assignRole(ctx, a),
);
export const pair_buyer_screen = spacetimedb.reducer({ buyerId: t.string(), code: t.string() }, (ctx, a) => {
  m.pairBuyerScreen(ctx, a);
});
export const sign_up_buyer = spacetimedb.reducer({ displayName: t.string(), phone: t.option(t.string()) }, (ctx, a) => {
  m.signUpBuyer(ctx, { displayName: a.displayName, phone: a.phone ?? undefined });
});
export const reissue_pair_code = spacetimedb.reducer({ buyerId: t.string(), code: t.string() }, (ctx, a) => m.reissuePairCode(ctx, a));
export const pair_seller_screen = spacetimedb.reducer({ sellerId: t.string(), code: t.string() }, (ctx, a) => {
  m.pairSellerScreen(ctx, a);
});
export const reissue_seller_screen_code = spacetimedb.reducer({ sellerId: t.string(), code: t.string() }, (ctx, a) => m.reissueSellerScreenCode(ctx, a));
export const set_buyer_profile = spacetimedb.reducer({ buyerId: t.string(), displayName: t.string() }, (ctx, a) => m.setBuyerProfile(ctx, a));
export const set_floor = spacetimedb.reducer({ skuSpec: t.string(), floor: t.f64() }, (ctx, a) => m.setFloor(ctx, a));
export const set_floor_for_condition = spacetimedb.reducer(
  { skuSpec: t.string(), condition: t.string(), floor: t.f64() },
  (ctx, a) => m.setFloorForCondition(ctx, a),
);

export const post_need = spacetimedb.reducer(
  {
    id: t.string(), buyerId: t.string(), goalId: t.string(), deliveryWindow: t.string(), spendLimit: t.f64(),
    consent: t.bool(), auctionWindowS: t.u32(), origin: t.string(), items: t.array(NeedItemArg),
  },
  (ctx, a) => m.postNeed(ctx, a),
);

export const post_goal = spacetimedb.reducer(
  {
    id: t.string(), buyerId: t.string(), type: t.string(), cap: t.f64(), deadline: t.string(),
    poNumber: t.string(), origin: t.string(), items: t.array(GoalItemArg),
  },
  (ctx, a) => m.postGoal(ctx, a),
);

export const open_round = spacetimedb.reducer({ roundId: t.string(), needId: t.string(), windowS: t.u32() }, (ctx, a) => m.openRound(ctx, a));

export const open_knockout_round = spacetimedb.reducer(
  { roundId: t.string(), needId: t.string(), stageWindowS: t.u32(), maxStages: t.u32() },
  (ctx, a) => m.openKnockoutRound(ctx, a),
);

export const place_bid = spacetimedb.reducer(
  {
    id: t.string(), roundId: t.string(), persona: t.string(), lines: t.array(BidLine), statedTotal: t.f64(),
    perks: t.array(t.string()), claims: t.array(t.string()), origin: t.string(), source: t.string(),
  },
  (ctx, a) => m.placeBid(ctx, a),
);

export const close_round = spacetimedb.reducer({ roundId: t.string() }, (ctx, a) => m.closeRound(ctx, a));

export const close_round_on_deadline = spacetimedb.reducer({ onSchedule: roundTimer }, { timer: roundTimer.rowType }, (ctx, { timer }) =>
  m.closeRoundOnDeadline(ctx, timer.roundId),
);

export const close_stage = spacetimedb.reducer({ roundId: t.string() }, (ctx, a) => m.closeStage(ctx, a));

export const attach_verdict = spacetimedb.reducer(
  { bidId: t.string(), verdict: t.string(), ruleIds: t.array(t.string()), origin: t.string() },
  (ctx, a) => m.attachVerdict(ctx, a),
);

export const attach_claim_check = spacetimedb.reducer(
  { bidId: t.string(), claim: t.string(), check: t.string(), evidenceUrl: t.string(), origin: t.string() },
  (ctx, a) => m.attachClaimCheck(ctx, a),
);

export const attach_advocate_card = spacetimedb.reducer(
  { bidId: t.string(), recommendation: t.string(), ruleId: t.string(), text: t.string(), sourceUrl: t.string(), origin: t.string() },
  (ctx, a) => m.attachAdvocateCard(ctx, a),
);

export const create_mandate = spacetimedb.reducer(
  {
    hash: t.string(), id: t.string(), dealId: t.string(), buyerId: t.string(), amount: t.f64(), payee: t.string(),
    expiryMinutes: t.u32(), nonce: t.string(), requestedBy: t.string(), origin: t.string(),
  },
  (ctx, a) => m.createMandate(ctx, a),
);

export const record_approval = spacetimedb.reducer(
  { mandateHash: t.string(), method: t.string(), approvedBy: t.string(), voiceApprovalId: t.string() },
  (ctx, a) => m.recordApproval(ctx, a),
);

export const issue_approval_code = spacetimedb.reducer({ mandateHash: t.string(), code: t.string() }, (ctx, a) => m.issueApprovalCode(ctx, a));
export const issue_build_approval_code = spacetimedb.reducer(
  { mandateHash: t.string(), buyerId: t.string(), amount: t.f64(), payee: t.string(), expiryMinutes: t.u32(), code: t.string(), origin: t.string() },
  (ctx, a) => m.issueBuildApprovalCode(ctx, a),
);
export const clear_build_approval_code = spacetimedb.reducer({ mandateHash: t.string() }, (ctx, a) => m.clearBuildApprovalCode(ctx, a));

export const record_loss_report = spacetimedb.reducer(
  {
    id: t.string(), roundId: t.string(), sellerId: t.string(), won: t.bool(), gapBand: t.string(), reason: t.string(), sourceUrl: t.string(),
    strategyDiff: t.array(StrategyStep), whatToChange: t.string(), whatToChangeOrigin: t.string(), origin: t.string(),
  },
  (ctx, a) => m.recordLossReport(ctx, a),
);

export const record_agent_event = spacetimedb.reducer(
  { agentName: t.string(), address: t.string(), text: t.string(), ts: t.string(), origin: t.string() },
  (ctx, a) => m.recordAgentEvent(ctx, a),
);

export const deny_approval = spacetimedb.reducer(
  { mandateHash: t.string(), reason: t.string() },
  (ctx, a) => m.denyApproval(ctx, a),
);

export const record_payment = spacetimedb.reducer(
  { mandateHash: t.string(), paymentRef: t.string(), amount: t.f64(), mode: t.string() },
  (ctx, a) => m.recordPayment(ctx, a),
);

export const record_receiving = spacetimedb.reducer(
  {
    id: t.string(), orderId: t.string(), skuSpec: t.string(), photoUrl: t.string(), expectedSpecId: t.string(),
    result: t.string(), reasons: t.array(t.string()), checkedBy: t.string(), origin: t.string(),
  },
  (ctx, a) => m.recordReceiving(ctx, a),
);

export const set_allowance = spacetimedb.reducer(
  { buyerId: t.string(), perPurchaseLimit: t.f64(), periodLimit: t.f64(), period: t.string() },
  (ctx, a) => m.setAllowanceChecked(ctx, a),
);

export const reset_demo = spacetimedb.reducer((ctx) => m.resetDemoChecked(ctx));
export const seed_demo = spacetimedb.reducer((ctx) => m.seedDemoChecked(ctx));

const SellerNeedRow = t.object('SellerNeedRow', {
  roundId: t.string(), needId: t.string(), skuSpec: t.string(), condition: t.string(), variant: t.string(),
  quantity: t.f64(), unit: t.string(), deliveryWindow: t.string(), deadline: t.timestamp(), ceilingBand: t.string(), origin: t.string(),
});

export const seller_needs = spacetimedb.anonymousView({ name: 'seller_needs', public: true }, t.array(SellerNeedRow), (ctx) => m.sellerNeedsView(ctx));
export const my_bids = spacetimedb.view({ name: 'my_bids', public: true }, t.array(bid.rowType), (ctx) => m.myBidsView(ctx));
export const my_goals = spacetimedb.view({ name: 'my_goals', public: true }, t.array(goal.rowType), (ctx) => m.myGoalsView(ctx));
export const my_goal_items = spacetimedb.view({ name: 'my_goal_items', public: true }, t.array(goalItem.rowType), (ctx) => m.myGoalItemsView(ctx));
export const my_role = spacetimedb.view({ name: 'my_role', public: true }, t.array(role.rowType), (ctx) => m.myRoleView(ctx));
export const my_pair_attempts = spacetimedb.view({ name: 'my_pair_attempts', public: true }, t.array(pairAttempt.rowType), (ctx) => m.myPairAttemptsView(ctx));
export const my_allowance = spacetimedb.view({ name: 'my_allowance', public: true }, t.array(allowance.rowType), (ctx) => m.myAllowanceView(ctx));
export const my_notifications = spacetimedb.view({ name: 'my_notifications', public: true }, t.array(notification.rowType), (ctx) => m.myNotificationsView(ctx));

const PendingApprovalRow = t.object('PendingApprovalRow', {
  mandateHash: t.string(), mandateId: t.string(), amount: t.f64(), payee: t.string(), expiry: t.timestamp(), code: t.string(),
  failures: t.u32(), locked: t.bool(), issuedAt: t.timestamp(), origin: t.string(),
});
export const my_pending_approvals = spacetimedb.view({ name: 'my_pending_approvals', public: true }, t.array(PendingApprovalRow), (ctx) => m.myPendingApprovalsView(ctx));
const BidCheckRow = t.object('BidCheckRow', {
  id: t.u64(), bidId: t.string(), roundId: t.string(), sellerId: t.string(), persona: t.string(), bidOrigin: t.string(), kind: t.string(),
  result: t.string(), detail: t.string(), evidenceUrl: t.string(), origin: t.string(), at: t.timestamp(),
});
export const my_bid_checks = spacetimedb.view({ name: 'my_bid_checks', public: true }, t.array(BidCheckRow), (ctx) => m.myBidChecksView(ctx));
const DealRow = t.object('DealRow', {
  mandateHash: t.string(), mandateId: t.string(), dealId: t.string(), amount: t.f64(), payee: t.string(), expiry: t.timestamp(),
  withinAllowance: t.bool(), origin: t.string(), approvalMethod: t.string(), voiceApprovalId: t.string(), approvedAt: t.option(t.timestamp()),
  paymentRef: t.string(), paymentMode: t.string(), paidAt: t.option(t.timestamp()),
});
export const my_deals = spacetimedb.view({ name: 'my_deals', public: true }, t.array(DealRow), (ctx) => m.myDealsView(ctx));
export const my_loss_reports = spacetimedb.view({ name: 'my_loss_reports', public: true }, t.array(lossReport.rowType), (ctx) => m.myLossReportsView(ctx));
export const my_buyer_profile = spacetimedb.view({ name: 'my_buyer_profile', public: true }, t.array(buyerProfile.rowType), (ctx) => m.myBuyerProfileView(ctx));

const StandingRow = t.object('StandingRow', {
  roundId: t.string(), stillIn: t.bool(), reason: t.string(), lastOfferSkuSpec: t.string(), lastOfferPrice: t.f64(),
});
export const my_standing = spacetimedb.view({ name: 'my_standing', public: true }, t.array(StandingRow), (ctx) => m.myStandingView(ctx));

/** #374 public telemetry: one row of market-wide counts. No money, no names, nothing per user. */
export const telemetry = spacetimedb.anonymousView({ name: 'telemetry', public: true }, t.array(TelemetryRow), (ctx) => m.telemetryView(ctx));
export const telemetry_agent = spacetimedb.anonymousView({ name: 'telemetry_agent', public: true }, t.array(TelemetryAgentRow), (ctx) => m.telemetryAgentView(ctx));

/** #374: referee only (the agents' identity); empty for everyone else. */
export const agent_buyer_contact = spacetimedb.view({ name: 'agent_buyer_contact', public: true }, t.array(AgentBuyerContactRow), (ctx) => m.agentBuyerContactView(ctx));
export const agent_open_goals = spacetimedb.view({ name: 'agent_open_goals', public: true }, t.array(goal.rowType), (ctx) => m.agentOpenGoalsView(ctx));
export const agent_goal_items = spacetimedb.view({ name: 'agent_goal_items', public: true }, t.array(goalItem.rowType), (ctx) => m.agentGoalItemsView(ctx));
