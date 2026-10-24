"use client";
// Fetch agents, live: a floating tile in a screen corner, like a minimized video call. Collapsed it is a small tile
// (a pill on a phone), expanded it lists every agent with its status and last line. Drag it to a corner, or use Move.
// Reads only the agent feed (lib/agentFeed.ts); when the feed is down it says "agents offline" and shows no rows.

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { OriginChip } from "@/components/ui";
import {
  ASI_ONE_URL,
  NEXT_CORNER,
  POLL_MS,
  STATUS_TEXT,
  ago,
  agentverseUrl,
  fetchAgents,
  nearestCorner,
  realRows,
  summary,
  type AgentRow,
  type AgentStatus,
  type Corner,
} from "@/lib/agentFeed";

const PREFS_KEY = "tb-agent-pip";
// Bottom corners clear the fixed run-mode footer, top corners clear the header; neither sits over the page's hero number.
const CORNER_CLASS: Record<Corner, string> = {
  br: "bottom-12 right-3",
  bl: "bottom-12 left-3",
  tr: "top-[64px] right-3",
  tl: "top-[64px] left-3",
};
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
  return { open: false, corner: "br" };
}

function savePrefs(p: Prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    // a per-viewer convenience only
  }
}

const subscribe = () => () => {};

/** Browser only: the saved corner and open state come from localStorage, which the server cannot see. */
export function AgentPip() {
  const inBrowser = useSyncExternalStore(subscribe, () => true, () => false);
  return inBrowser ? <AgentPipTile /> : null;
}

function AgentPipTile() {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [rows, setRows] = useState<AgentRow[] | null | undefined>(undefined); // undefined: first poll pending, null: offline
  const [now, setNow] = useState(() => Date.now());
  const [drag, setDrag] = useState<{ dx: number; dy: number } | null>(null);
  const box = useRef<HTMLElement>(null);
  const start = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ctl = new AbortController();
    const tick = async () => {
      if (!document.hidden) {
        const r = await fetchAgents(ctl.signal);
        if (stop) return;
        setRows(r);
        setNow(Date.now());
      }
      if (!stop) timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => {
      stop = true;
      ctl.abort();
      if (timer) clearTimeout(timer);
    };
  }, []);

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
  const anyUp = shown.some((r) => r.status !== "down");
  const head = pending ? "Checking agents" : offline ? "Agents offline" : summary(shown);

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
      style={drag ? { transform: `translate(${drag.dx}px, ${drag.dy}px)` } : undefined}
      className={`fixed z-40 flex flex-col overflow-hidden rounded-2xl border border-line bg-panel text-[13px] shadow-lg ${CORNER_CLASS[prefs.corner]} ${
        prefs.open ? "h-[320px] max-h-[60vh] w-[min(360px,calc(100vw-24px))]" : "w-auto sm:h-[120px] sm:w-[220px]"
      } ${drag ? "" : "transition-[width,height] duration-150"}`}
    >
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className="flex min-h-11 cursor-grab touch-none select-none items-center gap-2 border-b border-line px-3 active:cursor-grabbing"
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${offline ? "bg-coral" : anyUp ? "bg-mint" : "bg-slate opacity-40"}`} aria-hidden />
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
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
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
                {shown.map((r) => (
                  <li key={`${r.role}-${r.name}`} className="py-2">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[r.status]}`} aria-hidden />
                      <span className="min-w-0 flex-1 truncate font-semibold">{r.name}</span>
                      <OriginChip origin={r.origin} label={STATUS_TEXT[r.status]} />
                    </div>
                    <p className="mt-0.5 truncate pl-4 text-muted" title={r.last_message ?? undefined}>
                      {r.last_message ?? "no messages yet"}
                      {r.at ? ` (${ago(r.at, now)})` : ""}
                    </p>
                    {r.status === "agentverse" && r.address ? (
                      <a
                        href={agentverseUrl(r.address)}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-0.5 inline-block pl-4 text-accent underline-offset-2 hover:underline"
                      >
                        Agentverse
                      </a>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex items-center gap-3 border-t border-line px-3 py-2">
            <a href={ASI_ONE_URL} target="_blank" rel="noreferrer" className="font-semibold text-accent underline-offset-2 hover:underline">
              Open in ASI:One
            </a>
          </div>
        </>
      ) : (
        <div className="hidden min-h-0 flex-1 flex-col justify-center gap-1 px-3 sm:flex">
          {offline || pending || shown.length === 0 ? (
            <p className="text-muted">{pending ? "Checking..." : offline ? "No feed" : "Nothing running"}</p>
          ) : (
            <>
              <p className="flex flex-wrap gap-1.5" aria-hidden>
                {shown.map((r) => (
                  <span key={`${r.role}-${r.name}`} className={`h-2.5 w-2.5 rounded-full ${DOT[r.status]}`} title={`${r.name}: ${STATUS_TEXT[r.status]}`} />
                ))}
              </p>
              <p className="line-clamp-2 text-muted">{shown.find((r) => r.last_message)?.last_message ?? "no messages yet"}</p>
            </>
          )}
        </div>
      )}
    </aside>
  );
}
