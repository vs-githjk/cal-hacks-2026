"use client";

import { useMemo } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { OriginChip, Label, clock, money } from "@/components/ui";
import { Question } from "@/components/arena";
import { asOrigin, latestRound, recentRounds, roundTitle } from "@/lib/screens";
import { toDate } from "@/lib/stdb";

const PARTS = ["GPU", "CPU", "Motherboard", "RAM", "SSD", "Cooler"];

/** Home: the first screen judges see. Every number on it is counted from live market rows. */
export default function Home() {
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
  const recent = useMemo(() => recentRounds(rounds, results, events), [rounds, results, events]);
  const ticker = useMemo(() => [...events].sort((a, b) => (a.id < b.id ? 1 : -1)).slice(0, 14), [events]);

  return (
    <div className="grid gap-4">
      <Question question="Who builds the best 1440p gaming PC under $2,000?" bout={1} of={6} status="open" origin="SIM" />

      <section aria-label="This round" className="card p-4">
        <div className="flex items-center justify-between gap-2 [&>h2]:mb-0">
          <Label>One sealed round per part</Label>
          <OriginChip origin="SIM" />
        </div>
        <ol className="mt-2 grid grid-cols-3 gap-x-4 gap-y-4 sm:grid-cols-6">
          {PARTS.map((p, i) => (
            <li key={p} className="border-t-2 border-line-2 pt-2.5">
              <span className="text-[12px] tabular-nums text-muted">{i + 1}</span>
              <span className="block text-[14px] text-ink">{p}</span>
            </li>
          ))}
        </ol>
        <div className="my-4 border-t border-line" />
        <dl className="grid grid-cols-2 gap-y-4 sm:grid-cols-5 sm:divide-x sm:divide-line">
          {stats.map((s) => (
            <div key={s.label} className="px-1 sm:px-4 first:pl-0">
              <dd className="text-[26px] font-semibold leading-none tabular-nums text-ink">{s.value}</dd>
              <dt className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
                {s.label} <OriginChip origin={s.origin} />
              </dt>
            </div>
          ))}
        </dl>
      </section>

      {recent.length > 0 && (
        <section aria-label="Recent rounds" className="card p-4">
          <div className="[&>h2]:mb-2">
            <Label>Recent rounds</Label>
          </div>
          <ul className="divide-y divide-line">
            {recent.map((x) => (
              <li key={x.id} className="grid grid-cols-[auto_1fr_auto] items-baseline gap-x-4 py-2 text-[13.5px]">
                <span className="tabular-nums text-muted">{clock(x.closedAt)}</span>
                <span className="min-w-0 truncate">
                  <span className="text-ink">{roundTitle(x.id) ?? x.id}</span> <span className="text-muted">{x.bids} {x.bids === 1 ? "bid" : "bids"}</span> <OriginChip origin={x.origin} />
                </span>
                {x.winner ? (
                  <span className="whitespace-nowrap">
                    <span className="font-medium text-ink">{x.winner.seller}</span> <OriginChip origin={x.winner.origin} /> <span className="tabular-nums">{money(x.winner.landed)}</span>
                  </span>
                ) : (
                  <span className="text-muted">no winner</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

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
