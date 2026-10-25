"use client";
// Which local API a page may call, decided in the browser (#398): on the hosted site a loopback API is never fetched.

import { useSyncExternalStore } from "react";
import { reachableFrom } from "./url";

const noSubscribe = () => () => {};

/** base: the API to call from this page, or null. local: the page is deployed and the API only runs locally, so show "runs locally".
 * Before hydration ready is false and both are empty, so the server render neither fetches nor claims anything. */
export function useApiBase(api: string): { ready: boolean; base: string | null; local: boolean } {
  const host = useSyncExternalStore(noSubscribe, () => window.location.hostname, () => "");
  if (!host) return { ready: false, base: null, local: false };
  const base = reachableFrom(api, host);
  return { ready: true, base, local: base === null };
}

/** The page's hostname, "" on the server and before hydration. */
export function usePageHost(): string {
  return useSyncExternalStore(noSubscribe, () => window.location.hostname, () => "");
}
