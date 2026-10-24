"use client";

import { useMemo, useState } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { OriginBadge } from "@/components/OriginBadge";
import { fmtMoney, fmtTime, toDate } from "@/lib/stdb";

// Demo sign-in: the buyer is fixed to Vidyut. Real sign-in replaces this.
const DEMO_BUYER = "vidyut";

const GOAL_TYPE: Record<string, string> = {
  budget_cap: "Budget cap",
  part_by_date: "Part by date",
  build_by_date: "Build by date",
};

const STATE_STYLE: Record<string, string> = {
  ACTIVE: "bg-emerald-600",
  HUNTING: "bg-indigo-600",
  HOLD_FOR_CALL: "bg-amber-500",
  DONE: "bg-slate-500",
  EXPIRED: "bg-rose-600",
  PAUSED: "bg-slate-400",
};

type FeedClass = "deal found" | "bid in" | "veto" | "progress";

function classify(kind: string, label: string): FeedClass | null {
  if (kind === "bid_sealed") return "bid in";
  if (kind === "auction_closed") return label.includes("no eligible") ? "progress" : "deal found";
  if (kind === "bid_rejected" || (kind === "verdict" && !label.endsWith("allow")) || (kind === "claim_checked" && label.endsWith("false")))
    return "veto";
  if (["goal_posted", "goal_state", "need_posted", "round_opened", "approval_recorded", "payment_recorded", "mandate_created"].includes(kind))
    return "progress";
  return null;
}

const CLASS_STYLE: Record<FeedClass, string> = {
  "deal found": "text-emerald-700 dark:text-emerald-300",
  "bid in": "text-indigo-700 dark:text-indigo-300",
  veto: "text-rose-700 dark:text-rose-300",
  progress: "text-[var(--muted)]",
};

