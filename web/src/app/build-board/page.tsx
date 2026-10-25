"use client";

import { useEffect, useState } from "react";
import { BuildBoardScreen } from "@/components/buildBoard";
import { fetchBuildView, type BuildView } from "@/lib/buildBoard";

/** #343 Build Board: reads public/build-board.json (Lane D's shape and sample). A missing or bad file shows the empty state, never bricks. */
export default function BuildPage() {
  const [build, setBuild] = useState<BuildView | null>(null);
  const [state, setState] = useState<"loading" | "offline" | "ready">("loading");
  useEffect(() => {
    const ctl = new AbortController();
    void fetchBuildView(ctl.signal).then((b) => {
      if (ctl.signal.aborted) return;
      setBuild(b);
      setState(b ? "ready" : "offline");
    });
    return () => ctl.abort();
  }, []);
  return <BuildBoardScreen state={state} build={build} />;
}
