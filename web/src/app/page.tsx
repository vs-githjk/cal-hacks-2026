"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { Mark } from "@/components/shell";
import { OriginChip, Label, clock } from "@/components/ui";
import { Question } from "@/components/arena";
import { asOrigin, latestRound } from "@/lib/screens";
import { toDate } from "@/lib/stdb";

const ROUTES: { href: string; path: string; title: string; text: string; chips: string[] }[] = [
  { href: "/buyer", path: "/buyer", title: "Buyer", text: "Vidyut's goal, ranked bids, the veto with its source, the call and the receipt.", chips: ["MIRROR", "SIM"] },
  { href: "/market", path: "/market", title: "Market", text: "The referee's floor: sealed round, every seller line, loss reports, floor events.", chips: ["MIRROR", "SIM"] },
  { href: "/floor", path: "/floor", title: "3D floor", text: "Every character moves only when a market row names it. Click one to see its row.", chips: ["SIM"] },
  { href: "/seller/seller-a", path: "/seller/[id]", title: "Seller", text: "One seller's view: the pooled lot as a band, its own loss reports, what to change.", chips: ["SIM"] },
];

const PARTS = ["GPU", "CPU", "Motherboard", "RAM", "SSD", "Cooler"];

/** Home: the first screen judges see. Every number on it is counted from live market rows. */
export default function Home() {
  const conn = useSpacetimeDB();
  const [rounds] = useTable(tables.round);
  const [results] = useTable(tables.roundResult);
  const [events] = useTable(tables.floorEvent);

  const r = latestRound(rounds);
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
  const ticker = useMemo(() => [...events].sort((a, b) => (a.id < b.id ? 1 : -1)).slice(0, 14), [events]);

  return (
    <div className="grid gap-10 pb-10">
      <section className="relative -mx-4 grid items-center gap-8 overflow-hidden px-4 pt-6 md:min-h-[420px] md:grid-cols-[1.1fr_.9fr] md:gap-10">
        <div className="relative z-10 order-2 md:order-1">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1 font-mono text-[11px] uppercase tracking-[0.1em] text-muted">
            <span className={`h-1.5 w-1.5 rounded-full ${conn.isActive ? "bg-mint" : "bg-coral"}`} aria-hidden />
            {r ? `${r.id} · ${r.state === "closed" ? "closed" : "open"}` : "no round yet"}
          </p>
          <h1 className="max-w-[18ch] font-display text-[clamp(30px,5vw,56px)] font-semibold leading-[1.08] tracking-[0.01em] text-balance">
            The arena answers one question at a time.
          </h1>
          <p className="mt-5 max-w-[52ch] text-[16px] text-ink-2">
            Sellers bid in a sealed round. Your agent vetoes traps with proof. Above your allowance, it calls you. Nothing is paid until the condition matches.
          </p>
          <div className="mt-7 flex flex-wrap gap-2.5">
            <Link href="/market" className="inline-flex min-h-11 items-center gap-2 rounded-full bg-accent px-5 font-medium text-accent-ink transition-transform motion-safe:hover:-translate-y-0.5">
              Watch the round <span aria-hidden>→</span>
            </Link>
            <Link href="/start" className="inline-flex min-h-11 items-center rounded-full border border-line-2 px-5 font-medium text-ink hover:bg-soft">
              Start as a buyer
            </Link>
            <Link href="/buyer" className="inline-flex min-h-11 items-center rounded-full border border-line-2 px-5 font-medium text-ink hover:bg-soft">
              Open the buyer screen
            </Link>
          </div>
        </div>
        <div className="relative order-1 grid place-items-center md:order-2">
          <span className="hidden md:block"><Mark size={300} spin /></span>
          <span className="md:hidden"><Mark size={160} spin /></span>
        </div>
      </section>

      <Question question="Who builds the best 1440p gaming PC under $2,000?" bout={1} of={6} status="open" origin="SIM" />

      <section aria-label="One round per part" className="grid gap-3">
        <div className="flex items-center justify-between gap-2">
          <Label>One sealed round per part</Label>
          <OriginChip origin="SIM" />
        </div>
        <ol className="grid grid-cols-3 gap-x-4 gap-y-4 sm:grid-cols-6">
          {PARTS.map((p, i) => (
            <li key={p} className="border-t-2 border-line-2 pt-2.5">
              <span className="text-[12px] tabular-nums text-muted">{i + 1}</span>
              <span className="block text-[14px] text-ink">{p}</span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-label="This round in numbers" className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius)] border border-line bg-line sm:grid-cols-5">
        {stats.map((s) => (
          <div key={s.label} className="bg-panel px-4 py-4">
            <div className="text-[clamp(26px,3vw,36px)] font-semibold leading-none tracking-[-0.02em] tabular-nums text-ink">{s.value}</div>
            <div className="mt-2 flex items-center gap-1.5 text-[12px] text-muted">
              {s.label} <OriginChip origin={s.origin} />
            </div>
          </div>
        ))}
      </section>

      {ticker.length > 0 && (
        <section aria-label="Latest floor events" className="-mx-4 overflow-hidden border-y border-line bg-canvas-2 py-2.5">
          <div className="flex w-max gap-8 whitespace-nowrap font-mono text-[12px] text-muted motion-safe:animate-[marquee_60s_linear_infinite] hover:[animation-play-state:paused]">
            {[0, 1].map((copy) =>
              ticker.map((e) => (
                <span key={`${copy}-${e.id}`} aria-hidden={copy === 1} className="inline-flex items-center gap-2">
                  <span className="text-accent">{e.kind}</span>
                  <span className="text-ink-2">{e.label}</span>
                  <OriginChip origin={e.origin} />
                  <span>{clock(toDate(e.at))}</span>
                </span>
              )),
            )}
          </div>
        </section>
      )}

      <section aria-label="Screens" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {ROUTES.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="card group flex min-h-[132px] flex-col justify-between p-4 transition-transform motion-safe:hover:-translate-y-0.5"
          >
            <div>
              <div className="flex items-center justify-between font-mono text-[12px] text-accent">
                {t.path}
                <span className="text-muted transition-transform group-hover:translate-x-0.5" aria-hidden>→</span>
              </div>
              <div className="mt-2 text-[17px] font-semibold tracking-[-0.01em]">{t.title}</div>
              <p className="mt-1 text-[13px] text-muted">{t.text}</p>
            </div>
            <div className="mt-3 flex gap-1.5">
              {t.chips.map((c) => <OriginChip key={c} origin={c} />)}
            </div>
          </Link>
        ))}
      </section>
    </div>
  );
}
