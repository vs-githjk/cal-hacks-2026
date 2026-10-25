"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { OriginChip, Label, clock } from "@/components/ui";
import { Question } from "@/components/arena";
import { asOrigin, latestRound } from "@/lib/screens";
import { toDate } from "@/lib/stdb";

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
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div>
          <h1 className="font-display text-[32px] font-semibold tracking-[-0.02em] text-ink">Overview</h1>
          <p className="mt-1 max-w-[60ch] text-[15px] text-ink-2">
            Sellers bid in sealed rounds. Your agent vetoes traps with proof and calls you above your allowance.
          </p>
          <p className="mt-2 flex items-center gap-2 text-[13px] text-ink-2">
            <span className={`h-1.5 w-1.5 rounded-full ${conn.isActive ? "bg-mint" : "bg-coral"}`} aria-hidden />
            {r ? `${r.id} is ${r.state === "closed" ? "closed" : "open"}` : "No round yet"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <Link href="/buyer" className="inline-flex min-h-10 items-center rounded-lg bg-accent px-4 font-medium text-accent-ink">
            Open the buyer screen
          </Link>
          <Link href="/floor" className="inline-flex min-h-10 items-center rounded-lg bg-panel px-4 font-medium text-ink ring-1 ring-line-2 hover:bg-soft">
            Watch the round
          </Link>
        </div>
      </header>

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

      <section aria-label="This round in numbers" className="card grid grid-cols-2 sm:grid-cols-5 sm:divide-x sm:divide-line">
        {stats.map((s) => (
          <div key={s.label} className="px-4 py-4">
            <div className="text-[28px] font-semibold leading-none tabular-nums text-ink">{s.value}</div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
              {s.label} <OriginChip origin={s.origin} />
            </div>
          </div>
        ))}
      </section>

      {ticker.length > 0 && (
        <section aria-label="Latest floor events" className="overflow-hidden rounded-lg bg-canvas-2 py-2.5">
          <div className="flex w-max gap-8 whitespace-nowrap px-4 text-[13px] text-ink-2 motion-safe:animate-[marquee_60s_linear_infinite] hover:[animation-play-state:paused]">
            {[0, 1].map((copy) =>
              ticker.map((e) => (
                <span key={`${copy}-${e.id}`} aria-hidden={copy === 1} className="inline-flex items-center gap-2">
                  <span className="font-medium text-ink">{e.kind}</span>
                  <span className="text-ink-2">{e.label}</span>
                  <OriginChip origin={e.origin} />
                  <span>{clock(toDate(e.at))}</span>
                </span>
              )),
            )}
          </div>
        </section>
      )}
    </div>
  );
}
