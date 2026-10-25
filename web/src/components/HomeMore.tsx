"use client";
// web/src/components/HomeMore.tsx
// The home sections that the minimal landing folded away (#448): the five beats, who gets what, the agent auction, this round in
// numbers, the latest moves and the four screens. Mounted under "How it works" behind one toggle, so nothing was deleted.

import Link from "next/link";
import { useMemo } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { Corral } from "./Corral";
import { HowItWorks, Sides } from "./Explainer";
import { OriginChip, clock } from "./ui";
import { asOrigin, bidsFromRows, latestRound } from "@/lib/screens";
import { toDate } from "@/lib/stdb";

const ROUTES: { href: string; path: string; title: string; text: string; chips: string[] }[] = [
  { href: "/buyer", path: "/buyer", title: "Buyer", text: "Your goal, ranked bids, the veto with its source, the call and the receipt.", chips: ["MIRROR", "SIM"] },
  { href: "/market", path: "/market", title: "Market", text: "The referee's floor: sealed round, every seller line, loss reports, floor events.", chips: ["MIRROR", "SIM"] },
  { href: "/floor", path: "/floor", title: "Floor", text: "The live arena. Every move is a market row; click one to see its row.", chips: ["SIM"] },
  { href: "/seller/seller-a", path: "/seller/[id]", title: "Seller", text: "One seller's view: the pooled lot as a band, its own loss reports, what to change.", chips: ["SIM"] },
];

export function HomeMore() {
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
    <div className="grid gap-12 pt-10">
      <HowItWorks />
      <Sides />
      <Corral bids={bids} goalLine="Hunting the best verified price" />
      <section aria-label="This round in numbers" className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        {stats.map((s) => (
          <div key={s.label} className="card p-5">
            <div className="text-[32px] font-medium leading-none tracking-[-0.02em] tabular-nums text-ink md:text-[40px]">{s.value}</div>
            <div className="mt-2.5 flex items-center gap-1.5 text-[13px] text-muted">{s.label} <OriginChip origin={s.origin} /></div>
          </div>
        ))}
      </section>
      {latest.length > 0 && (
        <section aria-label="Latest moves" className="card grid gap-0 divide-y divide-line overflow-hidden p-0">
          {latest.map((e) => (
            <div key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3.5">
              <span className="font-mono text-[12px] font-medium uppercase tracking-[0.04em] text-pulse">{e.kind}</span>
              <span className="min-w-0 flex-1 text-[15px] text-ink-2">{e.label}</span>
              <OriginChip origin={e.origin} />
              <span className="font-mono text-[12px] text-muted">{clock(toDate(e.at))}</span>
            </div>
          ))}
        </section>
      )}
      <section aria-label="Screens" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {ROUTES.map((t) => (
          <Link key={t.href} href={t.href} className="btn card group flex min-h-[160px] flex-col justify-between p-5 hover:-translate-y-0.5 hover:shadow-lift">
            <div>
              <div className="flex items-center justify-between font-mono text-[12px] text-pulse">{t.path}<span className="text-muted transition-transform group-hover:translate-x-0.5" aria-hidden>→</span></div>
              <div className="mt-2.5 text-[20px] font-semibold tracking-[-0.01em]">{t.title}</div>
              <p className="mt-1.5 text-[14.5px] text-muted">{t.text}</p>
            </div>
            <div className="mt-4 flex gap-1.5">{t.chips.map((c) => <OriginChip key={c} origin={c} />)}</div>
          </Link>
        ))}
      </section>
    </div>
  );
}
