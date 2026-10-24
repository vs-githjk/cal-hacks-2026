"use client";

import { useEffect, useMemo, useState } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { AgentsTile } from "@/components/AgentsTile";
import { BuyerScreen } from "@/components/screens";
import { asSim, bidsFromRows, feedFromRows, goalFromRows, latestRound, reviewFromRows } from "@/lib/screens";
import * as sample from "@/lib/sample";

// Demo sign-in: the buyer is fixed to Vidyut. Real sign-in replaces this.
const DEMO_BUYER = "vidyut";
// Matches PAIR_MAX_FAILURES in market/spacetimedb/src/market.ts.
const PAIR_MAX_FAILURES = 5;

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
  const [goalItems] = useTable(tables.myGoalItems);
  const [allowances] = useTable(tables.myAllowance);
  const [rounds] = useTable(tables.round);
  const [results] = useTable(tables.roundResult);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [notes] = useTable(tables.myNotifications);
  const [pending] = useTable(tables.myPendingApprovals);
  const [clock, setClock] = useState(() => Date.now());
  const [profiles] = useTable(tables.myBuyerProfile);
  const approveTyped = useReducer(reducers.approveTyped);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const goal = useMemo(() => goalFromRows(goals, goalItems, allowances[0]), [goals, goalItems, allowances]);
  const liveBids = useMemo(() => bidsFromRows(results, events, latestRound(rounds)?.id), [results, events, rounds]);
  const feed = useMemo(() => feedFromRows(events, notes), [events, notes]);
  const sim = liveBids.length === 0;
  const review = useMemo(() => reviewFromRows(pending), [pending, clock]);
  // A wrong code is counted in my_pending_approvals (failures); a match records the approval and the row leaves the view.
  const onTyped = async (mandateHash: string, code: string) => {
    if (!code) return "Type the two words shown above.";
    try {
      await approveTyped({ mandateHash, code });
      return "Sent. If it matched, this card turns into the receipt.";
    } catch (err) {
      return err instanceof Error ? err.message : "Approval failed";
    }
  };

  // veto, shield, approval and receipt rows (bid_check, mandate, approval, payment) are not public yet: those cards show the SIM sample.
  return (
    <BuyerScreen
      connecting={!goalsReady || !eventsReady}
      goal={goal}
      bids={sim ? asSim(sample.rankedBids) : liveBids}
      veto={asSim(sample.veto)}
      shield={asSim(sample.shield)}
      approval={asSim(sample.approval)}
      review={review}
      onTyped={onTyped}
      receipt={asSim(sample.receipt)}
      feed={feed}
      buyerName={profiles[0]?.displayName || DEMO_BUYER}
      sample={{ bids: sim, veto: true, shield: true, approval: !review, receipt: true }}
    />
  );
}
