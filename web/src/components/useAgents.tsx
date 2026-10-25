"use client";
// One poller for everything that shows the Fetch agents (the corner tile and the directory). It runs only while something
// is subscribed and pauses while the tab is hidden, so two views never double the traffic or disagree about a row.

import { useState, useSyncExternalStore } from "react";
import { AGENTS, AGENTVERSE_URL } from "@/lib/agents";
import { FEED_ENV, POLL_MS, feedBase, fetchAgents, type AgentRow } from "@/lib/agentFeed";

/** rows: undefined while the first poll is pending, null when the feed is offline (no stale rows are kept). now: when it was read.
 * noFeed: no reachable feed is configured for this page, so views show the Agentverse profiles rather than "offline". */
export interface AgentsState {
  rows: AgentRow[] | null | undefined;
  now: number;
  noFeed?: boolean;
}

const INITIAL: AgentsState = { rows: undefined, now: 0 };
let state = INITIAL;
const listeners = new Set<() => void>();
let stopPolling: (() => void) | null = null;

function startPolling() {
  let stop = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const ctl = new AbortController();
  const base = feedBase(FEED_ENV, window.location.hostname);
  if (!base) {
    state = { rows: null, now: Date.now(), noFeed: true };
    queueMicrotask(() => listeners.forEach((l) => l()));
    return () => {};
  }
  const tick = async () => {
    if (!document.hidden) {
      const rows = await fetchAgents(base, ctl.signal);
      if (stop) return;
      state = { rows, now: Date.now() };
      listeners.forEach((l) => l());
    }
    if (!stop) timer = setTimeout(tick, POLL_MS);
  };
  void tick();
  return () => {
    stop = true;
    ctl.abort();
    if (timer) clearTimeout(timer);
  };
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) stopPolling = startPolling();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      stopPolling?.();
      stopPolling = null;
      state = INITIAL;
    }
  };
}

export function useAgents(): AgentsState {
  return useSyncExternalStore(subscribe, () => state, () => INITIAL);
}

/** The agent's picture when the feed sent a real web address, else a neutral initial. A picture that fails to load falls back too. */
export function AgentAvatar({ row, size = 28 }: { row: AgentRow; size?: number }) {
  const [failed, setFailed] = useState(false);
  const box = { width: size, height: size };
  if (row.avatar && !failed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- the avatar host is whatever the feed names, so next/image cannot be configured for it
      <img src={row.avatar} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} style={box} className="shrink-0 rounded-full object-cover" />
    );
  }
  return (
    <span aria-hidden style={box} className="inline-flex shrink-0 items-center justify-center rounded-full bg-surface-2 text-[12px] font-semibold text-ink-2">
      {row.name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}

/** Shown when this page has no reachable feed (a deployed site): the six published Agentverse profiles, with no status claimed. */
export function AgentProfiles({ className = "" }: { className?: string }) {
  return (
    <ul className={`divide-y divide-line ${className}`}>
      {AGENTS.map((a) => (
        <li key={a.key} className="flex items-center gap-2 py-1">
          <span className="min-w-0 flex-1 truncate font-semibold">{a.name}</span>
          <a href={AGENTVERSE_URL(a.address)} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center font-medium text-pulse underline-offset-2 hover:underline">
            Agentverse profile
          </a>
        </li>
      ))}
    </ul>
  );
}
