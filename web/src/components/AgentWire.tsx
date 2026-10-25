"use client";
// Who talks to whom: every seller line runs through the Smell Test (Shield) before it reaches the buyer. A line lights only when a real
// agent_event row lands after the page loaded (lib/wire.ts); the rows already in the table at load never replay. Nothing
// here is simulated, and with reduced motion the line lights without a travelling dot.

import { useEffect, useRef, useState } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { advance, displayNameFor, edgeForAgent, type EdgeId } from "@/lib/wire";
import { SHIELD } from "@/lib/brand";
import { OriginChip } from "./ui";

const EDGES: Record<EdgeId, { d: string; label: string }> = {
  "sellers-shield": { d: "M170 120 L300 120", label: `Seller bids go to ${SHIELD} first` },
  "shield-buyer": { d: "M430 120 L560 80", label: `${SHIELD} passes clean listings to the buyer` },
  "buyer-advocate": { d: "M620 110 L620 170", label: "The buyer asks the advocate" },
};
const LIT_MS = 2500;

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function AgentWire() {
  const [rows, ready] = useTable(tables.agentEvent);
  const seen = useRef<bigint | null>(null);
  const [lit, setLit] = useState<{ edge: EdgeId; key: bigint } | null>(null);
  const [last, setLast] = useState<{ name: string; text: string; origin: string } | null>(null);
  const [still] = useState(reduced);

  useEffect(() => {
    const { seen: next, fresh } = advance(seen.current, rows, ready);
    seen.current = next;
    const newest = fresh[fresh.length - 1];
    if (!newest) return;
    const edge = edgeForAgent(newest.agentName);
    const t = setTimeout(() => {
      setLast({ name: displayNameFor(newest.agentName), text: newest.text, origin: newest.origin });
      if (edge) setLit({ edge, key: newest.id });
    }, 0);
    const off = setTimeout(() => setLit((l) => (l && l.key === newest.id ? null : l)), LIT_MS);
    return () => {
      clearTimeout(t);
      clearTimeout(off);
    };
  }, [rows, ready]);

  const node = (x: number, y: number, w: number, name: string, sub: string, hub = false) => (
    <g>
      <rect x={x} y={y} width={w} height={60} rx={12} className={`fill-surface-2 ${hub ? "stroke-pulse" : "stroke-line-2"}`} strokeWidth={hub ? 1.5 : 1} />
      <text x={x + w / 2} y={y + 27} textAnchor="middle" className="fill-ink text-[13px] font-semibold">{name}</text>
      <text x={x + w / 2} y={y + 45} textAnchor="middle" className="fill-muted font-mono text-[10.5px]">{sub}</text>
    </g>
  );

  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface shadow-card">
      <div className="overflow-x-auto">
        <svg viewBox="0 0 760 240" className="block h-auto w-full min-w-[640px]" role="img" aria-label={`Seller agents send bids through ${SHIELD} to the buyer, which asks the advocate. A line lights when an agent message arrives.`}>
          {(Object.keys(EDGES) as EdgeId[]).map((id) => (
            <path key={id} d={EDGES[id].d} fill="none" strokeWidth={1.5} className={`transition-colors motion-reduce:transition-none ${lit?.edge === id ? "stroke-pulse" : "stroke-line-2"}`} />
          ))}
          {lit && !still && (
            <circle key={String(lit.key)} r={5} className="fill-pulse">
              <animateMotion dur="1.2s" repeatCount="1" path={EDGES[lit.edge].d} />
            </circle>
          )}
          {node(20, 90, 150, "Sellers", "sealed bids")}
          {node(300, 90, 130, SHIELD, "checks every page", true)}
          {node(560, 50, 150, "Buyer", "hunts and ranks")}
          {node(560, 170, 150, "Advocate", "vetoes with a source")}
        </svg>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-line px-3.5 py-3 text-[13px]" aria-live="polite">
        {last ? (
          <>
            <OriginChip origin={last.origin} />
            <span className="min-w-0 flex-1 break-words"><b className="font-semibold">{last.name}:</b> {last.text}</span>
          </>
        ) : (
          <span className="text-muted">No agent messages yet. A line lights here when one arrives; nothing on this diagram is replayed. {rows.length > 0 ? `${rows.length} earlier ${rows.length === 1 ? "message is" : "messages are"} recorded.` : ""}</span>
        )}
      </div>
    </div>
  );
}
