"use client";
// The header and the run mode footer for every page.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { STDB_DB, STDB_URI } from "@/lib/stdb";
import { serviceStatuses, type ServiceStatus } from "@/lib/runMode";

/** Header: wordmark plus two links. Drop into layout.tsx in place of the <header>. */
export function AppHeader() {
  const path = usePathname();
  const link = (href: string, label: string) => (
    <Link
      href={href}
      className={`inline-flex min-h-11 items-center rounded-lg px-3 text-[14px] font-medium ${path === href ? "text-ink" : "text-muted hover:text-ink"}`}
      aria-current={path === href ? "page" : undefined}
    >
      {label}
    </Link>
  );
  return (
    <header className="border-b border-line bg-panel">
      <nav className="mx-auto flex max-w-[1360px] items-center gap-3 px-4 py-2">
        <Link href="/" className="mr-1 inline-flex min-h-11 shrink-0 items-center gap-2.5 whitespace-nowrap text-[18px] font-bold tracking-[-0.01em] sm:mr-3">
          <span className="relative inline-block h-[22px] w-[22px] rounded-[7px] bg-accent" aria-hidden>
            <span className="absolute inset-1.5 rounded-[3px] bg-accent-ink opacity-90" />
          </span>
          Tech Bazaar
        </Link>
        {link("/buyer", "Buyer")}
        {link("/market", "Market")}
        {link("/floor", "Floor")}
      </nav>
    </header>
  );
}

const DOT: Record<ServiceStatus["tone"], string> = { live: "bg-mint", mirror: "bg-sky", sim: "bg-amber", none: "bg-slate opacity-40" };

/** Footer: one honest line about what ran. Each service's dot comes from the origin tags on the floor events it wrote (lib/runMode.ts), never a hardcoded claim. */
export function RunModeFooter() {
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  const [events] = useTable(tables.floorEvent);
  const services = serviceStatuses(events, live);
  return (
    <footer className="fixed inset-x-0 bottom-0 border-t border-line bg-panel px-4 py-2 font-mono text-[12px] text-muted">
      <div className="mx-auto flex max-w-[1360px] items-center gap-x-4 gap-y-1 overflow-x-auto whitespace-nowrap sm:flex-wrap">
        <span className="flex shrink-0 items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${live ? "bg-mint" : "bg-coral"}`} aria-hidden />
          Market: {live ? "live" : "disconnected"} ({STDB_DB} at {STDB_URI.replace(/^wss?:\/\//, "")})
        </span>
        {services.map((s) => (
          <span key={s.name} className="flex shrink-0 items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${DOT[s.tone]}`} aria-hidden />
            {s.name}: {s.text}
          </span>
        ))}
      </div>
    </footer>
  );
}
