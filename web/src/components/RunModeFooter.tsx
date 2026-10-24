"use client";

import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { STDB_DB, STDB_URI } from "@/lib/stdb";
import { serviceStatuses } from "@/lib/runMode";

// Per-service status comes from the floor events each service wrote (origin tags LIVE, MIRROR, SIM),
// so the footer shows what actually ran, not what we hope. See lib/runMode.ts.
export function RunModeFooter() {
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  const [events] = useTable(tables.floorEvent);
  const services = serviceStatuses(events, live);
  return (
    <footer className="fixed inset-x-0 bottom-0 border-t border-[var(--line)] bg-[var(--panel)] px-4 py-2 text-xs text-[var(--muted)]">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-1">
        <span className="flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${live ? "bg-emerald-500" : "bg-rose-500"}`} />
          Market: {live ? "live" : "disconnected"} ({STDB_DB} at {STDB_URI.replace(/^wss?:\/\//, "")})
        </span>
        {services.map((s) => (
          <span key={s.name}>
            {s.name}: {s.text}
          </span>
        ))}
      </div>
    </footer>
  );
}
