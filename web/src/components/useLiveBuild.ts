"use client";
// The live build from the agent feed, polled. null until one is posted, so callers fall back to SAMPLE_BUILD, labelled SIM.
import { useEffect, useState } from "react";
import { FEED_URL } from "@/lib/agentFeed";
import { fetchBuild, toBuildResult } from "@/lib/buildView";
import type { BuildResult } from "@/lib/build";

export function useLiveBuild(): BuildResult | null {
  const [build, setBuild] = useState<BuildResult | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    const read = () =>
      fetchBuild(FEED_URL, ctl.signal)
        .then((v) => {
          if (v?.rejected) console.warn(`build feed: ${v.rejected} rows failed the BuildView shape and were left out`);
          setBuild(v ? toBuildResult(v) : null);
        })
        .catch((e) => { if (!ctl.signal.aborted) { console.warn(e); setBuild(null); } });
    read();
    const t = setInterval(read, 3000);
    return () => { clearInterval(t); ctl.abort(); };
  }, []);
  return build;
}
