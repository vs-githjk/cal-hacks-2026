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
      <nav className="mx-auto flex max-w-[1360px] items-center gap-4 px-4 py-3">
        <Link href="/" aria-label="Tech Bazaar" className="inline-flex min-h-12 shrink-0 items-center gap-2.5 whitespace-nowrap font-display text-[20px] tracking-[0.06em] text-ink">
          <Badge />
          <span className="hidden sm:inline">TECH BAZAAR</span>
        </Link>
        <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto rounded-full border border-line bg-soft/70 p-1.5 [scrollbar-width:none]">
          {NAV.map((n) => {
            const on = n.match ? path.startsWith(n.match) : path === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={on ? "page" : undefined}
                className={`btn inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-full px-5 text-[15px] font-semibold ${on ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-panel hover:text-ink"}`}
              >
                {n.label}
              </Link>
            );
          })}
        </div>
        {path !== "/start" && !path.startsWith("/buyer") && (
          <Link href="/start" className="btn hidden shrink-0 items-center rounded-full border-2 border-line-2 px-5 text-[15px] font-semibold text-ink hover:bg-soft sm:inline-flex min-h-11">
            Start as a buyer
          </Link>
        )}
        <span className="hidden items-center gap-1.5 font-mono text-[12px] uppercase tracking-[0.08em] text-muted md:flex">
          <span className={`h-2.5 w-2.5 rounded-full ${conn.isActive ? "bg-mint" : "border border-ink bg-transparent"}`} aria-hidden />
          {conn.isActive ? "market live" : "offline"}
        </span>
      </nav>
    </header>
  );
}

/** Badge mark: a six-point sheriff star. */
function Badge() {
  return (
    <svg width={27} height={27} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden className="shrink-0 text-accent">
      <path d="M12 2.5 13.6 8l5.4-2-2 5.4 5.4 1.6-5.4 1.6 2 5.4-5.4-2L12 23.5 10.4 18l-5.4 2 2-5.4L1.6 13l5.4-1.6-2-5.4 5.4 2L12 2.5Z" />
      <circle cx="12" cy="12" r="3.1" />
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
