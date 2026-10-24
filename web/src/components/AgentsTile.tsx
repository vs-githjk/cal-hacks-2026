"use client";
// Fetch agents picture-in-picture: what each of the six Agentverse agents said last. Quiet by design.
// Rows come from agent_event (written by the agents' relay through record_agent_event); for the buyer, advocate and
// Shield a public floor_event of their kind fills in until they write one. With no agent_event rows at all, SIM samples.
import { useEffect, useMemo, useRef, useState } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { AGENTS, AGENTVERSE_URL, ASI_ONE_URL, nearestCorner, sampleRows, shortAddress, timeAgo, type AgentRow, type Corner } from "@/lib/agents";
import { asOrigin } from "@/lib/screens";
import { toDate } from "@/lib/stdb";
import { OriginChip } from "./ui";

const KEY = "tb_agents_tile_corner";
const FRESH_MS = 60_000;
const KIND_OF: Record<string, "buyer" | "advocate" | "shield"> = {
  goal_posted: "buyer", need_posted: "buyer", mandate_created: "buyer", approval_recorded: "buyer", advocate_card: "advocate", claim_checked: "advocate", verdict: "shield",
};

function readCorner(): Corner {
  try {
    const c = localStorage.getItem(KEY);
    return c === "tl" || c === "tr" || c === "bl" || c === "br" ? c : "br";
  } catch {
    return "br";
  }
}
function saveCorner(c: Corner) {
  try {
    localStorage.setItem(KEY, c);
  } catch {
    // Private window or blocked storage: the corner just is not remembered.
  }
}

