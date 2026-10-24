"use client";

import { useEffect, useState } from "react";
import { LotScreen } from "@/components/lot";
import { fetchLot, type Lot } from "@/lib/lot";

/** Lot Wall: reads the static lot written by sim/lot_wall.py. A missing or bad file shows the empty state, never bricks. */
export default function LotPage() {
  const [lot, setLot] = useState<Lot | null>(null);
  const [state, setState] = useState<"loading" | "offline" | "ready">("loading");
  useEffect(() => {
    const ctl = new AbortController();
    void fetchLot(ctl.signal).then((l) => {
      if (ctl.signal.aborted) return;
      setLot(l);
      setState(l ? "ready" : "offline");
    });
    return () => ctl.abort();
  }, []);
  return <LotScreen state={state} lot={lot} />;
}
