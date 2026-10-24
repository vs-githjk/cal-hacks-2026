"use client";

import { useEffect, useMemo, useState } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import type { Timestamp } from "spacetimedb";
import { reducers, tables } from "@/module_bindings";
import { AgentsTile } from "@/components/AgentsTile";
import { BuyerScreen } from "@/components/screens";
import { bidsFromRows, feedFromRows, goalFromRows, latestGoal, purchaseFromRows, reviewsFromRows, stepFeedFromRows } from "@/lib/screens";

// Demo sign-in: the buyer is fixed to Vidyut. Real sign-in replaces this.
const DEMO_BUYER = "vidyut";
// Matches PAIR_MAX_FAILURES in market/spacetimedb/src/market.ts.
const PAIR_MAX_FAILURES = 5;

interface BuyerRoundRow { goalId: string; roundId: string; openedAt: Timestamp }
interface BuyerStepRow { stableId: string; goalId: string; klass: string; text: string; origin: string; at: Timestamp }
interface BuyerNotificationRow { id: bigint; goalId: string; klass: string; text: string; at: Timestamp }

export function selectBuyerRound(rows: readonly BuyerRoundRow[], goalId: string): BuyerRoundRow | null {
  return [...rows].filter((row) => row.goalId === goalId).sort((a, b) => {
    if (a.openedAt.microsSinceUnixEpoch !== b.openedAt.microsSinceUnixEpoch) {
      return a.openedAt.microsSinceUnixEpoch > b.openedAt.microsSinceUnixEpoch ? -1 : 1;
    }
    return a.roundId.localeCompare(b.roundId);
  })[0] ?? null;
}

export function buyerFeedFromRows(steps: readonly BuyerStepRow[], notifications: readonly BuyerNotificationRow[], goalId: string) {
  const ownedSteps = new Map<string, BuyerStepRow>();
  for (const row of steps) if (row.goalId === goalId && !ownedSteps.has(row.stableId)) ownedSteps.set(row.stableId, row);
  const ownedNotifications = new Map<string, BuyerNotificationRow>();
  for (const row of notifications) if (row.goalId === goalId && !ownedNotifications.has(String(row.id))) ownedNotifications.set(String(row.id), row);
  const stepItems = stepFeedFromRows([...ownedSteps.values()], goalId).map((item) => ({ ...item, key: `step-${item.key}` }));
  const notificationItems = feedFromRows([], [...ownedNotifications.values()]).map((item) => ({ ...item, key: `notification-${item.key.slice(1)}` }));
  return [...stepItems, ...notificationItems].sort((a, b) => b.at.getTime() - a.at.getTime() || a.key.localeCompare(b.key));
}

/** A screen sees Vidyut's goal only after pairing with the demo code (SIM sign-in). */
function PairScreen() {
  const pair = useReducer(reducers.pairBuyerScreen);
  const [attempts] = useTable(tables.myPairAttempts);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [tried, setTried] = useState(false);
  const failures = attempts[0]?.failures ?? 0;
  return (
    <section className="card mx-auto max-w-md p-6">
      <h1 className="mb-2 text-lg font-semibold">Pair this screen with the buyer</h1>
      <p className="mb-4 text-sm text-muted">
        Enter the pairing code from the demo operator. Sellers can never pair.
      </p>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          try {
            await pair({ buyerId: DEMO_BUYER, code: code.trim() });
            setTried(true);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Pairing failed");
          }
        }}
      >
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          inputMode="numeric"
          placeholder="6-digit code"
          className="flex-1 min-h-11 rounded-lg border border-line bg-soft px-3 py-2 font-mono"
        />
        <button className="min-h-11 rounded-lg bg-accent px-4 py-2 font-medium text-accent-ink">Pair</button>
      </form>
      {error && <p className="mt-3 text-sm text-coral">{error}</p>}
      {!error && tried && failures > 0 && (
        <p className="mt-3 text-sm text-coral">
          {failures >= PAIR_MAX_FAILURES
            ? "Too many wrong codes. This screen is locked; ask the operator for a new code."
            : `That code did not match. ${PAIR_MAX_FAILURES - failures} tries left before pairing locks.`}
        </p>
      )}
    </section>
  );
}

export default function BuyerPage() {
  return (
    <>
      <BuyerGate />
      <AgentsTile />
    </>
  );
}

function BuyerGate() {
  const conn = useSpacetimeDB();
  const [roles, rolesReady] = useTable(tables.myRole);
  const isBuyer = roles.some((r) => r.role === "buyer" && r.subjectId === DEMO_BUYER);
  if (!conn.isActive || !rolesReady) return <p className="text-muted">Connecting to the market...</p>;
  if (!isBuyer) return <PairScreen />;
  return <BuyerView />;
}

function BuyerView() {
  const [goals, goalsReady] = useTable(tables.myGoals);
  const [goalItems, goalItemsReady] = useTable(tables.myGoalItems);
  const [allowances, allowancesReady] = useTable(tables.myAllowance);
  const [results, resultsReady] = useTable(tables.roundResult);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [notes, notesReady] = useTable(tables.myNotifications);
  const [purchaseRows, purchaseReady] = useTable(tables.myPurchaseStatus);
  const [reviewRows, reviewsReady] = useTable(tables.myBidReviews);
  const [buyerRounds, buyerRoundsReady] = useTable(tables.myBuyerRounds);
  const [stepEvents, stepEventsReady] = useTable(tables.myGoalStepEvents);
  const [clock, setClock] = useState(() => Date.now());
  const [profiles, profilesReady] = useTable(tables.myBuyerProfile);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const goalRow = useMemo(() => goalsReady ? latestGoal(goals) : undefined, [goals, goalsReady]);
  const goal = useMemo(() => goalsReady && goalItemsReady && allowancesReady ? goalFromRows(goals, goalItems, allowances[0]) : null,
    [goals, goalItems, allowances, goalsReady, goalItemsReady, allowancesReady]);
  const buyerRound = useMemo(() => goalRow && buyerRoundsReady ? selectBuyerRound(buyerRounds, goalRow.id) : null, [buyerRounds, buyerRoundsReady, goalRow]);
  const liveBids = useMemo(() => resultsReady && eventsReady ? bidsFromRows(results, events, buyerRound?.roundId) : [],
    [results, resultsReady, events, eventsReady, buyerRound]);
  const { veto, shield } = useMemo(() => goalRow && buyerRound && reviewsReady
    ? reviewsFromRows(reviewRows, goalRow.id, buyerRound.roundId)
    : { veto: null, shield: null }, [reviewRows, reviewsReady, goalRow, buyerRound]);
  const purchase = useMemo(() => goalRow && purchaseReady ? purchaseFromRows(purchaseRows, goalRow.id, clock) : null,
    [purchaseRows, purchaseReady, goalRow, clock]);
  const feed = useMemo(() => goalRow && stepEventsReady && notesReady
    ? buyerFeedFromRows(stepEvents, notes, goalRow.id)
    : [], [goalRow, stepEvents, stepEventsReady, notes, notesReady]);

  return (
    <BuyerScreen
      connecting={!goalsReady || !goalItemsReady || !allowancesReady || !resultsReady || !eventsReady || !notesReady || !purchaseReady || !reviewsReady || !buyerRoundsReady || !stepEventsReady || !profilesReady}
      goal={goal}
      bids={liveBids}
      veto={veto}
      shield={shield}
      approval={null}
      purchase={purchase}
      receipt={purchase?.receipt ?? null}
      feed={feed}
      buyerName={profiles[0]?.displayName || DEMO_BUYER}
    />
  );
}
