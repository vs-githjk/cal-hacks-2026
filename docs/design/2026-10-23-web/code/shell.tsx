// Replacements for the header in app/layout.tsx and for components/RunModeFooter.tsx.
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSpacetimeDB } from "spacetimedb/react";
import { STDB_DB, STDB_URI } from "@/lib/stdb";

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
        <Link href="/" className="mr-3 inline-flex min-h-11 items-center gap-2.5 text-[18px] font-bold tracking-[-0.01em]">
          <span className="relative inline-block h-[22px] w-[22px] rounded-[7px] bg-accent" aria-hidden>
            <span className="absolute inset-1.5 rounded-[3px] bg-accent-ink opacity-90" />
          </span>
          Tech Bazaar
        </Link>
        {link("/buyer", "Buyer")}
        {link("/market", "Market")}
      </nav>
    </header>
  );
}

// Services owned by other lanes. "mode" is shown as written: say "fixture" or "stub", never "live", until the adapter is real.
const OTHER_SERVICES: { name: string; mode: string; real: boolean }[] = [
  { name: "Advocate", mode: "real checks", real: true },
  { name: "Shield", mode: "shield-1.0.0", real: true },
  { name: "Claim check", mode: "fixture", real: false },
  { name: "Payments", mode: "SIM stub", real: false },
];

/** Footer: one honest line about what is live. Replaces RunModeFooter. */
export function RunModeFooter() {
  const conn = useSpacetimeDB();
  const live = conn.isActive;
  return (
    <footer className="fixed inset-x-0 bottom-0 border-t border-line bg-panel px-4 py-2 font-mono text-[12px] text-muted">
      <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-4 gap-y-1">
        <span className="flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${live ? "bg-mint" : "bg-coral"}`} aria-hidden />
          Market: {live ? "live" : "disconnected"} ({STDB_DB} at {STDB_URI.replace(/^wss?:\/\//, "")})
        </span>
        {OTHER_SERVICES.map((s) => (
          <span key={s.name} className="flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${s.real ? "bg-mint" : "bg-amber"}`} aria-hidden />
            {s.name}: {s.mode}
          </span>
        ))}
      </div>
    </footer>
  );
}
