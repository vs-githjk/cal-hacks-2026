"use client";

import { useEffect, useMemo, useState } from "react";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { Floor3D, hasWebGL, type FloorRow } from "@/components/Floor3D";
import { Card, Code, Label, OriginChip, clock } from "@/components/ui";
import { FIXED_ACTORS, MAX_SELLERS, actorFor, type Actor } from "@/lib/floor";
import { asOrigin } from "@/lib/screens";
import { toDate } from "@/lib/stdb";

/** The market floor in 3D. Every motion is a floor_event row; click a character to see the row that moved it last. */
export default function FloorPage() {
  const conn = useSpacetimeDB();
  const [events, eventsReady] = useTable(tables.floorEvent);
  const [personas] = useTable(tables.persona);
  const [picked, setPicked] = useState<string | null>(null);
  const [webgl, setWebgl] = useState<boolean | null>(null);
  useEffect(() => setWebgl(hasWebGL()), []);

  const actors = useMemo<Actor[]>(
    () => [
      ...FIXED_ACTORS,
      ...[...personas]
        .sort((a, b) => a.sellerId.localeCompare(b.sellerId))
        .slice(0, MAX_SELLERS)
        .map((p): Actor => ({ key: `seller:${p.sellerId}`, name: p.name, kind: "seller", origin: asOrigin(p.origin) })),
    ],
    [personas],
  );
  const rows = useMemo<FloorRow[]>(() => {
    const sellers = new Set(personas.map((p) => p.sellerId));
    return [...events]
      .sort((a, b) => (a.id < b.id ? 1 : -1))
      .map((e) => ({ id: String(e.id), actor: actorFor(e, sellers), kind: e.kind, label: e.label, origin: e.origin, at: toDate(e.at), ref: `${e.refTable}/${e.refId}` }));
  }, [events, personas]);
  const lastRow = (key: string) => rows.find((r) => r.actor === key);
  // "Connecting..." until the first connect; "disconnected" only after a live connection drops.
  const [everActive, setEverActive] = useState(false);
  useEffect(() => {
    if (conn.isActive) setEverActive(true);
  }, [conn.isActive]);
  const disconnected = !conn.isActive;
  const sel = picked ? actors.find((a) => a.key === picked) : undefined;
  const selRow = picked ? lastRow(picked) : undefined;

  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3.5">
        <div className="text-[18px] font-bold tracking-[-0.01em]">
          Floor <span className="font-medium text-muted">every motion is a market row</span>
        </div>
        <div className="text-[14px] text-muted">{rows.length} rows · {actors.length} characters</div>
      </div>
      <div className="grid gap-3.5 lg:grid-cols-[8fr_4fr]">
        <div className="relative min-w-0">
          {webgl === false ? (
            <ActorList actors={actors} lastRow={lastRow} onPick={setPicked} />
          ) : webgl ? (
            <Floor3D actors={actors} rows={rows} frozen={disconnected} onPick={setPicked} />
          ) : (
            <p className="text-muted">Loading the floor...</p>
          )}
          {disconnected && (
            <div className="absolute inset-0 grid place-items-center rounded-[var(--radius)] bg-canvas/70">
              {everActive ? (
                <span className="rounded-lg bg-coral-soft px-3 py-2 font-semibold text-coral">market disconnected · the floor is still</span>
              ) : (
                <span className="rounded-lg bg-soft px-3 py-2 font-semibold text-muted">Connecting...</span>
              )}
            </div>
          )}
        </div>
        <Card>
          <Label>{sel ? sel.name : "Pick a character"}</Label>
          {!sel ? (
            <p className="text-muted">Click a character to see the floor_event row that last moved it.</p>
          ) : !selRow ? (
            <p className="text-muted">No row yet, so it has not moved.</p>
          ) : (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[14px]">
              <dt className="text-muted">Row</dt><dd><Code>floor_event/{selRow.id}</Code></dd>
              <dt className="text-muted">Kind</dt><dd className="font-mono text-[13px]">{selRow.kind}</dd>
              <dt className="text-muted">Label</dt><dd>{selRow.label} <OriginChip origin={selRow.origin} /></dd>
              <dt className="text-muted">At</dt><dd className="font-mono text-[13px]">{clock(selRow.at)}</dd>
              <dt className="text-muted">Ref</dt><dd className="font-mono text-[13px] [overflow-wrap:anywhere]">{selRow.ref}</dd>
            </dl>
          )}
          {!eventsReady && <p className="mt-2 text-muted">Connecting to the market...</p>}
        </Card>
      </div>
      {webgl && <ActorList actors={actors} lastRow={lastRow} onPick={setPicked} compact />}
    </div>
  );
}

/** The 2D fallback without WebGL, and the legend under the 3D floor. */
function ActorList({ actors, lastRow, onPick, compact }: { actors: Actor[]; lastRow: (k: string) => FloorRow | undefined; onPick: (k: string) => void; compact?: boolean }) {
  return (
    <Card>
      <Label>{compact ? "Characters" : "Floor (2D, this browser has no WebGL)"}</Label>
      <ul className="grid gap-1 sm:grid-cols-2">
        {actors.map((a) => {
          const r = lastRow(a.key);
          return (
            <li key={a.key}>
              <button onClick={() => onPick(a.key)} className="grid min-h-11 w-full grid-cols-[1fr_auto] items-baseline gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-soft">
                <span className="min-w-0">
                  <b className="font-semibold">{a.name}</b> <OriginChip origin={a.origin} />
                  <span className="block truncate text-[13px] text-muted">{r ? `${r.kind}: ${r.label}` : "no row yet"}</span>
                </span>
                <span className="font-mono text-[12px] text-muted">{r ? clock(r.at) : ""}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
