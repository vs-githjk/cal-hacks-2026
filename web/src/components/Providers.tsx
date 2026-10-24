"use client";

import { useSyncExternalStore } from "react";
import { SpacetimeDBProvider } from "spacetimedb/react";
import { connectionBuilder } from "@/lib/stdb";

const subscribe = () => () => {};

// Every screen is live market state, so nothing here renders on the server: the connection is
// built in the browser only (it draws random connection ids, which prerendering forbids).
export function Providers({ children }: { children: React.ReactNode }) {
  const inBrowser = useSyncExternalStore(subscribe, () => true, () => false);
  if (!inBrowser) return <p className="mx-auto max-w-6xl px-4 py-6 text-[var(--muted)]">Connecting to the market...</p>;
  return <ClientProvider>{children}</ClientProvider>;
}

let builder: ReturnType<typeof connectionBuilder> | null = null;

function ClientProvider({ children }: { children: React.ReactNode }) {
  builder ??= connectionBuilder();
  return <SpacetimeDBProvider connectionBuilder={builder}>{children}</SpacetimeDBProvider>;
}
