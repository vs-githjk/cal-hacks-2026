// Demo data, all labelled SIM. Joe is a labelled demo persona. Bids are not seeded: seller agents
// (or market/scripts/sim_sellers.mjs, SIM) place them through place_bid like anyone else.
import type { InferSchema, ReducerCtx } from 'spacetimedb/server';
import type spacetimedb from './schema';
import { postGoal } from './market';

type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;

export const DEMO = {
  buyerId: 'joe',
  goalId: 'goal-joe-gpu',
  goalText: 'a GPU for 1440p that fits my case and PSU, under $800, by Friday',
  sellers: [
    { sellerId: 'seller-a', name: 'Seller A', archetype: 'refurbisher' },
    { sellerId: 'seller-b', name: 'Seller B', archetype: 'marketplace seller' },
    { sellerId: 'seller-c', name: 'Seller C', archetype: 'local PC shop' },
  ],
};

export function resetDemo(ctx: Ctx) {
  // Identities and buyer screen sessions survive a reset so open tabs and agents keep working.
  const db = ctx.db;
  for (const r of [...db.need.iter()]) db.need.id.delete(r.id);
  for (const r of [...db.needItem.iter()]) db.needItem.id.delete(r.id);
  for (const r of [...db.goal.iter()]) db.goal.id.delete(r.id);
  for (const r of [...db.goalItem.iter()]) db.goalItem.id.delete(r.id);
  for (const r of [...db.notification.iter()]) db.notification.id.delete(r.id);
  for (const r of [...db.bid.iter()]) db.bid.id.delete(r.id);
  for (const r of [...db.bidCheck.iter()]) db.bidCheck.id.delete(r.id);
  for (const r of [...db.mandate.iter()]) db.mandate.hash.delete(r.hash);
  for (const r of [...db.approval.iter()]) db.approval.id.delete(r.id);
  for (const r of [...db.payment.iter()]) db.payment.id.delete(r.id);
  for (const r of [...db.round.iter()]) db.round.id.delete(r.id);
  for (const r of [...db.roundResult.iter()]) db.roundResult.id.delete(r.id);
  for (const r of [...db.rejectedAttempt.iter()]) db.rejectedAttempt.id.delete(r.id);
  for (const r of [...db.roundTimer.iter()]) db.roundTimer.scheduledId.delete(r.scheduledId);
  for (const r of [...db.floorEvent.iter()]) db.floorEvent.id.delete(r.id);
  for (const r of [...db.persona.iter()]) db.persona.sellerId.delete(r.sellerId);
  ctx.db.floorEvent.insert({ id: 0n, kind: 'reset', refTable: '', refId: '', sellerId: '', label: 'Demo reset', origin: 'SIM', at: ctx.timestamp });
}

export function seedDemo(ctx: Ctx) {
  for (const s of DEMO.sellers) {
    if (!ctx.db.persona.sellerId.find(s.sellerId)) {
      ctx.db.persona.insert({ sellerId: s.sellerId, name: s.name, archetype: s.archetype, voiceId: '', modelUrl: '', origin: 'SIM' });
    }
  }
  if (!ctx.db.goal.id.find(DEMO.goalId)) {
    postGoal(ctx, {
      id: DEMO.goalId, buyerId: DEMO.buyerId, type: 'part_by_date', text: DEMO.goalText, cap: 800,
      deadlineMinutes: 60 * 24 * 3, poNumber: '', origin: 'SIM',
      items: [{ category: 'gpu', description: 'GPU for 1440p that fits the case and PSU Joe owns', skuSpec: '', modelNumber: '' }],
    });
  }
}
