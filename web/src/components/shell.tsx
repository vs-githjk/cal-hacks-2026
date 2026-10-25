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
        className={`btn inline-flex min-h-10 shrink-0 items-center rounded-xl px-3.5 text-[15px] font-medium transition-[background-color,box-shadow,transform] ${on ? "bg-ink text-canvas shadow-[0_6px_16px_-6px_rgba(11,27,43,0.5)]" : "text-ink-2 hover:bg-white/70 hover:text-ink hover:shadow-ring"}`}
      >
        {n.label}
      </Link>
    );
  });

  return (
    <header className="sticky top-0 z-40 border-b border-white/50 bg-[rgba(214,236,247,0.55)] backdrop-blur-xl">
      <nav aria-label="Main" className="relative mx-auto flex h-[60px] max-w-[1120px] items-center justify-between gap-4 px-4 md:px-8">
        <Link href="/" aria-label={`${BRAND} home`} className="inline-flex min-h-11 shrink-0 items-center">
          <Wordmark showName={false} />
          <span className="ml-2 hidden text-[16px] font-medium tracking-[-0.02em] text-ink lg:inline">{BRAND}</span>
        </Link>
        <div className="absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 items-center gap-0.5 rounded-2xl border border-white/70 bg-white/45 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_8px_24px_-12px_rgba(11,27,43,0.25)] backdrop-blur-xl sm:flex">{links}</div>
        <div className="flex items-center gap-2.5">
          <span className="hidden lg:inline-flex"><LivePill on={conn.isActive} /></span>
          {path !== "/start" && !path.startsWith("/buyer") && (
            <Link href="/start" className="btn inline-flex min-h-10 items-center rounded-xl bg-[linear-gradient(135deg,#1e4ed8,#0891b2)] px-4 text-[14px] font-medium text-white shadow-[0_8px_20px_-8px_rgba(8,145,178,0.7)] hover:shadow-[0_10px_24px_-8px_rgba(8,145,178,0.8)]">
              Start a goal
            </Link>
          )}
        </div>
      </nav>
      <div className="mx-auto mb-2 flex w-max max-w-full gap-0.5 overflow-x-auto rounded-2xl border border-white/70 bg-white/45 p-1 [scrollbar-width:none] sm:hidden">{links}</div>
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
