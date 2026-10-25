"use client";
// The header and the run mode footer for every page.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { STDB_DB, STDB_URI } from "@/lib/stdb";
import { serviceStatuses, type ServiceStatus } from "@/lib/runMode";

const NAV: { href: string; label: string; match?: string }[] = [
  { href: "/", label: "Home" },
  { href: "/buyer", label: "Buyer" },
  { href: "/market", label: "Market" },
  { href: "/floor", label: "Floor" },
  { href: "/seller/seller-a", label: "Seller", match: "/seller" },
];

/** Header: mark, pill nav and market status. */
export function AppHeader() {
  const path = usePathname();
  const conn = useSpacetimeDB();

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-glass backdrop-blur-md">
      <nav className="mx-auto flex max-w-[1360px] items-center gap-3 px-4 py-2">
        <Link href="/" aria-label="Tech Bazaar" className="inline-flex min-h-11 shrink-0 items-center gap-2 whitespace-nowrap font-display text-[16px] font-semibold tracking-[0.12em] text-ink">
          <Laurel />
          <span className="hidden sm:inline">TECH BAZAAR</span>
        </Link>
        <div className="flex min-w-0 flex-1 gap-0.5 overflow-x-auto [scrollbar-width:none]">
          {NAV.map((n) => {
            const on = n.match ? path.startsWith(n.match) : path === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={on ? "page" : undefined}
                className={`inline-flex min-h-9 shrink-0 items-center border-b-2 px-3 text-[13px] font-medium transition-colors ${on ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink"}`}
              >
                {n.label}
              </Link>
            );
          })}
        </div>
        <span className="hidden items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-muted md:flex">
          <span className={`h-2 w-2 rounded-full ${conn.isActive ? "bg-ink" : "border border-ink bg-transparent"}`} aria-hidden />
          {conn.isActive ? "market live" : "offline"}
        </span>
      </nav>
    </header>
  );
}

/** Laurel mark: two mirrored leaf arcs. */
function Laurel() {
  return (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden className="shrink-0 text-accent">
      <path d="M11 21C5 19 3 12 5 4" />
      <path d="M13 21C19 19 21 12 19 4" />
      <path d="M5.5 9.5C7.5 9 8.5 10 9 12M6.5 14.5C8.5 14 9.5 15 10 17M5 5.5C7 5.5 8 6.5 8.5 8.5" />
      <path d="M18.5 9.5C16.5 9 15.5 10 15 12M17.5 14.5C15.5 14 14.5 15 14 17M19 5.5C17 5.5 16 6.5 15.5 8.5" />
    </svg>
  );
}

/** The Tech Bazaar mark: a referee ring with a sealed bid at its center. */
export function Mark({ size = 24, spin = false }: { size?: number; spin?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden className="shrink-0">
      <circle cx="50" cy="50" r="44" fill="none" stroke="var(--line-2)" strokeWidth="3" />
      <g className={spin ? "origin-center motion-safe:animate-[orbit_18s_linear_infinite]" : ""} style={{ transformBox: "fill-box" }}>
        <circle cx="50" cy="50" r="44" fill="none" stroke="var(--accent)" strokeWidth="6" strokeDasharray="70 207" strokeLinecap="round" />
      </g>
      <rect x="32" y="32" width="36" height="36" rx="9" fill="var(--accent)" />
      <rect x="42" y="42" width="16" height="16" rx="4" fill="var(--accent-ink)" />
    </svg>
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
