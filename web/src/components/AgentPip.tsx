"use client";
// The Fetch tile: an activity feed pinned in a screen corner (top right on a desktop, a compact pill at the bottom on a phone),
// not a video call. Collapsed it shows the latest recorded activity and its age; expanded it lists every agent, links to the
// directory, and links out to ASI:One and Agentverse. Drag it to a corner, or use Move.
// Reads only the agent feed (lib/agentFeed.ts); when the feed is down it says "agents offline" and shows no rows.

import Link from "next/link";
import { useCallback, useRef, useState, useSyncExternalStore } from "react";
import { OriginChip } from "@/components/ui";
import { AgentAvatar, useAgents } from "@/components/useAgents";
import { useLiveBuild } from "@/components/useLiveBuild";
import { planLines, SAMPLE_BUILD, type BuildResult, type StepKind } from "@/lib/build";
import {
  ASI_ONE_URL,
  NEXT_CORNER,
  STATUS_TEXT,
  agentLink,
  ago,
  headline,
  isStale,
  latestActivity,
  nearestCorner,
  realRows,
  type AgentStatus,
  type Corner,
} from "@/lib/agentFeed";

// A new key: the first version defaulted to the bottom right on every screen, and a saved corner would keep that.
const PREFS_KEY = "tb-agent-pip-2";
// Bottom corners clear the fixed run-mode footer, top corners clear the header.
const CORNER_CLASS: Record<Corner, string> = {
  br: "bottom-12 right-3",
  bl: "bottom-12 left-3",
  tr: "top-[64px] right-3",
  tl: "top-[64px] left-3",
};
// Plan and re-plan lines: the clash is the one red line, the swap and the lock are green, a budget move is amber.
const PLAN_TONE: Partial<Record<StepKind, string>> = { clash: "text-coral", swap: "text-mint", locked: "text-mint", reallocate: "text-amber", blocked: "text-coral" };
const PLAN_LABEL: Partial<Record<StepKind, string>> = { plan: "Plan", clash: "Clash", swap: "Re-plan", reallocate: "Budget", locked: "Locked", blocked: "Blocked" };

