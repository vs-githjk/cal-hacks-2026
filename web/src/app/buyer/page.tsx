"use client";

import { useMemo } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { useBuyerId } from "@/components/BuyerGate";
import { GoalComposer } from "@/components/GoalComposer";
import { useLiveBuild } from "@/components/useLiveBuild";
import { RecentPurchases } from "@/components/memory";
import { BuyerScreen } from "@/components/screens";
import { allowanceForBuyer, asSim, bidsFromRows, dealFromRows, feedFromRows, goalsForBuyer, latestRound, reviewFromRows, shieldFromRows, vetoFromRows } from "@/lib/screens";
import * as sample from "@/lib/sample";

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

  const goals = useMemo(() => goalsForBuyer(goalRows, goalItems, allowances[0], buyerId), [goalRows, goalItems, allowances, buyerId]);
  const allowance = useMemo(() => allowanceForBuyer(allowances, buyerId), [allowances, buyerId]);
  const liveBids = useMemo(() => bidsFromRows(results, events, latestRound(rounds)?.id), [results, events, rounds]);
  const feed = useMemo(() => feedFromRows(events, notes), [events, notes]);
  const sim = liveBids.length === 0;
  const review = useMemo(() => reviewFromRows(pending, results), [pending, results]);
  const roundId = latestRound(rounds)?.id;
  const veto = useMemo(() => vetoFromRows(checks, results, roundId), [checks, results, roundId]);
  const shield = useMemo(() => shieldFromRows(checks, roundId), [checks, roundId]);
  const deal = useMemo(() => dealFromRows(deals, goals[0]?.allowance?.perPurchase ?? null, results), [deals, goals, results]);
  const closeKey = useMemo(() => events.filter((e) => e.kind === "auction_closed").reduce<string | undefined>((k, e) => (k === undefined || BigInt(k) < e.id ? String(e.id) : k), undefined), [events]);
  const liveBuild = useLiveBuild();
  // #191-5: veto, Shield, approval and receipt come from my_bid_checks and my_deals; a card shows the SIM sample only while its row is missing.
  return (
    <BuyerScreen
      build={liveBuild ?? undefined}
      connecting={!goalsReady || !eventsReady}
      goals={goals}
      allowance={allowance}
      composer={<GoalComposer buyerId={buyerId} />}
      purchases={<RecentPurchases />}
      bids={sim ? asSim(sample.rankedBids) : liveBids}
      veto={veto ?? asSim(sample.veto)}
      shield={shield ?? asSim(sample.shield)}
      approval={deal.approval ?? asSim(sample.approval)}
      review={review}
      receipt={deal.receipt ?? asSim(sample.receipt)}
      feed={feed}
      revealKey={closeKey}
      sample={{ bids: sim, veto: !veto, shield: !shield, approval: !review && !deal.approval, receipt: !deal.receipt }}
    />
  );
}
