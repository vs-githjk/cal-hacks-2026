"use client";
// The sidebar, phone top bar, bottom tabs and run mode services for every page.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { STDB_DB, STDB_URI } from "@/lib/stdb";
import { serviceStatuses, type ServiceStatus } from "@/lib/runMode";

const NAV: { href: string; label: string; match?: string }[] = [
  { href: "/", label: "Overview" },
  { href: "/buyer", label: "Buyer" },
  { href: "/market", label: "Market" },
  { href: "/floor", label: "Floor" },
  { href: "/seller/seller-a", label: "Seller", match: "/seller" },
];

function Icon({ label }: { label: string }) {
  const p = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, className: "shrink-0" };
  switch (label) {
    case "Overview":
      return <svg {...p}><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" /></svg>;
    case "Buyer":
      return <svg {...p}><circle cx="12" cy="8" r="3.5" /><path d="M5 20c0-3.9 3.1-6.5 7-6.5s7 2.6 7 6.5" /></svg>;
    case "Market":
      return <svg {...p}><path d="M5 20V11M12 20V4M19 20v-6" /></svg>;
    case "Floor":
      return <svg {...p}><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" /><path d="M4 7.5l8 4.5 8-4.5M12 12v9" /></svg>;
    default:
      return <svg {...p}><path d="M3.5 12.5V4.5a1 1 0 0 1 1-1h8l8 8-9 9-8-8z" /><circle cx="8" cy="8" r="1.3" /></svg>;
  }
}

function useActive() {
  const path = usePathname();
  return (n: (typeof NAV)[number]) => (n.match ? path.startsWith(n.match) : path === n.href);
}

/** Desktop left sidebar: brand, main nav, run mode services at the bottom. */
export function Sidebar() {
  const isOn = useActive();
  return (
    <aside className="hidden lg:flex sticky top-0 h-screen w-[240px] shrink-0 flex-col border-r border-line bg-canvas-2 px-3 py-5">
      <Link href="/" aria-label="Tech Bazaar" className="flex items-center gap-2.5 px-3">
        <Mark size={28} />
        <span className="font-display text-[18px] font-semibold text-ink">Tech Bazaar</span>
      </Link>
      <nav aria-label="Main" className="mt-8">
        <ul className="flex flex-col gap-1">
          {NAV.map((n) => {
            const on = isOn(n);
            return (
              <li key={n.href}>
                <Link
                  href={n.href}
                  aria-current={on ? "page" : undefined}
                  className={`flex min-h-10 items-center gap-3 rounded-lg px-3 text-[14px] ${on ? "bg-panel text-accent font-semibold ring-1 ring-line" : "text-ink-2 hover:bg-panel/60 hover:text-ink"}`}
                >
                  <Icon label={n.label} />
                  {n.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="mt-auto px-3">
        <RunModeFooter compact />
      </div>
    </aside>
  );
}

/** Phone top bar: brand and market status. */
export function TopBar() {
  const conn = useSpacetimeDB();
  return (
    <div className="lg:hidden sticky top-0 z-30 flex items-center justify-between border-b border-line bg-glass px-4 py-2.5 backdrop-blur">
      <Link href="/" aria-label="Tech Bazaar" className="flex items-center gap-2">
        <Mark size={24} />
        <span className="font-display text-[16px] font-semibold text-ink">Tech Bazaar</span>
      </Link>
      <span className="flex items-center gap-1.5 text-[13px] text-ink-2">
        <span className={`h-2 w-2 rounded-full ${conn.isActive ? "bg-mint" : "bg-coral"}`} aria-hidden />
        {conn.isActive ? "Live" : "Offline"}
      </span>
    </div>
  );
}

/** Phone bottom tab bar. */
export function BottomTabs() {
  const isOn = useActive();
  return (
    <nav aria-label="Main" className="lg:hidden fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-line bg-panel/95 backdrop-blur pb-[env(safe-area-inset-bottom)]">
      {NAV.map((n) => {
        const on = isOn(n);
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={on ? "page" : undefined}
            className={`flex min-h-14 flex-col items-center justify-center gap-1 text-[11px] ${on ? "text-accent font-semibold" : "text-muted"}`}
          >
            <Icon label={n.label} />
            {n.label}
          </Link>
        );
      })}
    </nav>
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
 *  `compact` is the sidebar copy (desktop only); without it this is the inline phone copy at the end of the page. */
export function RunModeFooter({ compact = false }: { compact?: boolean }) {
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  const [events] = useTable(tables.floorEvent);
  const services = serviceStatuses(events, live);
  return (
    <footer className={compact ? "text-[12px] text-muted" : "lg:hidden mx-4 mt-8 border-t border-line pb-4 pt-4 text-[12px] text-muted"}>
      <ul className="flex flex-col gap-1.5">
        <li>
          <span className="flex items-center gap-1.5">
            <span className={`h-2 w-2 shrink-0 rounded-full ${live ? "bg-mint" : "bg-coral"}`} aria-hidden />
            Market: {live ? "live" : "disconnected"}
          </span>
          <span className="mt-0.5 block truncate pl-3.5" title={`${STDB_DB} at ${STDB_URI}`}>
            {STDB_DB} at {STDB_URI.replace(/^wss?:\/\//, "")}
          </span>
        </li>
        {services.map((s) => (
          <li key={s.name} className="flex items-center gap-1.5">
            <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[s.tone]}`} aria-hidden />
            {s.name}: {s.text}
          </li>
        ))}
      </ul>
    </footer>
  );
}
