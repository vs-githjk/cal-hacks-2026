"use client";

import { useEffect, useMemo, useState } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { useBuyerId } from "@/components/BuyerGate";
import { GoalComposer } from "@/components/GoalComposer";
import { useLiveBuild } from "@/components/useLiveBuild";
import { RecentPurchases } from "@/components/memory";
import { BuyerScreen } from "@/components/screens";
import { allowanceForBuyer, asSim, bidsFromRows, buyerRefIds, dealFromRows, feedFromRows, goalsForBuyer, latestRound, reviewFromRows, shieldFromRows, vetoFromRows, approvalForScreen } from "@/lib/screens";
import * as sample from "@/lib/sample";

/** The dashboard. BuyerGate (app/buyer/layout.tsx) has already proved who this screen is paired as. */
export default function BuyerPage() {
  const buyerId = useBuyerId();
  const [goalRows, goalsReady] = useTable(tables.myGoals);
  const [goalItems] = useTable(tables.myGoalItems);
  const [allowances] = useTable(tables.myAllowance);
  // #449 PL-3: this buyer's own rounds (my_rounds). Until `spacetime generate` adds tables.myRounds to module_bindings the table is
  // missing, and the page shows the SIM sample; it never falls back to the public round table. The ternary is fixed per build, so the hook order is stable.
  const myRoundsTable = (tables as unknown as { myRounds?: typeof tables.round }).myRounds;
  const [myRoundRows] = useTable(myRoundsTable ?? tables.round);
  const rounds = useMemo(() => (myRoundsTable ? myRoundRows : []), [myRoundsTable, myRoundRows]);
  const [results] = useTable(tables.roundResult);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [notes] = useTable(tables.myNotifications);
  const [pending] = useTable(tables.myPendingApprovals);
  const [checks] = useTable(tables.myBidChecks);
  const [deals] = useTable(tables.myDeals);

  const goals = useMemo(() => goalsForBuyer(goalRows, goalItems, allowances[0], buyerId, notes), [goalRows, goalItems, allowances, buyerId, notes]);
  const allowance = useMemo(() => allowanceForBuyer(allowances, buyerId), [allowances, buyerId]);
  const roundId = useMemo(() => latestRound(rounds)?.id, [rounds]);
  const liveBids = useMemo(() => bidsFromRows(results, events, roundId), [results, events, roundId]);
  const mine = useMemo(() => buyerRefIds(rounds, results, checks, deals), [rounds, results, checks, deals]);
  const feed = useMemo(() => feedFromRows(events, notes, mine), [events, notes, mine]);
  const sim = liveBids.length === 0;
  // #449 item 4 PL-12: an expired code never shows (recomputed each second), and a paired screen never shows the sample code.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const review = useMemo(() => reviewFromRows(pending, results, now), [pending, results, now]);
  const veto = useMemo(() => vetoFromRows(checks, results, roundId), [checks, results, roundId]);
  const shield = useMemo(() => shieldFromRows(checks, roundId), [checks, roundId]);
  const deal = useMemo(() => dealFromRows(deals, goals[0]?.allowance?.perPurchase ?? null, results), [deals, goals, results]);
  const closeKey = useMemo(() => events.filter((e) => e.kind === "auction_closed" && mine.has(e.refId)).reduce<string | undefined>((k, e) => (k === undefined || BigInt(k) < e.id ? String(e.id) : k), undefined), [events, mine]);
  const approvalCard = approvalForScreen(deal.approval, buyerId, sample.approval);
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
      approval={approvalCard.approval}
      review={review}
      receipt={deal.receipt ?? asSim(sample.receipt)}
      feed={feed}
      revealKey={closeKey}
      sample={{ bids: sim, veto: !veto, shield: !shield, approval: !review && approvalCard.sample, receipt: !deal.receipt }}
    />
  );
}
