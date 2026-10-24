"use client";

import { useMemo } from "react";
import { useReducer, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { useBuyerId } from "@/components/BuyerGate";
import { GoalComposer } from "@/components/GoalComposer";
import { RecentPurchases } from "@/components/memory";
import { BuyerScreen } from "@/components/screens";
import { allowanceForBuyer, asSim, bidsFromRows, feedFromRows, goalsForBuyer, latestRound, reviewFromRows } from "@/lib/screens";
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
  const approveTyped = useReducer(reducers.approveTyped);

  const goals = useMemo(() => goalsForBuyer(goalRows, goalItems, allowances[0], buyerId), [goalRows, goalItems, allowances, buyerId]);
  const allowance = useMemo(() => allowanceForBuyer(allowances, buyerId), [allowances, buyerId]);
  const liveBids = useMemo(() => bidsFromRows(results, events, latestRound(rounds)?.id), [results, events, rounds]);
  const feed = useMemo(() => feedFromRows(events, notes), [events, notes]);
  const sim = liveBids.length === 0;
  const review = useMemo(() => reviewFromRows(pending), [pending]);
  const closeKey = useMemo(() => events.filter((e) => e.kind === "auction_closed").reduce<string | undefined>((k, e) => (k === undefined || BigInt(k) < e.id ? String(e.id) : k), undefined), [events]);
  // A wrong code is counted in my_pending_approvals (failures); a match records the approval and the row leaves the view.
  const onTyped = async (mandateHash: string, code: string) => {
    if (!code) return "Type the two words shown above.";
    try {
      await approveTyped({ mandateHash, code });
      return "If it matched, this card disappears and the approval is recorded.";
    } catch (err) {
      return err instanceof Error ? err.message : "Approval failed";
    }
  };

  // veto, shield, approval and receipt rows (bid_check, mandate, approval, payment) are not public yet: those cards show the SIM sample.
  return (
    <BuyerScreen
      connecting={!goalsReady || !eventsReady}
      goals={goals}
      allowance={allowance}
      composer={<GoalComposer buyerId={buyerId} />}
      purchases={<RecentPurchases />}
      bids={sim ? asSim(sample.rankedBids) : liveBids}
      veto={asSim(sample.veto)}
      shield={asSim(sample.shield)}
      approval={asSim(sample.approval)}
      review={review}
      onTyped={onTyped}
      receipt={asSim(sample.receipt)}
      feed={feed}
      revealKey={closeKey}
      sample={{ bids: sim, veto: true, shield: true, approval: !review, receipt: true }}
    />
  );
}
