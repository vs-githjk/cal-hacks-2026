"use client";
// The header and the run mode footer for every page.

import { useEffect, useState } from "react";
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
const THEME_KEY = "tb_theme";

/** Header: mark, pill nav, market status and a light or dark toggle. Also lights card borders under the pointer. */
export function AppHeader() {
  const path = usePathname();
  const conn = useSpacetimeDB();
  const [light, setLight] = useState(false);

  useEffect(() => {
    let saved = false;
    try {
      saved = localStorage.getItem(THEME_KEY) === "light";
    } catch {
      // Blocked storage: dark, the default.
    }
    setLight(saved);
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("light", light);
  }, [light]);

  // One listener for the whole app: the card under the pointer gets --mx and --my for its lit border.
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let last: HTMLElement | null = null;
    const move = (e: PointerEvent) => {
      const card = (e.target as Element | null)?.closest?.(".card") as HTMLElement | null;
      if (last && last !== card) {
        last.style.removeProperty("--mx");
        last.style.removeProperty("--my");
      }
      last = card;
      if (!card) return;
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - r.left}px`);
      card.style.setProperty("--my", `${e.clientY - r.top}px`);
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => window.removeEventListener("pointermove", move);
  }, []);

  const flip = () => {
    setLight((l) => {
      try {
        localStorage.setItem(THEME_KEY, l ? "dark" : "light");
      } catch {
        // Not remembered; still switches.
      }
      return !l;
    });
  };

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-glass backdrop-blur-md">
      <nav className="mx-auto flex max-w-[1360px] items-center gap-3 px-4 py-2">
        <Link href="/" className="inline-flex min-h-11 shrink-0 items-center gap-2.5 whitespace-nowrap text-[17px] font-semibold tracking-[-0.02em]">
          <Mark size={24} />
          <span className="hidden sm:inline">Tech Bazaar</span>
        </Link>
        <div className="flex min-w-0 flex-1 gap-0.5 overflow-x-auto [scrollbar-width:none]">
          {NAV.map((n) => {
            const on = n.match ? path.startsWith(n.match) : path === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={on ? "page" : undefined}
                className={`inline-flex min-h-9 shrink-0 items-center rounded-full px-3 text-[13px] font-medium transition-colors ${on ? "bg-accent-soft text-accent-2" : "text-muted hover:bg-soft hover:text-ink"}`}
              >
                {n.label}
              </Link>
            );
          })}
        </div>
        <span className="hidden items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-muted md:flex">
          <span className={`h-2 w-2 rounded-full ${conn.isActive ? "bg-mint shadow-[0_0_10px_var(--mint)]" : "bg-coral"}`} aria-hidden />
          {conn.isActive ? "market live" : "offline"}
        </span>
        <button
          type="button"
          onClick={flip}
          aria-label={light ? "Switch to dark" : "Switch to light"}
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line text-muted hover:text-ink"
        >
          <span aria-hidden className="text-[15px] leading-none">{light ? "◐" : "◑"}</span>
        </button>
      </nav>
    </header>
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
