"use client";

import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { OriginBadge } from "@/components/OriginBadge";
import { fmtMoney, fmtTime } from "@/lib/stdb";

/** Raw public market state: what every screen and the floor draw from. */
export default function MarketPage() {
  const [rounds, roundsReady] = useTable(tables.round);
  const [results] = useTable(tables.roundResult);
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [rejected] = useTable(tables.rejectedAttempt);

  const sortedEvents = [...events].sort((a, b) => (a.id < b.id ? 1 : -1));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Market state</h1>
        <span className="text-xs text-[var(--muted)]">Reset: the demo operator runs reset_demo then seed_demo</span>
      </div>

      <section className="panel p-5">
        <h2 className="mb-3 font-semibold">Rounds</h2>
        {!roundsReady ? (
          <p className="text-[var(--muted)]">Connecting...</p>
        ) : rounds.length === 0 ? (
          <p className="text-[var(--muted)]">No rounds yet.</p>
        ) : (
          <div className="space-y-4">
            {rounds.map((r) => {
              const rows = results.filter((x) => x.roundId === r.id).sort((a, b) => (a.rank || 99) - (b.rank || 99));
              return (
                <div key={r.id} className="rounded-lg bg-[var(--bg)] p-3">
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <span className="font-mono">{r.id}</span>
                    <span className="font-semibold">{r.state === "open" ? `sealed, ${r.sealedCount} bid(s)` : "closed"}</span>
                    <span className="text-[var(--muted)]">deadline {fmtTime(r.deadline)}</span>
                    {r.extensions > 0 && <span className="text-[var(--muted)]">extended {r.extensions}x</span>}
                    <OriginBadge origin={r.origin} />
                  </div>
                  {rows.length > 0 && (
                    <table className="mt-2 w-full text-sm">
                      <tbody>
                        {rows.map((x) => (
                          <tr key={String(x.id)} className="border-t border-[var(--line)]">
                            <td className="py-1 pr-3 font-semibold">{x.rank ? `#${x.rank}` : "out"}</td>
                            <td className="pr-3">{x.persona || x.sellerId}</td>
                            <td className="pr-3">{fmtMoney(x.landed)}</td>
                            <td className="pr-3 text-[var(--muted)]">
                              {(x.rank ? "picked " : "offered ") +
                                x.lines.map((l) => `${l.offeredCondition || "as asked"} at ${fmtMoney(l.unitPrice)}`).join(", ")}
                            </td>
                            <td className="pr-3 text-rose-700 dark:text-rose-300">{x.reasons.join("; ")}</td>
                            <td>
                              <OriginBadge origin={x.origin} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {rejected.length > 0 && (
        <section className="panel p-5">
          <h2 className="mb-3 font-semibold">Refused attempts</h2>
          <ul className="space-y-1 text-sm">
            {rejected.map((r) => (
              <li key={String(r.id)}>
                <span className="font-mono text-xs text-[var(--muted)]">{fmtTime(r.at)}</span> {r.kind}: {r.reason}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel p-5">
        <h2 className="mb-3 font-semibold">Floor events</h2>
        {!eventsReady ? (
          <p className="text-[var(--muted)]">Connecting...</p>
        ) : sortedEvents.length === 0 ? (
          <p className="text-[var(--muted)]">No events yet.</p>
        ) : (
          <ol className="space-y-1 font-mono text-xs">
            {sortedEvents.slice(0, 60).map((e) => (
              <li key={String(e.id)} className="flex gap-3">
                <span className="text-[var(--muted)]">{fmtTime(e.at)}</span>
                <span className="w-36 shrink-0">{e.kind}</span>
                <span className="flex-1 font-sans">{e.label}</span>
                <span className="text-[var(--muted)]">
                  {e.refTable}/{e.refId}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
