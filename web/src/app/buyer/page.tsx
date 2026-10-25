"use client";

import { useEffect, useMemo, useState } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { useBuyerId } from "@/components/BuyerGate";
import { GoalComposer } from "@/components/GoalComposer";
import { useLiveBuild } from "@/components/useLiveBuild";
import { RecentPurchases } from "@/components/memory";
import { BuyerScreen } from "@/components/screens";
import { allowanceForBuyer, bidsFromRows, dealFromRows, feedFromRows, goalsForBuyer, myRounds, reviewFromRows, shieldFromRows, vetoFromRows } from "@/lib/screens";

/** The dashboard. BuyerGate (app/buyer/layout.tsx) has already proved who this screen is paired as. */
export default function BuyerPage() {
  const buyerId = useBuyerId();
  const [goalRows, goalsReady] = useTable(tables.myGoals);
  const [goalItems] = useTable(tables.myGoalItems);
  const [allowances] = useTable(tables.myAllowance);
  const [rounds] = useTable(tables.round);
  const [results] = useTable(tables.roundResult);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [notes] = useTable(tables.myNotifications);
  const [pending] = useTable(tables.myPendingApprovals);
  const [checks] = useTable(tables.myBidChecks);
  const [deals] = useTable(tables.myDeals);

  const goals = useMemo(() => goalsForBuyer(goalRows, goalItems, allowances[0], buyerId, notes), [goalRows, goalItems, allowances, buyerId, notes]);
  const allowance = useMemo(() => allowanceForBuyer(allowances, buyerId), [allowances, buyerId]);
  // Rounds are market-wide; this buyer's own are the ones named by their my_bid_checks rows.
  const mine = useMemo(() => myRounds(rounds, checks), [rounds, checks]);
  const myLatest = mine[0];
  const roundId = myLatest?.id;
  const myRoundIds = useMemo(() => new Set(mine.map((x) => x.id)), [mine]);
  const liveBids = useMemo(() => (roundId ? bidsFromRows(results, events, roundId) : []), [results, events, roundId]);
  // #449 item 4 PL-12: an expired code never shows (recomputed each second), and a paired screen never shows the sample code.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const review = useMemo(() => reviewFromRows(pending, now), [pending, now]);
  const veto = useMemo(() => vetoFromRows(checks, results, roundId), [checks, results, roundId]);
  const shield = useMemo(() => shieldFromRows(checks, roundId), [checks, roundId]);
  const deal = useMemo(() => dealFromRows(deals, goals[0]?.allowance?.perPurchase ?? null, results), [deals, goals, results]);
  // Floor events are market-wide: keep only those that point at this buyer's goals, or at rounds and bids that belong to them.
  const feed = useMemo(() => {
    const ids = new Set<string>([...goals.map((g) => g.id), ...myRoundIds, ...checks.map((c) => c.bidId)]);
    for (const x of results) if (myRoundIds.has(x.roundId)) ids.add(x.bidId);
    return feedFromRows(events, notes, ids);
  }, [goals, myRoundIds, checks, results, events, notes]);
  const closeKey = useMemo(() => events.filter((e) => e.kind === "auction_closed" && myRoundIds.has(e.refId)).reduce<string | undefined>((k, e) => (k === undefined || BigInt(k) < e.id ? String(e.id) : k), undefined), [events, myRoundIds]);
  const roundOpen = !!myLatest && myLatest.state !== "closed";
  const receiptsCount = useMemo(() => deals.filter((x) => x.paidAt).length, [deals]);
  const liveBuild = useLiveBuild(buyerId);
  // Veto, Shield, approval and receipt come from my_bid_checks and my_deals; a card shows only when its row exists. No sample data on this page.
  return (
    <BuyerScreen
      build={liveBuild ?? undefined}
      connecting={!goalsReady || !eventsReady}
      goals={goals}
      allowance={allowance}
      composer={<GoalComposer buyerId={buyerId} />}
      purchases={<RecentPurchases />}
      bids={liveBids}
      veto={veto}
      shield={shield}
      approval={deal.approval}
      review={review}
      receipt={deal.receipt}
      roundOpen={roundOpen}
      receiptsCount={receiptsCount}
      feed={feed}
      revealKey={closeKey}
    />
  );
}
