"use client";

import { useSpacetimeDB } from "spacetimedb/react";
import { STDB_DB, STDB_URI } from "@/lib/stdb";

// Services owned by other lanes show "mock" until their adapters land. Update as they do.
const OTHER_SERVICES: { name: string; mode: string }[] = [
  { name: "Advocate", mode: "mock" },
  { name: "Shield", mode: "mock" },
  { name: "Claim check", mode: "mock" },
  { name: "Payments", mode: "mock" },
];

export function RunModeFooter() {
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  return (
    <footer className="fixed inset-x-0 bottom-0 border-t border-[var(--line)] bg-[var(--panel)] px-4 py-2 text-xs text-[var(--muted)]">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-1">
        <span className="flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${live ? "bg-emerald-500" : "bg-rose-500"}`} />
          Market: {live ? "live" : "disconnected"} ({STDB_DB} at {STDB_URI.replace(/^wss?:\/\//, "")})
        </span>
        {OTHER_SERVICES.map((s) => (
          <span key={s.name}>
            {s.name}: {s.mode}
          </span>
        ))}
      </div>
    </footer>
  );
}