/** The buyer agent's build plan and re-plans, above the agent rows. The live build (useLiveBuild); SAMPLE_BUILD, labelled SIM, only while none is posted. */
function BuildPlan({ build, origin }: { build: BuildResult; origin: string }) {
  return (
    <section aria-label="Build plan" className="border-b border-line pb-2">
      <div className="flex items-center gap-2 py-1">
        <span className="flex-1 font-semibold">Buyer agent: build plan</span>
        <OriginChip origin={origin} />
      </div>
      <ol className="grid gap-1">
        {planLines(build).map((s, i) => (
          <li key={i} className="grid grid-cols-[52px_1fr] gap-2">
            <span className={`text-[11px] font-bold uppercase tracking-[0.04em] ${PLAN_TONE[s.kind] ?? "text-muted"}`}>{PLAN_LABEL[s.kind]}</span>
            <span className="min-w-0 text-ink-2">{s.line}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

const DOT: Record<AgentStatus, string> = { agentverse: "bg-mint", local: "bg-sky", down: "bg-coral" };

interface Prefs {
  open: boolean;
  corner: Corner;
}

function loadPrefs(): Prefs {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) ?? "null");
    if (p && typeof p.open === "boolean" && p.corner in CORNER_CLASS) return p;
  } catch {
    // storage blocked or corrupt: fall through to the default
  }
  return { open: false, corner: window.matchMedia("(max-width: 639px)").matches ? "br" : "tr" };
}

function savePrefs(p: Prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    // a per-viewer convenience only
  }
}

const subscribe = () => () => {};

/** Browser only: the saved corner and open state come from localStorage, which the server cannot see. Mounted once, in the root layout. */
export function AgentPip() {
  const inBrowser = useSyncExternalStore(subscribe, () => true, () => false);
  return inBrowser ? <AgentPipTile /> : null;
}

function AgentPipTile() {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const { rows, now } = useAgents();
  const liveBuild = useLiveBuild();
  const [drag, setDrag] = useState<{ dx: number; dy: number } | null>(null);
  const box = useRef<HTMLElement>(null);
  const start = useRef<{ x: number; y: number } | null>(null);

  const update = useCallback((next: Partial<Prefs>) => {
    setPrefs((p) => {
      const merged = { ...p, ...next };
      savePrefs(merged);
      return merged;
    });
  }, []);

  const shown = rows ? realRows(rows) : [];
  const offline = rows === null;
  const pending = rows === undefined;
  const latest = latestActivity(shown);
  const fresh = !!latest && !isStale(latest.at, now);
  const head = headline(rows ? shown : rows, now);

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button, a")) return;
    start.current = { x: e.clientX, y: e.clientY };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (start.current) setDrag({ dx: e.clientX - start.current.x, dy: e.clientY - start.current.y });
  };
  const onPointerUp = () => {
    const el = box.current;
    if (start.current && el) {
      const r = el.getBoundingClientRect();
      update({ corner: nearestCorner(r.left + r.width / 2, r.top + r.height / 2, window.innerWidth, window.innerHeight) });
    }
    start.current = null;
    setDrag(null);
  };

  return (
    <aside
      ref={box}
      aria-label="Fetch agents"
      onKeyDown={(e) => {
        if (e.key === "Escape" && prefs.open) update({ open: false });
      }}
      style={drag ? { transform: `translate(${drag.dx}px, ${drag.dy}px)` } : undefined}
      className={`fixed z-40 flex flex-col overflow-hidden rounded-2xl border border-line bg-panel text-[13px] shadow-lg ${CORNER_CLASS[prefs.corner]} ${
        prefs.open ? "h-[360px] max-h-[60vh] w-[min(360px,calc(100vw-24px))]" : "w-auto max-w-[calc(100vw-24px)] sm:w-[340px]"
      } ${drag ? "" : "transition-[width,height] duration-150 motion-reduce:transition-none"}`}
    >
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className="flex min-h-11 cursor-grab touch-none select-none items-center gap-2 px-3 active:cursor-grabbing"
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${offline ? "bg-coral" : fresh ? "bg-mint" : "bg-slate opacity-40"}`} aria-hidden />
        <span className="min-w-0 flex-1 truncate font-semibold" aria-live="polite">
          {head}
        </span>
        <button
          type="button"
          onClick={() => update({ corner: NEXT_CORNER[prefs.corner] })}
          className="inline-flex min-h-11 min-w-11 items-center justify-center text-muted hover:text-ink"
          aria-label="Move to the next corner"
          title="Move to the next corner"
        >
          <span aria-hidden>&#8635;</span>
        </button>
        <button
          type="button"
          onClick={() => update({ open: !prefs.open })}
          className="inline-flex min-h-11 min-w-11 items-center justify-center text-muted hover:text-ink"
          aria-label={prefs.open ? "Collapse agents" : "Expand agents"}
          aria-expanded={prefs.open}
        >
          <span aria-hidden>{prefs.open ? "-" : "+"}</span>
        </button>
      </div>

      {prefs.open ? (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto border-t border-line px-3 py-2">
            <BuildPlan build={liveBuild ?? SAMPLE_BUILD} origin={liveBuild?.origin ?? "SIM"} />
            {offline || pending || shown.length === 0 ? (
              <p className="py-3 text-muted">
                {pending
                  ? "Checking the agent feed..."
                  : offline
                    ? "The agent feed is not answering, so no agent rows are shown. Start it with python3 scripts/launch.py up."
                    : "No agents are running. Start them with python3 scripts/launch.py up."}
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {shown.map((r) => {
                  const link = agentLink(r);
                  return (
                    <li key={`${r.role}-${r.name}`} className="flex gap-2.5 py-2">
                      <AgentAvatar row={r} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate font-semibold">{r.name}</span>
                          <OriginChip origin={r.origin} />
                        </div>
                        <p className="flex items-center gap-1.5 text-muted">
                          <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[r.status]}`} aria-hidden />
                          {STATUS_TEXT[r.status]}
                        </p>
                        <p className="truncate text-muted" title={r.last_message ?? undefined}>
                          {r.last_message ?? "no messages yet"}
                          {ago(r.at, now) ? ` (${ago(r.at, now)})` : ""}
                        </p>
                        {link ? (
                          <a href={link} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center text-accent underline-offset-2 hover:underline">
                            Agentverse profile
                          </a>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <div className="flex items-center gap-4 border-t border-line px-3">
            <Link href="/buyer/agents" className="inline-flex min-h-11 items-center font-semibold text-accent underline-offset-2 hover:underline">
              All agents
            </Link>
            <a href={ASI_ONE_URL} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center font-semibold text-accent underline-offset-2 hover:underline">
              Open in ASI:One
            </a>
          </div>
        </>
      ) : (
        <p className="hidden truncate px-3 pb-2.5 text-muted sm:block" title={latest?.last_message ?? undefined}>
          {pending ? "Checking..." : offline ? "No feed" : (latest?.last_message ?? "No recorded activity")}
        </p>
      )}
    </aside>
  );
}
