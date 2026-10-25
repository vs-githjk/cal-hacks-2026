"use client";
// The private boundary for every /buyer route. Children render only once the market's own my_role row says this
// screen is paired as one buyer; the buyer id is read from that row, never from the URL or local state.
// Switching buyers remounts everything below (key), so no private row, draft or pending request outlives the identity it belonged to.

import { createContext, useContext, useState, type ReactNode } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { buyerSession } from "@/lib/screens";
import { GoalComposer } from "./GoalComposer";

// Demo pairing: the screen pairs as Vidyut with the operator's code (SIM sign-in). A real account system replaces this.
const DEMO_BUYER = "vidyut";
// Matches PAIR_MAX_FAILURES in market/spacetimedb/src/market.ts.
const PAIR_MAX_FAILURES = 5;

const BuyerIdContext = createContext<string | null>(null);

/** The paired buyer's id. Only callable below BuyerGate, so it is never empty. */
export function useBuyerId(): string {
  const id = useContext(BuyerIdContext);
  if (!id) throw new Error("useBuyerId must be used inside BuyerGate");
  return id;
}

/** A screen sees the buyer's goals only after pairing with the demo code (SIM sign-in). */
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
          aria-label="Pairing code"
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

export function BuyerGate({ children }: { children: ReactNode }) {
  const conn = useSpacetimeDB();
  const [roles, rolesReady] = useTable(tables.myRole);
  const session = buyerSession(conn.isActive, rolesReady, roles);
  if (session.status === "connecting") return <p className="text-muted">Connecting to the market...</p>;
  if (session.status === "unpaired") {
    return (
      <div className="grid gap-3.5">
        <GoalComposer buyerId={null} />
        <PairScreen />
      </div>
    );
  }
  return (
    <BuyerIdContext.Provider key={session.buyerId} value={session.buyerId}>
      {children}
    </BuyerIdContext.Provider>
  );
}
