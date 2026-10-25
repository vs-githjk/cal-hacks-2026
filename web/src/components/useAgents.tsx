"use client";
// One poller for everything that shows the Fetch agents (the corner tile and the directory). It runs only while something
// is subscribed and pauses while the tab is hidden, so two views never double the traffic or disagree about a row.

import { useState, useSyncExternalStore } from "react";
import { POLL_MS, fetchAgents, type AgentRow } from "@/lib/agentFeed";

/** rows: undefined while the first poll is pending, null when the feed is offline (no stale rows are kept). now: when it was read. */
export interface AgentsState {
  rows: AgentRow[] | null | undefined;
  now: number;
}

const INITIAL: AgentsState = { rows: undefined, now: 0 };
let state = INITIAL;
const listeners = new Set<() => void>();
let stopPolling: (() => void) | null = null;

function startPolling() {
  let stop = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const ctl = new AbortController();
  const tick = async () => {
    if (!document.hidden) {
      const rows = await fetchAgents(ctl.signal);
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
    <span aria-hidden style={box} className="inline-flex shrink-0 items-center justify-center rounded-full bg-soft text-[12px] font-semibold text-muted">
      {row.name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