const overlaps = (a: DOMRect, b: DOMRect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

export function AgentsTile() {
  const [agentEvents] = useTable(tables.agentEvent);
  const [floorEvents] = useTable(tables.floorEvent);
  const [now, setNow] = useState(() => new Date());
  const [open, setOpen] = useState(false);
  const [corner, setCorner] = useState<Corner>("br");
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const start = useRef<{ x: number; y: number; dx: number; dy: number; moved: boolean } | null>(null);
  const tile = useRef<HTMLDivElement>(null);

  useEffect(() => setCorner(readCorner()), []);
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 5000);
    return () => clearInterval(t);
  }, []);

  const sim = agentEvents.length === 0;
  const rows = useMemo<AgentRow[]>(() => {
    if (sim) return sampleRows(now);
    return AGENTS.map((agent) => {
      const own = agentEvents.filter((e) => e.address === agent.address).sort((a, b) => (a.ts.microsSinceUnixEpoch < b.ts.microsSinceUnixEpoch ? 1 : -1))[0];
      if (own) return { agent, text: own.text, at: toDate(own.ts), origin: asOrigin(own.origin) };
      const fe = [...floorEvents].filter((e) => KIND_OF[e.kind] === agent.key).sort((a, b) => (a.id < b.id ? 1 : -1))[0];
      if (fe) return { agent, text: fe.label, at: toDate(fe.at), origin: asOrigin(fe.origin) };
      return { agent, text: "no message yet", at: null, origin: "SIM" };
    });
    // now only matters for the sample rows' relative times
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim ? now : null, agentEvents, floorEvents]);
  // Green only for a real agent write (LIVE or MIRROR) in the last 60 s; a SIM row never lights it.
  const fresh = agentEvents.some((e) => asOrigin(e.origin) !== "SIM" && now.getTime() - toDate(e.ts).getTime() < FRESH_MS);

  // Never cover the hero number: if the tile sits over it, move to the other corner on the same side.
  useEffect(() => {
    const check = () => {
      const hero = document.querySelector("[data-hero]")?.getBoundingClientRect();
      const me = tile.current?.getBoundingClientRect();
      if (hero && me && overlaps(hero, me)) setCorner((c) => ((c[0] === "t" ? "b" : "t") + c[1]) as Corner);
    };
    check();
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    return () => {
      window.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
    };
  }, [corner, open]);

  const place: Record<Corner, string> = {
    tl: "sm:left-4 sm:top-[76px]",
    tr: "sm:right-4 sm:top-[76px]",
    bl: "sm:bottom-12 sm:left-4",
    br: "sm:bottom-12 sm:right-4",
  };

  const onDown = (e: React.PointerEvent) => {
    if (window.innerWidth < 640 || (e.target as HTMLElement).closest("a")) return;
    const r = tile.current!.getBoundingClientRect();
    start.current = { x: e.clientX, y: e.clientY, dx: e.clientX - r.left, dy: e.clientY - r.top, moved: false };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    const s = start.current;
    if (!s) return;
    if (!s.moved && Math.hypot(e.clientX - s.x, e.clientY - s.y) < 6) return;
    s.moved = true;
    setDrag({ x: e.clientX - s.dx, y: e.clientY - s.dy });
  };
  const onUp = (e: React.PointerEvent) => {
    const s = start.current;
    start.current = null;
    if (!s) return;
    if (!s.moved) return setOpen((o) => !o);
    const c = nearestCorner(e.clientX, e.clientY, window.innerWidth, window.innerHeight);
    setDrag(null);
    setCorner(c);
    saveCorner(c);
  };

  return (
    <div
      ref={tile}
      data-agents-tile
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      style={drag ? { left: drag.x, top: drag.y, right: "auto", bottom: "auto" } : undefined}
      className={`fixed inset-x-4 bottom-12 z-30 select-none overflow-hidden border border-line bg-panel/95 shadow-[0_6px_24px_rgba(0,0,0,0.12)] backdrop-blur sm:inset-x-auto ${drag ? "" : place[corner]} ${
        open ? "max-h-[60vh] rounded-[var(--radius)] sm:h-[320px] sm:max-h-none sm:w-[360px]" : "h-11 rounded-full sm:h-[120px] sm:w-[220px] sm:rounded-[var(--radius)]"
      } ${drag ? "cursor-grabbing" : "sm:cursor-grab"}`}
    >
      <button
        type="button"
        onClick={(e) => {
          if (window.innerWidth < 640) setOpen((o) => !o);
          e.preventDefault();
        }}
        aria-expanded={open}
        className="flex min-h-11 w-full items-center gap-2 px-3 text-left sm:min-h-0 sm:pt-2.5"
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${fresh ? "bg-mint" : "bg-slate opacity-50"}`} title={fresh ? "a real agent event in the last 60 s" : "no real agent event in the last 60 s"} aria-hidden />
        <span className="truncate text-[11px] font-semibold uppercase tracking-[0.05em] text-muted">Fetch agents · live on Agentverse</span>
        {sim && <span className="ml-auto shrink-0" title="sample rows until the agents write"><OriginChip origin="SIM" /></span>}
      </button>
      {!open ? (
        <ul className="hidden px-3 pb-2 pt-1 sm:grid sm:gap-0.5">
          {rows.slice(0, 3).map((r) => (
            <li key={r.agent.key} className="flex items-baseline gap-1.5 text-[12px]">
              <b className="shrink-0 font-semibold">{r.agent.name.split(" ")[0]}</b>
              <span className="min-w-0 truncate text-muted">{r.text}</span>
            </li>
          ))}
          <li className="text-[11px] text-muted">+{rows.length - 3} more · click to open</li>
        </ul>
      ) : (
        <div className="flex h-[calc(100%-44px)] flex-col sm:h-[calc(100%-32px)]">
          <ul className="min-h-0 flex-1 overflow-y-auto px-3 py-1">
            {rows.map((r) => (
              <li key={r.agent.key} className="border-b border-line py-1.5 last:border-b-0">
                <div className="flex items-baseline gap-1.5 text-[13px]">
                  <b className="min-w-0 truncate font-semibold">{r.agent.name}</b>
                  <span className="shrink-0 font-mono text-[11px] text-muted" title={r.agent.address}>{shortAddress(r.agent.address)}</span>
                  <span className="ml-auto shrink-0 font-mono text-[11px] text-muted">{timeAgo(r.at, now)}</span>
                </div>
                <div className="flex items-baseline gap-1.5 text-[12px]">
                  <span className="min-w-0 truncate text-muted">{r.text}</span>
                  <span className="shrink-0"><OriginChip origin={r.origin} /></span>
                </div>
              </li>
            ))}
          </ul>
          <div className="flex gap-3 border-t border-line px-3 py-2 text-[12px]">
            <a href={ASI_ONE_URL} target="_blank" rel="noreferrer" className="font-semibold text-accent">Open in ASI:One</a>
            <a href={AGENTVERSE_URL(AGENTS[0].address)} target="_blank" rel="noreferrer" className="font-semibold text-accent">Agentverse</a>
          </div>
        </div>
      )}
    </div>
  );
}
