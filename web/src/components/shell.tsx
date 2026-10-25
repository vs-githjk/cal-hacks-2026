"use client";
// The header and the run mode footer for every page (design system v2 Nav).

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { STDB_DB, STDB_URI } from "@/lib/stdb";
import { serviceStatuses, type ServiceStatus } from "@/lib/runMode";
import { BRAND } from "@/lib/brand";
import { navEdges, scrollToShow } from "@/lib/navScroll";
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
  const links = NAV.map((n) => {
    const on = n.match ? path.startsWith(n.match) : path === n.href;
    return (
      <Link
        key={n.href}
        href={n.href}
        aria-current={on ? "page" : undefined}
        className={`btn inline-flex min-h-10 shrink-0 items-center rounded-xl px-3.5 text-[15px] font-medium transition-[background-color,transform] ${on ? "bg-ink/10 text-ink" : "text-ink-2 hover:bg-ink/5 hover:text-ink"}`}
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
        <div className="absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 items-center gap-1 sm:flex">{links}</div>
        <div className="flex items-center gap-2.5">
          {path !== "/start" && !path.startsWith("/buyer") && (
            <Link href="/start" className="btn fm-btn fm-grad inline-flex min-h-10 items-center rounded-xl px-4 text-[14px] font-medium text-white">
              Start a goal
            </Link>
          )}
        </div>
      </nav>
      <NavScroll path={path} className="mx-auto mb-1 flex w-max max-w-full gap-1 overflow-x-auto [scrollbar-width:none] sm:hidden">{links}</NavScroll>
    </header>
  );
}

/** The phone nav row. On a 390 px phone the links scroll sideways; a fade on the edge that hides more links says so (#449 RT-33),
 * and the current page's link is scrolled into view. The fade is a CSS mask driven by data-more-left / data-more-right. */
function NavScroll({ path, className, children }: { path: string; className: string; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const measure = useCallback(() => {
    const el = box.current;
    if (el) setEdges(navEdges(el));
  }, []);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(measure);   // also fires once on observe(), which sets the first state
    observer.observe(el);
    return () => observer.disconnect();
  }, [measure]);
  useEffect(() => {
    const el = box.current;
    const current = el?.querySelector<HTMLElement>("[aria-current='page']");
    if (el && current) el.scrollLeft = scrollToShow(el, current);
  }, [path]);
  return (
    <div ref={box} onScroll={measure} data-nav-scroll data-more-left={edges.left} data-more-right={edges.right} className={className}>
      {children}
    </div>
  );
}

/** Kept for screens that showed the old ring mark: now the Fish Market tile. `spin` is accepted and ignored. */
export function Mark({ size = 24 }: { size?: number; spin?: boolean }) {
  return <BrandMark size={size} />;
}

const DOT: Record<ServiceStatus["tone"], string> = { live: "bg-mint-mark", mirror: "bg-slate", sandbox: "bg-mint", sim: "bg-amber", none: "bg-slate opacity-40" };

/** Footer: one honest line about what ran. Each service's dot comes from the origin tags on the floor events it wrote (lib/runMode.ts), never a hardcoded claim. */
export function RunModeFooter() {
  const path = usePathname();
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  const [events] = useTable(tables.floorEvent);
  const services = serviceStatuses(events, live);
  if (path === "/") return null; // the landing has no status line (#448, Vidyut); app screens keep it
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
