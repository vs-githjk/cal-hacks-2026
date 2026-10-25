"use client";
// One shared reading of the market connection for the header, footer and home page.

import { useState } from "react";
import { useSpacetimeDB } from "spacetimedb/react";
import { connectionState, type ConnectionState } from "@/lib/runMode";

/** Three states instead of a flipping boolean (lib/runMode.ts): neutral "connecting" until the first
 * connect, then "live", then "disconnected" once a live connection drops or the first connect fails. */
export function useConnectionState(): ConnectionState {
  const conn = useSpacetimeDB();
  const [everActive, setEverActive] = useState(false);
  if (conn.isActive && !everActive) setEverActive(true);
  return connectionState(conn.isActive, everActive, conn.connectionError);
}
