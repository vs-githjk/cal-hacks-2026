"use client";
// Buyer navigation under the global header (design system v2): the page title, who this screen is paired as, and a segmented
// control for Dashboard, Decisions, Purchases and Agents. The tabs scroll sideways on a phone; nothing scrolls the page sideways.

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { useBuyerId } from "./BuyerGate";
import { MemoryProvider } from "./memory";
import { OriginChip } from "./ui";

const NAV = [
  { href: "/buyer", label: "Dashboard" },
  { href: "/buyer/decisions", label: "Decisions" },
  { href: "/buyer/purchases", label: "Purchases" },
  { href: "/buyer/agents", label: "Agents" },
];

export function BuyerAppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const buyerId = useBuyerId();
  const [profiles] = useTable(tables.myBuyerProfile);
  const name = profiles.find((p) => p.buyerId === buyerId)?.displayName || "Buyer";
  const title = NAV.find((n) => n.href === path)?.label ?? "Dashboard";
  return (
    <div className="mx-auto grid w-full max-w-[1120px] grid-cols-[minmax(0,1fr)] gap-6 md:px-4">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4 pt-2 md:pt-6">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-[13px] leading-[18px] text-muted">
            <span className="grid h-6 w-6 place-items-center rounded-full bg-surface text-[11px] font-semibold text-ink shadow-ring" aria-hidden>{name.slice(0, 1).toUpperCase()}</span>
            {name}
            {/* The market's sellers and payments are SIM tonight: self-serve accounts (ids b_...) say SIM market, the operator-paired buyer says SIM demo pairing. */}
            <OriginChip origin="SIM" label={buyerId.startsWith("b_") ? "SIM market" : "SIM demo pairing"} />
          </p>
          <h1 className="mt-2 text-[28px] font-medium leading-[34px] tracking-[-0.015em]">{title}</h1>
        </div>
        <nav aria-label="Buyer" className="flex min-w-0 max-w-full gap-1 overflow-x-auto rounded-xl bg-surface p-1 shadow-ring [scrollbar-width:none]">
          {NAV.map((n) => {
            const on = path === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={on ? "page" : undefined}
                className={`inline-flex min-h-10 shrink-0 items-center rounded-lg px-3.5 text-[14px] font-medium transition-colors ${on ? "bg-ink text-canvas" : "text-ink-2 hover:bg-surface-2 hover:text-ink"}`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <MemoryProvider>{children}</MemoryProvider>
    </div>
  );
}
