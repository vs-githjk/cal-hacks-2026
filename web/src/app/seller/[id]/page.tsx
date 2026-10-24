"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { Card, Code, Label, OriginChip, Pill, SourceLink, clock } from "@/components/ui";
import { toDate } from "@/lib/stdb";

const BAND: Record<string, string> = { within5: "within 5%", within10: "within 10%", within20: "within 20%", over20: "over 20%" };
// Matches PAIR_MAX_FAILURES in market/spacetimedb/src/market.ts.
const PAIR_MAX_FAILURES = 5;

/** One seller's screen. The pooled lot is public (aggregate only); loss reports need this screen paired to the seller. */
export default function SellerPage() {
  const { id } = useParams<{ id: string }>();
  const conn = useSpacetimeDB();
  const [personas] = useTable(tables.persona);
  const [roles, rolesReady] = useTable(tables.myRole);
  const persona = personas.find((p) => p.sellerId === id);
  const paired = roles.some((r) => (r.role === "seller_screen" || r.role === "seller") && r.subjectId === id);

  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="text-[18px] font-bold tracking-[-0.01em]">
          Seller <span className="font-medium text-muted">{persona?.name ?? id}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[14px] text-muted">
          {persona && <span>{persona.archetype}</span>}
          <OriginChip origin={persona?.origin ?? "SIM"} label={`${persona?.origin === "LIVE" || persona?.origin === "MIRROR" ? persona.origin : "SIM"} seller agent`} />
          {paired && <Pill tone="done">Paired</Pill>}
        </div>
      </div>
      {!conn.isActive || !rolesReady ? (
        <p className="text-muted">Connecting to the market...</p>
      ) : (
        <>
          <PooledLot />
          {paired ? <LossReports sellerId={id} /> : <SellerPair sellerId={id} />}
        </>
      )}
    </div>
  );
}

function PooledLot() {
  const [needs] = useTable(tables.sellerNeeds);
  return (
    <Card>
      <Label>Pooled lot · what sellers see</Label>
      {needs.length === 0 ? (
        <p className="text-muted">No open request right now. When a buyer posts a need, it shows here as SKU, quantity, ceiling band and deadline only.</p>
      ) : (
        <div className="-mx-[18px] overflow-x-auto px-[18px]">
          <table className="w-full border-collapse text-[14px] tabular-nums">
            <thead>
              <tr>
                <Th>SKU</Th><Th>Quantity</Th><Th>Ceiling band</Th><Th>Deadline</Th>
              </tr>
            </thead>
            <tbody>
              {needs.map((n) => (
                <tr key={`${n.roundId}-${n.skuSpec}`}>
                  <Td><Code>{n.skuSpec}</Code> <OriginChip origin={n.origin} /></Td>
                  <Td>{n.quantity} {n.unit} <OriginChip origin={n.origin} /></Td>
                  <Td>{n.ceilingBand} <OriginChip origin={n.origin} /></Td>
                  <Td>{clock(toDate(n.deadline))} <OriginChip origin={n.origin} /></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2.5 text-[13px] text-muted">Never a buyer name, goal text or exact ceiling.</p>
    </Card>
  );
}

function LossReports({ sellerId }: { sellerId: string }) {
  const [reports] = useTable(tables.myLossReports);
  const mine = [...reports].filter((r) => r.sellerId === sellerId).sort((a, b) => (a.createdAt.microsSinceUnixEpoch < b.createdAt.microsSinceUnixEpoch ? 1 : -1));
  const learned = mine.find((r) => r.strategyDiff.length > 0 || r.whatToChange);
  return (
    <div className="grid gap-3.5 lg:grid-cols-2">
      <Card>
        <Label>Your loss reports</Label>
        {mine.length === 0 ? (
          <p className="text-muted">No reports yet. After each round you lose, the gap band, the reason and its source show here.</p>
        ) : (
          <div className="-mx-[18px] overflow-x-auto px-[18px]">
            <table className="w-full border-collapse text-[14px]">
              <thead>
                <tr><Th>Round</Th><Th>Gap</Th><Th>Reason</Th><Th>Source</Th></tr>
              </thead>
              <tbody>
                {mine.map((r) => (
                  <tr key={r.id}>
                    <Td className="font-mono text-[13px]">{r.roundId} {r.won && <Pill tone="done">Won</Pill>}</Td>
                    <Td>
                      <span className="rounded-md bg-slate-soft px-1.5 py-0.5 font-mono text-[11px] text-slate">{BAND[r.gapBand] ?? r.gapBand}</span>{" "}
                      <OriginChip origin={r.origin} />
                    </Td>
                    <Td>{r.reason.replaceAll("_", " ")}</Td>
                    <Td>{r.sourceUrl ? <SourceLink href={r.sourceUrl} /> : <span className="text-muted">none</span>}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card>
        <Label>What to change</Label>
        {!learned ? (
          <p className="text-muted">No strategy change yet. When your agent updates its strategy after a loss, the diff and the one line for you show here.</p>
        ) : (
          <>
            {learned.whatToChange && (
              <div className="rounded-xl border-l-[3px] border-accent bg-soft px-3.5 py-3 text-[15px]">
                &ldquo;{learned.whatToChange}&rdquo;
                <small className="mt-1 block text-[12px] text-muted">
                  Claude&apos;s one line to the owner ({learned.whatToChangeOrigin || "origin not stated"}) <OriginChip origin={learned.origin} />
                </small>
              </div>
            )}
            {learned.strategyDiff.length > 0 && (
              <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 font-mono text-[13px]">
                {learned.strategyDiff.map((d) => (
                  <div key={d.key} className="contents">
                    <dt className="text-muted">{d.key}</dt>
                    <dd>
                      <span className="text-coral line-through">{d.from}</span> → <span className="font-semibold text-mint">{d.to}</span> <OriginChip origin={learned.origin} />
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="mt-2.5 text-[13px] text-muted">From round {learned.roundId}. One deterministic, replayable diff. No trend claim.</p>
          </>
        )}
      </Card>
    </div>
  );
}

function SellerPair({ sellerId }: { sellerId: string }) {
  const pair = useReducer(reducers.pairSellerScreen);
  const [attempts] = useTable(tables.myPairAttempts);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [tried, setTried] = useState(false);
  const failures = attempts[0]?.failures ?? 0;
  return (
    <Card>
      <Label>Your loss reports</Label>
      <p className="mb-3 text-[14px] text-muted">Loss reports are private to this seller. Pair this screen with the seller code from the demo operator to see them. This screen can never bid.</p>
      <form
        className="flex max-w-md gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          try {
            await pair({ sellerId, code: code.trim() });
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
          className="min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-soft px-3 font-mono"
        />
        <button className="min-h-11 rounded-lg bg-accent px-4 font-medium text-accent-ink">Pair</button>
      </form>
      {error && <p className="mt-3 text-[13px] text-coral">{error}</p>}
      {!error && tried && failures > 0 && (
        <p className="mt-3 text-[13px] text-coral">
          {failures >= PAIR_MAX_FAILURES ? "Too many wrong codes. Ask the operator for a new code." : `That code did not match. ${PAIR_MAX_FAILURES - failures} tries left.`}
        </p>
      )}
    </Card>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="whitespace-nowrap border-b border-line px-2.5 pb-2 pt-1.5 text-left text-[12px] font-semibold uppercase tracking-[0.06em] text-muted">{children}</th>;
}
function Td({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <td className={`border-b border-line p-2.5 align-top ${className}`}>{children}</td>;
}
