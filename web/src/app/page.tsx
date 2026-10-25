"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { Mark } from "@/components/shell";
import { Corral } from "@/components/Corral";
import { HowItWorks, Sides } from "@/components/Explainer";
import { OriginChip, clock } from "@/components/ui";
import { asOrigin, bidsFromRows, latestRound } from "@/lib/screens";
import { toDate } from "@/lib/stdb";

const ROUTES: { href: string; path: string; title: string; text: string; chips: string[] }[] = [
  { href: "/buyer", path: "/buyer", title: "Buyer", text: "Vidyut's goal, ranked bids, the veto with its source, the call and the receipt.", chips: ["MIRROR", "SIM"] },
  { href: "/market", path: "/market", title: "Market", text: "The referee's floor: sealed round, every seller line, loss reports, floor events.", chips: ["MIRROR", "SIM"] },
  { href: "/floor", path: "/floor", title: "3D floor", text: "Every character moves only when a market row names it. Click one to see its row.", chips: ["SIM"] },
  { href: "/seller/seller-a", path: "/seller/[id]", title: "Seller", text: "One seller's view: the pooled lot as a band, its own loss reports, what to change.", chips: ["SIM"] },
];

/** Home: the first screen judges see. Every number on it is counted from live market rows. */
export default function Home() {
  const conn = useSpacetimeDB();
  const [rounds] = useTable(tables.round);
  const [results] = useTable(tables.roundResult);
  const [events] = useTable(tables.floorEvent);

  const r = latestRound(rounds);
  const bids = useMemo(() => bidsFromRows(results, events, r?.id), [results, events, r]);
  const stats = useMemo(() => {
    const mine = results.filter((x) => x.roundId === r?.id);
    const by = (o: string) => mine.filter((x) => asOrigin(x.origin) === o).length;
    return [
      { label: "sealed bids", value: r?.sealedCount ?? 0, origin: r?.origin ?? "SIM" },
      { label: "MIRROR listings", value: by("MIRROR"), origin: "MIRROR" },
      { label: "SIM sellers", value: by("SIM"), origin: "SIM" },
      { label: "LIVE bids", value: by("LIVE"), origin: "LIVE" },
      { label: "floor events", value: events.length, origin: "SIM" },
    ];
  }, [r, results, events]);
  const latest = useMemo(() => [...events].sort((a, b) => (a.id < b.id ? 1 : -1)).slice(0, 4), [events]);

  return (
    <div className="grid gap-12 pb-12">
      <section className="relative -mx-4 grid items-center gap-4 overflow-hidden px-4 pt-6 text-center">
        <p className="mx-auto inline-flex items-center gap-2 rounded-full border border-line bg-panel px-4 py-1.5 font-mono text-[12px] uppercase tracking-[0.1em] text-muted">
          <span className={`h-2 w-2 rounded-full ${conn.isActive ? "bg-mint" : "bg-coral"}`} aria-hidden />
          {r ? `${r.id} · ${r.state === "closed" ? "closed" : "open"}` : "no round yet"}
        </p>
        <h1 className="mx-auto max-w-[20ch] font-display text-[clamp(32px,6vw,68px)] font-normal leading-[1.05] tracking-[0.01em] text-balance">
          <span className="mr-3 inline-block align-middle">
            <Mark size={52} spin />
          </span>
          The arena answers one question at a time.
        </h1>
        <p className="mx-auto mt-1 max-w-[56ch] text-[19px] text-ink-2">
          Sellers bid in a sealed round. Your agent vetoes traps with proof. Inside your allowance it can pay on its own; above it, it calls you.
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-3">
          <Link href="/market" className="btn inline-flex min-h-14 items-center gap-2 rounded-full bg-accent px-8 text-[17px] font-semibold text-accent-ink shadow-[var(--shadow)]">
            Watch the round <span aria-hidden>→</span>
          </Link>
          <Link href="/start" className="btn inline-flex min-h-14 items-center rounded-full border-2 border-line-2 bg-panel px-8 text-[17px] font-semibold text-ink hover:bg-soft">
            Start as a buyer
          </Link>
          <Link href="/buyer" className="btn inline-flex min-h-14 items-center rounded-full border-2 border-line-2 bg-panel px-8 text-[17px] font-semibold text-ink hover:bg-soft">
            Open the buyer screen
          </Link>
        </div>
      </section>

      <HowItWorks />

      <Sides />

      <Corral bids={bids} goalLine="Hunting the best verified price" />

      <section aria-label="This round in numbers" className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        {stats.map((s) => (
          <div key={s.label} className="card p-5">
            <div className="text-[clamp(28px,3.2vw,40px)] font-semibold leading-none tracking-[-0.02em] tabular-nums text-ink">{s.value}</div>
            <div className="mt-2.5 flex items-center gap-1.5 text-[13px] text-muted">
              {s.label} <OriginChip origin={s.origin} />
            </div>
          </div>
        ))}
      </section>

      {latest.length > 0 && (
        <section aria-label="Latest moves" className="card grid gap-0 divide-y divide-line overflow-hidden p-0">
          {latest.map((e) => (
            <div key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3.5">
              <span className="font-mono text-[12px] font-semibold uppercase tracking-[0.06em] text-accent">{e.kind}</span>
              <span className="min-w-0 flex-1 text-[15px] text-ink-2">{e.label}</span>
              <OriginChip origin={e.origin} />
              <span className="font-mono text-[12px] text-muted">{clock(toDate(e.at))}</span>
            </div>
          ))}
        </section>
      )}

      <section aria-label="Screens" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {ROUTES.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="btn card group flex min-h-[160px] flex-col justify-between p-5 hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            <div>
              <div className="flex items-center justify-between font-mono text-[12px] text-accent">
                {t.path}
                <span className="text-muted transition-transform group-hover:translate-x-0.5" aria-hidden>→</span>
              </div>
              <div className="mt-2.5 text-[20px] font-semibold tracking-[-0.01em]">{t.title}</div>
              <p className="mt-1.5 text-[14.5px] text-muted">{t.text}</p>
            </div>
            <div className="mt-4 flex gap-1.5">
              {t.chips.map((c) => <OriginChip key={c} origin={c} />)}
            </div>
          </Link>
        ))}
      </section>
    </div>
  );
}
