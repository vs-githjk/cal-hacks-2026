"use client";

import { useEffect, useMemo, useState } from "react";
import { FEED_ENV, feedBase } from "@/lib/agentFeed";
import { chatFromScript, parseChat, type ChatLine } from "@/lib/chatFeed";
import type { FloorScript } from "@/components/floor/floorPhases";

const CHAT_POLL_MS = 1500;

/** Real chat when the agent feed answers (localhost, not replay); otherwise SIM lines from the floor script. */
export function useChatFeed(script: FloorScript, seconds: number, opts: { replay: boolean }): { lines: ChatLine[]; live: boolean } {
  const { replay } = opts;
  const [real, setReal] = useState<ChatLine[] | null>(null);

  useEffect(() => {
    if (replay || typeof window === "undefined") return;
    const base = feedBase(FEED_ENV, window.location.hostname);
    if (!base) return;
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const res = await fetch(`${base}/chat?limit=30`, { signal: ctl.signal, cache: "no-store" });
        if (res.ok) {
          const lines = parseChat(await res.json(), false);
          if (!ctl.signal.aborted) setReal(lines);
        } else if (!ctl.signal.aborted) setReal(null);
      } catch {
        if (!ctl.signal.aborted) setReal(null);
      }
      if (!ctl.signal.aborted) timer = setTimeout(tick, CHAT_POLL_MS);
    };
    void tick();
    return () => {
      ctl.abort();
      if (timer) clearTimeout(timer);
    };
  }, [replay]);

  const sim = useMemo(() => chatFromScript(script, seconds), [script, seconds]);
  const live = !replay && real !== null && real.length > 0;
  return { lines: live ? real : sim, live };
}
