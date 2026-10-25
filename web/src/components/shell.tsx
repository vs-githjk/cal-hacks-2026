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
    <header className="sticky top-0 z-40 border-b border-line bg-glass backdrop-blur-xl">
      <nav className="mx-auto flex max-w-[1360px] items-center gap-4 px-4 py-3">
        <Link href="/" aria-label="Tech Bazaar" className="inline-flex min-h-12 shrink-0 items-center gap-2.5 whitespace-nowrap text-[16px] font-medium tracking-[-0.02em] text-ink">
          <Badge />
          <span data-wordmark="Tech Bazaar" className="hidden sm:inline">Tech Bazaar</span>
        </Link>
        <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto p-0 [scrollbar-width:none]">
          {NAV.map((n) => {
            const on = n.match ? path.startsWith(n.match) : path === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={on ? "page" : undefined}
                className={`btn inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-lg px-3 text-[14px]/[20px] font-medium ${on ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink"}`}
              >
                {n.label}
              </Link>
            );
          })}
        </div>
        {path !== "/start" && !path.startsWith("/buyer") && (
          <Link href="/start" className="btn hidden min-h-11 shrink-0 items-center rounded-xl bg-pulse px-5 text-[15px] font-medium text-pulse-ink sm:inline-flex">
            Start as a buyer
          </Link>
        )}
        <span className={`hidden h-6 items-center gap-1.5 rounded-full px-2.5 text-[12px]/[16px] font-medium md:inline-flex ${conn.isActive ? "bg-live-soft text-ink" : "bg-slate-soft text-slate"}`}>
          <span className={`size-2 rounded-full ${conn.isActive ? "bg-live" : "bg-current opacity-50"}`} aria-hidden />
          {conn.isActive ? "Market live" : "Offline"}
        </span>
      </nav>
    </header>
  );
}

/** Wordmark tile: an ink square with a white disc (the buyer). */
function Badge() {
  return (
    <svg width={22} height={22} viewBox="0 0 22 22" aria-hidden className="shrink-0">
      <rect width="22" height="22" rx="6" className="fill-ink" />
      <circle cx="11" cy="11" r="4.5" className="fill-surface" />
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

const DOT: Record<ServiceStatus["tone"], string> = { live: "bg-live", mirror: "bg-slate", sim: "bg-amber", none: "bg-slate opacity-40" };

/** Footer: one honest line about what ran. Each service's dot comes from the origin tags on the floor events it wrote (lib/runMode.ts), never a hardcoded claim. */
export function RunModeFooter() {
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  const [events] = useTable(tables.floorEvent);
  const services = serviceStatuses(events, live);
  return (
    <footer className="fixed inset-x-0 bottom-0 border-t border-line bg-surface px-4 py-2 font-mono text-[12px] text-muted">
      <div className="mx-auto flex max-w-[1360px] items-center gap-x-4 gap-y-1 overflow-x-auto whitespace-nowrap sm:flex-wrap">
        <span className="flex shrink-0 items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${live ? "bg-live" : "bg-coral-mark"}`} aria-hidden />
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
