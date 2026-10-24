// Demo data, all labelled SIM. Bids are not seeded: seller agents
// (or market/scripts/sim_sellers.mjs, SIM) place them through place_bid like anyone else.
import type { InferSchema, ReducerCtx } from 'spacetimedb/server';
import type spacetimedb from './schema';
import { insertGoal } from './market';

type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;

export const DEMO = {
  buyerId: 'vidyut',
  goalId: 'goal-vidyut-gpu',
  sellers: [
    { sellerId: 'seller-a', name: 'Seller A', archetype: 'refurbisher' },
    { sellerId: 'seller-b', name: 'Seller B', archetype: 'marketplace seller' },
    { sellerId: 'seller-c', name: 'Seller C', archetype: 'local PC shop' },
  ],
};

export function resetDemo(ctx: Ctx) {
  // Roles, the owner and pairing codes survive a reset so open tabs and agents keep working.
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
  for (const r of [...db.allowance.iter()]) db.allowance.buyerId.delete(r.buyerId);
  for (const r of [...db.receivingEvent.iter()]) db.receivingEvent.id.delete(r.id);
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
  if (!ctx.db.pairCode.buyerId.find(DEMO.buyerId)) {
    const code = String(ctx.random.integerInRange(100000, 999999));
    ctx.db.pairCode.insert({ buyerId: DEMO.buyerId, code });
  }
  if (!ctx.db.goal.id.find(DEMO.goalId)) {
    // "a GPU for 1440p that fits my case and PSU, under $800, by Friday", as Lane A parses it.
    const deadline = new Date(Number(ctx.timestamp.microsSinceUnixEpoch / 1000n) + 3 * 24 * 3600_000).toISOString();
    insertGoal(ctx, {
      id: DEMO.goalId, buyerId: DEMO.buyerId, type: 'part_by_date', cap: 800, deadline, poNumber: '', origin: 'SIM',
      items: [{ skuSpec: 'gpu-rtx5070ti-retail', condition: 'new', variant: 'retail', quantity: 1, skippedOwnedPartId: '' }],
    });
  }
}
