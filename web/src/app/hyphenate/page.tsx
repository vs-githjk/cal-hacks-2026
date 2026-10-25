"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HyphenateScreen } from "@/components/hyphenate";
import { HYPHENATE_URL, POLL_MS, fetchSnapshot, loadMoment, parseSnapshot, type Snapshot } from "@/lib/hyphenate";
import recorded from "@/lib/fixtures/hyphenate-recorded.json";
import { useApiBase } from "@/lib/useApiBase";

/** Hyphenate: the purchasing and AP seats. Reads the local API (:8789) every few seconds; when it is down the page says so and shows no rows. */
export default function HyphenatePage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [state, setState] = useState<"loading" | "offline" | "ready">("loading");
  const [loadingMoment, setLoadingMoment] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const api = useApiBase(HYPHENATE_URL);
  const recordedSnapshot = useMemo(() => parseSnapshot(recorded.raw), []);

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

  if (api.local) // the hosted site: the recorded SIM snapshot, labelled, never a fetch to 127.0.0.1 (#398)
    return <HyphenateScreen state={recordedSnapshot ? "ready" : "local"} snapshot={recordedSnapshot} recordedAt={recorded.recorded_at} />;
  return <HyphenateScreen state={state} snapshot={snapshot} onLoadMoment={onLoadMoment} loadingMoment={loadingMoment} />;
}
