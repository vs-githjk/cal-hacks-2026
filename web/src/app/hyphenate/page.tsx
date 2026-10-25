"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { HyphenateScreen } from "@/components/hyphenate";
import { HYPHENATE_URL, POLL_MS, fetchSnapshot, loadMoment, type Snapshot } from "@/lib/hyphenate";
import { useApiBase } from "@/lib/useApiBase";

/** Hyphenate: the purchasing and AP seats. Reads the local API (:8789) every few seconds; when it is down the page says so and shows no rows. */
export default function HyphenatePage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [state, setState] = useState<"loading" | "offline" | "ready">("loading");
  const [loadingMoment, setLoadingMoment] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const api = useApiBase(HYPHENATE_URL);

  const refresh = useCallback(async () => {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    const s = await fetchSnapshot(ctl.signal);
    if (ctl.signal.aborted) return;
    setSnapshot(s);
    setState(s ? "ready" : "offline");
  }, []);

  useEffect(() => {
    if (!api.base) return; // not hydrated yet, or the hosted site: Hyphenate runs locally, so never fetch 127.0.0.1
    // refresh() only sets state after an await, so the first fetch is not a synchronous cascade
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => {
      clearInterval(t);
      abort.current?.abort();
    };
  }, [api.base, refresh]);

  const onLoadMoment = useCallback(async () => {
    setLoadingMoment(true);
    await loadMoment();
    await refresh();
    setLoadingMoment(false);
  }, [refresh]);

  return <HyphenateScreen state={api.local ? "local" : state} snapshot={snapshot} onLoadMoment={onLoadMoment} loadingMoment={loadingMoment} />;
}
