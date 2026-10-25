"use client";
// The top navigation band (brand, folder tabs, market status) and the run mode services for every page.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { STDB_DB, STDB_URI } from "@/lib/stdb";
import { latestRound } from "@/lib/screens";
import { serviceStatuses, type ServiceStatus } from "@/lib/runMode";

const NAV: { href: string; label: string; match?: string }[] = [
  { href: "/", label: "Overview" },
  { href: "/buyer", label: "Buyer" },
  { href: "/market", label: "Market" },
  { href: "/floor", label: "Floor" },
  { href: "/seller/seller-a", label: "Seller", match: "/seller" },
];

function useActive() {
  const path = usePathname();
  return (n: (typeof NAV)[number]) => (n.match ? path.startsWith(n.match) : path === n.href);
}

/** The top navigation band: brand, five page tabs (the active one is a cream folder tab cut out of the navy band) and market status. */
export function TopNav() {
  const isOn = useActive();
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  const r = latestRound(useTable(tables.round)[0]);
  const status = !live ? "Offline" : r ? `Live, ${r.id} ${r.state === "closed" ? "closed" : "open"}` : "Live, no round yet";
  return (
    <header className="sticky top-0 z-40 bg-accent text-accent-ink">
      <div className="mx-auto flex max-w-[1200px] items-end gap-2 px-4 lg:px-8">
        <Link href="/" aria-label="Tech Bazaar" className="on-navy mr-2 flex h-14 shrink-0 items-center gap-2.5 self-stretch">
          <Mark size={26} />
          <span className="hidden text-[16px] font-semibold text-accent-ink sm:inline">Tech Bazaar</span>
        </Link>
        <nav aria-label="Main" className="min-w-0 flex-1 self-end overflow-x-auto [scrollbar-width:none]">
          <ul className="flex items-end gap-1 pt-3">
            {NAV.map((n) => {
              const on = isOn(n);
              return (
                <li key={n.href}>
                  <Link
                    href={n.href}
                    aria-current={on ? "page" : undefined}
                    className={on ? "tab-on flex h-11 items-center px-4 text-[14px] font-semibold" : "flex h-11 items-center rounded-t-xl px-4 text-[14px] font-medium text-accent-ink/75 hover:bg-accent-ink/10 hover:text-accent-ink"}
                  >
                    {n.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="ml-auto flex h-14 shrink-0 items-center gap-3 self-stretch text-[13px] text-accent-ink/85">
          <span className="hidden items-center gap-2 md:flex">
            <span className={`h-2 w-2 rounded-full ${live ? "bg-accent-ink" : "border border-accent-ink/70 bg-transparent"}`} aria-hidden />
            {status}
          </span>
          {/* The one entry point for a stranger: /start comes with #385. Once #379 lands, a paired buyer sees "Continue as <name>" to /buyer here instead. */}
          <Link href="/start" className="inline-flex h-9 items-center rounded-full bg-accent-ink px-3.5 text-[13px] font-semibold text-accent hover:bg-accent-ink/90">
            Start<span className="hidden sm:inline">&nbsp;as a buyer</span>
          </Link>
        </div>
      </div>
    </header>
  );
}

/** The Tech Bazaar mark: a navy tile with a cream seal and a gold arc on a ring. */
export function Mark({ size = 24, spin = false }: { size?: number; spin?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden className="shrink-0">
      <circle cx="50" cy="50" r="44" fill="none" stroke="var(--line-2)" strokeWidth="3" />
      <g className={spin ? "origin-center motion-safe:animate-[orbit_18s_linear_infinite]" : ""} style={{ transformBox: "fill-box" }}>
        <circle cx="50" cy="50" r="44" fill="none" stroke="var(--gold)" strokeWidth="6" strokeDasharray="70 207" strokeLinecap="round" />
      </g>
      <rect x="32" y="32" width="36" height="36" rx="9" fill="var(--accent)" />
      <rect x="42" y="42" width="16" height="16" rx="4" fill="var(--accent-ink)" />
    </svg>
  );
}

const DOT: Record<ServiceStatus["tone"], string> = { live: "bg-mint", mirror: "bg-sky", sim: "bg-amber", none: "bg-slate opacity-40" };

/** Run mode services: one honest line per service. Each dot comes from the origin tags on the floor events it wrote (lib/runMode.ts), never a hardcoded claim.
 *  Renders at the end of every page. */
export function RunModeFooter() {
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  const [events] = useTable(tables.floorEvent);
  const services = serviceStatuses(events, live);
  return (
    <footer className="mx-auto mt-8 flex max-w-[1200px] flex-wrap gap-x-5 gap-y-1 border-t border-line px-4 py-4 text-[12px] text-muted lg:px-8">
      <span className="flex items-center gap-1.5">
        <span className={`h-2 w-2 shrink-0 rounded-full ${live ? "bg-mint" : "bg-coral"}`} aria-hidden />
        Market: {live ? "live" : "disconnected"}
        <span className="max-w-[28ch] truncate" title={`${STDB_DB} at ${STDB_URI}`}>
          {STDB_DB} at {STDB_URI.replace(/^wss?:\/\//, "")}
        </span>
      </span>
      {services.map((s) => (
        <span key={s.name} className="flex items-center gap-1.5">
          <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[s.tone]}`} aria-hidden />
          {s.name}: {s.text}
        </span>
      ))}
    </footer>
  );
}
