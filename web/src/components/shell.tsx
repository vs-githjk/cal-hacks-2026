"use client";
// The header and the run mode footer for every page (design system v2 Nav).

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { STDB_DB, STDB_URI } from "@/lib/stdb";
import { serviceStatuses, type ServiceStatus } from "@/lib/runMode";
import { BRAND } from "@/lib/brand";
import { BrandMark, Wordmark } from "./BrandMark";

const NAV: { href: string; label: string; match?: string }[] = [
  { href: "/buyer", label: "Buyer", match: "/buyer" },
  { href: "/market", label: "Market" },
  { href: "/floor", label: "Floor" },
  { href: "/sell", label: "Sell", match: "/sell" },
];

/** Header: wordmark, links, the market's live pill and the one primary action. On a phone the links scroll in a second row. */
export function AppHeader() {
  const path = usePathname();
  const conn = useSpacetimeDB();
  const links = NAV.map((n) => {
    const on = n.match ? path.startsWith(n.match) : path === n.href;
    return (
      <Link
        key={n.href}
        href={n.href}
        aria-current={on ? "page" : undefined}
        className={`inline-flex min-h-11 shrink-0 items-center rounded-lg px-3 text-[14px] font-medium transition-colors ${on ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink"}`}
      >
        {n.label}
      </Link>
    );
  });

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-glass backdrop-blur-xl">
      <nav aria-label="Main" className="mx-auto flex h-[60px] max-w-[1120px] items-center justify-between gap-4 px-4 md:px-8">
        <Link href="/" aria-label={`${BRAND} home`} className="inline-flex min-h-11 shrink-0 items-center">
          <Wordmark />
        </Link>
        <div className="hidden items-center gap-1 md:flex">{links}</div>
        <div className="flex items-center gap-2.5">
          <LivePill on={conn.isActive} />
          {path !== "/start" && !path.startsWith("/buyer") && (
            <Link href="/start" className="btn inline-flex min-h-10 items-center rounded-xl bg-pulse px-4 text-[14px] font-medium text-pulse-ink hover:shadow-card">
              Start a goal
            </Link>
          )}
        </div>
      </nav>
      <div className="flex gap-1 overflow-x-auto px-3 pb-1.5 [scrollbar-width:none] md:hidden">{links}</div>
    </header>
  );
}

/** Market connection as a v2 pill: cyan heartbeat when live, a neutral word while connecting or offline. */
export function LivePill({ on }: { on: boolean }) {
  return (
    <span className={`hidden h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-[12px] font-medium sm:inline-flex ${on ? "bg-live-soft text-ink" : "bg-slate-soft text-slate"}`}>
      {on ? <span className="dot text-live" aria-hidden /> : <span className="h-2 w-2 rounded-full border border-current" aria-hidden />}
      {on ? "Market live" : "Connecting"}
    </span>
  );
}

/** Kept for screens that showed the old ring mark: now the Fish Market tile. `spin` is accepted and ignored. */
export function Mark({ size = 24 }: { size?: number; spin?: boolean }) {
  return <BrandMark size={size} />;
}

const DOT: Record<ServiceStatus["tone"], string> = { live: "bg-mint-mark", mirror: "bg-slate", sim: "bg-amber", none: "bg-slate opacity-40" };

/** Footer: one honest line about what ran. Each service's dot comes from the origin tags on the floor events it wrote (lib/runMode.ts), never a hardcoded claim. */
export function RunModeFooter() {
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  const [events] = useTable(tables.floorEvent);
  const services = serviceStatuses(events, live);
  return (
    <footer className="fixed inset-x-0 bottom-0 border-t border-line bg-glass px-4 py-2 font-mono text-[11.5px] text-muted backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1120px] items-center gap-x-4 gap-y-1 overflow-x-auto whitespace-nowrap [scrollbar-width:none] sm:flex-wrap md:px-4">
        <span className="flex shrink-0 items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${live ? "bg-live" : "bg-slate opacity-60"}`} aria-hidden />
          Market: {live ? "live" : "connecting"} ({STDB_DB} at {STDB_URI.replace(/^wss?:\/\//, "")})
        </span>
        {services.map((s) => (
          <span key={s.name} className="flex shrink-0 items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${DOT[s.tone]}`} aria-hidden />
            {s.name}: {s.text}
          </span>
        ))}
        <span className="shrink-0 text-muted">Sandbox only: test cards, test identities, no real money</span>
      </div>
    </footer>
  );
}
