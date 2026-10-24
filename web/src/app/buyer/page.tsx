"use client";

import { useMemo, useState } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { BuyerScreen } from "@/components/screens";
import { asSim, bidsFromRows, dealFromRows, feedFromRows, goalFromRows, latestRound, reviewFromRows, shieldFromRows, vetoFromRows } from "@/lib/screens";
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
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          placeholder="XXXXX-XXXXX"
          className="flex-1 min-h-11 rounded-lg border border-line bg-soft px-3 py-2 font-mono uppercase placeholder:normal-case"
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
  return <BuyerGate />;
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
  const [profiles] = useTable(tables.myBuyerProfile);
  const [checks] = useTable(tables.myBidChecks);
  const [deals] = useTable(tables.myDeals);

  const goal = useMemo(() => goalFromRows(goals, goalItems, allowances[0]), [goals, goalItems, allowances]);
  const liveBids = useMemo(() => bidsFromRows(results, events, latestRound(rounds)?.id), [results, events, rounds]);
  const feed = useMemo(() => feedFromRows(events, notes), [events, notes]);
  const sim = liveBids.length === 0;
  const review = useMemo(() => reviewFromRows(pending), [pending]);
  const roundId = latestRound(rounds)?.id;
  const veto = useMemo(() => vetoFromRows(checks, results, roundId), [checks, results, roundId]);
  const shield = useMemo(() => shieldFromRows(checks, roundId), [checks, roundId]);
  const deal = useMemo(() => dealFromRows(deals, goal?.allowance?.perPurchase ?? null, results), [deals, goal, results]);
  const closeKey = useMemo(() => events.filter((e) => e.kind === "auction_closed").reduce<string | undefined>((k, e) => (k === undefined || BigInt(k) < e.id ? String(e.id) : k), undefined), [events]);
  // #191-5: veto, Shield, approval and receipt come from my_bid_checks and my_deals; a card shows the SIM sample only while its row is missing.
  return (
    <BuyerScreen
      connecting={!goalsReady || !eventsReady}
      goal={goal}
      bids={sim ? asSim(sample.rankedBids) : liveBids}
      veto={veto ?? asSim(sample.veto)}
      shield={shield ?? asSim(sample.shield)}
      approval={deal.approval ?? asSim(sample.approval)}
      review={review}
      receipt={deal.receipt ?? asSim(sample.receipt)}
      feed={feed}
      buyerName={profiles[0]?.displayName || "Buyer"}
      revealKey={closeKey}
      sample={{ bids: sim, veto: !veto, shield: !shield, approval: !review && !deal.approval, receipt: !deal.receipt }}
    />
  );
}
