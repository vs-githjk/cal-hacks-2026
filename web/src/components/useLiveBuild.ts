"use client";
// The live build from the agent feed, polled. null until one is posted, so callers fall back to SAMPLE_BUILD, labelled SIM.
import { useEffect, useState } from "react";
import { FEED_ENV, feedBase } from "@/lib/agentFeed";
import { fetchBuild, toBuildResult } from "@/lib/buildView";
import type { BuildResult } from "@/lib/build";

export function useLiveBuild(): BuildResult | null {
  const [build, setBuild] = useState<BuildResult | null>(null);
  useEffect(() => {
    const base = feedBase(FEED_ENV, window.location.hostname);
    if (!base) return; // deployed page with no reachable feed: stay null, callers show SIM
    const ctl = new AbortController();
    let seq = 0;
    const read = () => {
      const mine = ++seq;
      return fetchBuild(base, ctl.signal)
        .then((v) => { if (mine === seq) setBuild(v ? toBuildResult(v) : null); })
        .catch((e) => { if (!ctl.signal.aborted && mine === seq) { console.warn(e); setBuild(null); } });
    };
    read();
    const t = setInterval(read, 3000);
    return () => { clearInterval(t); ctl.abort(); };
  }, []);
  return build;
}