/** A screen sees Vidyut's goal only after pairing with the demo code (SIM sign-in). */
function PairScreen() {
  const pair = useReducer(reducers.pairBuyerScreen);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  return (
    <section className="panel mx-auto max-w-md p-6">
      <h1 className="mb-2 text-lg font-semibold">Pair this screen with Vidyut</h1>
      <p className="mb-4 text-sm text-[var(--muted)]">
        Enter the pairing code from the demo operator. Sellers can never pair.
      </p>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          try {
            await pair({ buyerId: DEMO_BUYER, code: code.trim() });
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
          className="flex-1 rounded-lg border border-[var(--line)] bg-[var(--bg)] px-3 py-2 font-mono"
        />
        <button className="rounded-lg bg-[var(--accent)] px-4 py-2 font-medium text-white">Pair</button>
      </form>
      {error && <p className="mt-3 text-sm text-rose-700 dark:text-rose-300">{error}</p>}
    </section>
  );
}

export default function BuyerPage() {
  const conn = useSpacetimeDB();
  const [roles, rolesReady] = useTable(tables.myRole);
  const isBuyer = roles.some((r) => r.role === "buyer" && r.subjectId === DEMO_BUYER);
  if (!conn.isActive || !rolesReady) return <p className="text-[var(--muted)]">Connecting to the market...</p>;
  if (!isBuyer) return <PairScreen />;
  return <BuyerScreen />;
}

function BuyerScreen() {
  const [goals, goalsReady] = useTable(tables.myGoals);
  const [goalItems] = useTable(tables.myGoalItems);
  const [notes] = useTable(tables.myNotifications);
  const [allowances] = useTable(tables.myAllowance);
  const allowance = allowances[0];
  const [events, eventsReady] = useTable(tables.floorEvent);

  const feed = useMemo(() => {
    const fromEvents = events
      .map((e) => ({ key: `e${e.id}`, at: e.at, cls: classify(e.kind, e.label), text: e.label, origin: e.origin }))
      .filter((x): x is typeof x & { cls: FeedClass } => x.cls !== null);
    const fromNotes = notes.map((n) => ({ key: `n${n.id}`, at: n.at, cls: (n.klass === "veto" ? "veto" : "progress") as FeedClass, text: n.text, origin: "SIM" }));
    return [...fromEvents, ...fromNotes].sort((a, b) => (a.at.microsSinceUnixEpoch < b.at.microsSinceUnixEpoch ? 1 : -1));
  }, [events, notes]);

  const goal = [...goals].sort((a, b) => (a.createdAt.microsSinceUnixEpoch < b.createdAt.microsSinceUnixEpoch ? 1 : -1))[0];
  const items = goal ? goalItems.filter((i) => i.goalId === goal.id) : [];

  return (
    <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
      <section className="panel p-5">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-lg font-semibold">Goal</h1>
          <span className="text-xs text-[var(--muted)]">Buyer: Vidyut</span>
        </div>

        {!goalsReady ? (
          <p className="text-[var(--muted)]">Connecting to the market...</p>
        ) : !goal ? (
          <p className="text-[var(--muted)]">No goal yet. Tell the agent what you want and it will appear here.</p>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded px-2 py-0.5 text-xs font-semibold text-white ${STATE_STYLE[goal.state] ?? "bg-slate-500"}`}>
                {goal.state.replaceAll("_", " ")}
              </span>
              <span className="text-sm text-[var(--muted)]">{GOAL_TYPE[goal.type] ?? goal.type}</span>
              <OriginBadge origin={goal.origin} />
            </div>
            {items.length > 0 && (
              <ul className="space-y-2">
                {items.map((i) => (
                  <li key={String(i.id)} className="flex flex-wrap items-baseline gap-2">
                    <span className="text-xl font-medium">{i.quantity > 1 ? `${i.quantity} x ` : ""}{i.skuSpec}</span>
                    <span className="rounded bg-[var(--bg)] px-1.5 py-0.5 text-xs">{i.condition}</span>
                    {i.variant && <span className="rounded bg-[var(--bg)] px-1.5 py-0.5 text-xs">{i.variant}</span>}
                    {i.skippedOwnedPartId && (
                      <span className="text-xs text-[var(--muted)]">skipped, already owned ({i.skippedOwnedPartId})</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div className="rounded-lg bg-[var(--bg)] p-3">
                <dt className="text-[var(--muted)]">Cap</dt>
                <dd className="text-lg font-semibold">{fmtMoney(goal.cap)}</dd>
              </div>
              <div className="rounded-lg bg-[var(--bg)] p-3">
                <dt className="text-[var(--muted)]">Reserved</dt>
                <dd className="text-lg font-semibold">{fmtMoney(goal.reservedAmount)}</dd>
              </div>
              <div className="rounded-lg bg-[var(--bg)] p-3">
                <dt className="text-[var(--muted)]">Deadline</dt>
                <dd className="text-lg font-semibold">
                  {toDate(goal.deadline).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
                </dd>
              </div>
              <div className="rounded-lg bg-[var(--bg)] p-3">
                <dt className="text-[var(--muted)]">Allowance</dt>
                <dd className="text-lg font-semibold">{allowance ? fmtMoney(allowance.perPurchaseLimit) : fmtMoney(0)}</dd>
                <dd className="text-xs text-[var(--muted)]">
                  {allowance && allowance.perPurchaseLimit > 0
                    ? `per buy, step ${allowance.ladderStep}; ${fmtMoney(allowance.spentThisPeriod)} of ${fmtMoney(allowance.periodLimit)} this ${allowance.period}`
                    : "every buy calls you first"}
                </dd>
              </div>
            </dl>
            {goal.poNumber && <p className="text-sm text-[var(--muted)]">PO {goal.poNumber}</p>}
            <p className="rounded-lg border border-dashed border-[var(--line)] p-3 text-sm">
              Goal cap is the ceiling to hunt under. Allowance is what it may spend without a call.
            </p>
          </div>
        )}
      </section>

      <section className="panel p-5">
        <h2 className="mb-4 text-lg font-semibold">What the agent did</h2>
        {!eventsReady ? (
          <p className="text-[var(--muted)]">Connecting to the market...</p>
        ) : feed.length === 0 ? (
          <p className="text-[var(--muted)]">Nothing yet. Every step the agent takes shows up here.</p>
        ) : (
          <ol className="space-y-2">
            {feed.slice(0, 40).map((f) => (
              <li key={f.key} className="flex items-baseline gap-3 text-sm">
                <span className="w-20 shrink-0 font-mono text-xs text-[var(--muted)]">{fmtTime(f.at)}</span>
                <span className={`w-20 shrink-0 text-xs font-semibold uppercase ${CLASS_STYLE[f.cls]}`}>{f.cls}</span>
                <span className="flex-1">{f.text}</span>
                <OriginBadge origin={f.origin} />
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
