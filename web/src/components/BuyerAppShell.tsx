"use client";
// Buyer navigation under the global header: Dashboard, Purchases, Decisions, plus who this screen is paired as.

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
  { href: "/buyer/purchases", label: "Purchases" },
  { href: "/buyer/decisions", label: "Decisions" },
];

export function BuyerAppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const buyerId = useBuyerId();
  const [profiles] = useTable(tables.myBuyerProfile);
  const name = profiles.find((p) => p.buyerId === buyerId)?.displayName || "Buyer";
  return (
    <div className="grid gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line pb-2">
        <nav aria-label="Buyer" className="flex flex-wrap gap-0.5">
          {NAV.map((n) => {
            const on = path === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={on ? "page" : undefined}
                className={`inline-flex min-h-11 items-center rounded-lg px-3 text-[14px]/[20px] font-medium transition-colors ${on ? "bg-surface-2 text-ink" : "text-muted hover:text-ink"}`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <span className="flex items-center gap-2 text-[13px]/[18px] text-muted">
          {name}
          {/* The market's sellers and payments are SIM tonight: self-serve accounts (ids b_...) say SIM market, the operator-paired buyer says SIM demo pairing. */}
          <OriginChip origin="SIM" label={buyerId.startsWith("b_") ? "SIM market" : "SIM demo pairing"} />
        </span>
      </div>
      <MemoryProvider>{children}</MemoryProvider>
    </div>
  );
}
