// Module entry: registers reducers and views. Bodies live in market.ts (tested in market.test.ts).
import { t } from 'spacetimedb/server';
import spacetimedb, { BidLine, GoalItemArg, NeedItemArg, bid, goal, goalItem, notification, role, roundTimer } from './schema';
import * as m from './market';

export default spacetimedb;

export const init = spacetimedb.init((ctx) => m.init(ctx));

export const assign_role = spacetimedb.reducer(
  { identity: t.identity(), role: t.string(), subjectId: t.string() },
  (ctx, a) => m.assignRole(ctx, a),
);
export const pair_buyer_screen = spacetimedb.reducer({ buyerId: t.string(), code: t.string() }, (ctx, a) => m.pairBuyerScreen(ctx, a));
export const set_floor = spacetimedb.reducer({ skuSpec: t.string(), floor: t.f64() }, (ctx, a) => m.setFloor(ctx, a));

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

export const attach_verdict = spacetimedb.reducer(
  { bidId: t.string(), verdict: t.string(), ruleIds: t.array(t.string()), origin: t.string() },
  (ctx, a) => m.attachVerdict(ctx, a),
);

export const attach_claim_check = spacetimedb.reducer(
  { bidId: t.string(), claim: t.string(), check: t.string(), evidenceUrl: t.string(), origin: t.string() },
  (ctx, a) => m.attachClaimCheck(ctx, a),
);

export const create_mandate = spacetimedb.reducer(
  {
    hash: t.string(), id: t.string(), dealId: t.string(), buyerId: t.string(), amount: t.f64(), payee: t.string(),
    expiryMinutes: t.u32(), nonce: t.string(), origin: t.string(),
  },
  (ctx, a) => m.createMandate(ctx, a),
);

export const record_approval = spacetimedb.reducer(
  { mandateHash: t.string(), method: t.string(), approvedBy: t.string() },
  (ctx, a) => m.recordApproval(ctx, a),
);

export const record_payment = spacetimedb.reducer(
  { mandateHash: t.string(), paymentRef: t.string(), amount: t.f64() },
  (ctx, a) => m.recordPayment(ctx, a),
);

export const reset_demo = spacetimedb.reducer((ctx) => m.resetDemoChecked(ctx));
export const seed_demo = spacetimedb.reducer((ctx) => m.seedDemoChecked(ctx));

const SellerNeedRow = t.object('SellerNeedRow', {
  roundId: t.string(), needId: t.string(), skuSpec: t.string(), condition: t.string(), variant: t.string(),
  quantity: t.f64(), unit: t.string(), deliveryWindow: t.string(), deadline: t.timestamp(),
});

export const seller_needs = spacetimedb.anonymousView({ name: 'seller_needs', public: true }, t.array(SellerNeedRow), (ctx) => m.sellerNeedsView(ctx));
export const my_bids = spacetimedb.view({ name: 'my_bids', public: true }, t.array(bid.rowType), (ctx) => m.myBidsView(ctx));
export const my_goals = spacetimedb.view({ name: 'my_goals', public: true }, t.array(goal.rowType), (ctx) => m.myGoalsView(ctx));
export const my_goal_items = spacetimedb.view({ name: 'my_goal_items', public: true }, t.array(goalItem.rowType), (ctx) => m.myGoalItemsView(ctx));
export const my_role = spacetimedb.view({ name: 'my_role', public: true }, t.array(role.rowType), (ctx) => m.myRoleView(ctx));
export const my_notifications = spacetimedb.view({ name: 'my_notifications', public: true }, t.array(notification.rowType), (ctx) => m.myNotificationsView(ctx));
