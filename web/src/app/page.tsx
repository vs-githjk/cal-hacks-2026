"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { FishGlyph } from "@/components/BrandMark";
import { HowItWorks, Sides } from "@/components/Explainer";
import { OriginChip, StatusPill, clock, money } from "@/components/ui";
import { asOrigin, bidsFromRows, latestRound, winningBid } from "@/lib/screens";
import { rankedBids as SAMPLE_BIDS } from "@/lib/sample";
import { BRAND, SHIELD, SHIELD_LINE, TAGLINE } from "@/lib/brand";
import { toDate } from "@/lib/stdb";

// Measured results, copied from data/scoreboard.json (Lane C, run of Oct 24): fit_accuracy checked 39 of 39, attacks_blocked held-out
// 0.65 of 20, voice_attacks first run 9 of 10. Update here when the scoreboard is regenerated.
const PROOF: { value: string; text: string }[] = [
  { value: "39 of 39", text: "fit checks right on maker-checked builds" },
  { value: "13 of 20", text: `held-out attacks stopped by ${SHIELD}` },
  { value: "9 of 10", text: "voice approval attacks denied, first run" },
];

const ROUTES: { href: string; path: string; title: string; text: string; chips: string[] }[] = [
  { href: "/buyer", path: "/buyer", title: "Buyer", text: "The buyer's goal, ranked bids, the veto with its source, the call and the receipt.", chips: ["MIRROR", "SIM"] },
  { href: "/market", path: "/market", title: "Market", text: "The referee's floor: sealed round, every seller line, loss reports, floor events.", chips: ["MIRROR", "SIM"] },
  { href: "/floor", path: "/floor", title: "Floor", text: "The live arena: the buyer's agent eats the worst offer each round. Every move is a market row.", chips: ["SIM"] },
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
    <div className="mx-auto grid w-full max-w-[1120px] grid-cols-[minmax(0,1fr)] gap-16 pb-12 md:px-4">
      <section className="grid items-center gap-8 pt-4 md:pt-14 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12">
        <div>
          <span className="inline-flex items-center gap-2 text-[15px] font-medium text-ink-2">
            <span className="dot text-live" aria-hidden /> Live sandbox. Sealed rounds, test-mode money.
          </span>
          <h1 className="mt-4 text-[40px] font-medium leading-[44px] tracking-[-0.025em] text-balance md:text-[56px] md:leading-[60px]">
            Sellers compete. <span className="text-muted">{SHIELD_LINE}</span>
          </h1>
          <p className="mt-4 max-w-[46ch] text-[17px] leading-[26px] text-ink-2">
            {BRAND} is {TAGLINE.charAt(0).toLowerCase() + TAGLINE.slice(1, -1)}. Seller agents bid for your PC parts in sealed rounds, {SHIELD} screens every listing, and nothing above your allowance is paid until you say the code on the phone.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/start" className="btn inline-flex min-h-12 items-center rounded-xl bg-pulse px-6 text-[17px] font-medium text-pulse-ink hover:shadow-card">Start a goal</Link>
            <Link href="/floor" className="btn inline-flex min-h-12 items-center rounded-xl bg-surface px-6 text-[17px] font-medium text-ink shadow-ring hover:bg-surface-2">Watch the floor</Link>
            <Link href="/market" className="inline-flex min-h-12 items-center gap-1.5 px-2 text-[15px] font-medium text-pulse">Open the market <span aria-hidden>→</span></Link>
          </div>
          <p className="mt-4 text-[13px] leading-[18px] text-muted">Free while {BRAND} is a project. Prices are dated listings until Bright Data re-checks them.</p>
          <dl className="mt-10 grid grid-cols-3 gap-4 border-t border-line pt-6 md:gap-8">
            {PROOF.map((p) => (
              <div key={p.value} className="grid gap-0.5">
                <dt className="order-2 max-w-[22ch] text-[13px] leading-[18px] text-muted">{p.text}</dt>
                <dd className="order-1 text-[20px] font-medium leading-[26px] tracking-[-0.015em] tabular-nums md:text-[24px] md:leading-[30px]">{p.value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <HeroMock live={conn.isActive} roundId={r?.id} closed={r?.state === "closed"} bids={bids} />
      </section>

      <HowItWorks />

      <Sides />

      <section aria-label="The floor" className="relative grid gap-6 overflow-hidden rounded-[24px] bg-floor-bg p-6 text-floor-line shadow-lift md:grid-cols-[1fr_auto] md:items-center md:p-10">
        <div className="grid gap-3">
          <span className="inline-flex items-center gap-2 text-[13px] font-medium uppercase tracking-[0.06em] text-ghost-1">
            <span className="dot text-shield" aria-hidden /> The floor
          </span>
          <h2 className="max-w-[24ch] text-[28px] font-medium leading-[34px] tracking-[-0.015em] text-balance md:text-[40px] md:leading-[44px]">Watch every round play out, live.</h2>
          <p className="max-w-[52ch] text-[15px] leading-[22px] text-ghost-1">
            The buyer&apos;s agent eats the worst offer each round. {SHIELD} blocks the fishy ones, the checker vetoes what does not fit, and the referee names the winner. Every move is a market row.
          </p>
          <div className="mt-2 flex flex-wrap gap-2.5" aria-hidden>
            {["ghost-1", "ghost-2", "ghost-3", "ghost-4"].map((g) => <span key={g} className="h-3 w-3 rounded-full" style={{ background: `var(--${g})` }} />)}
          </div>
        </div>
        <div className="flex items-center gap-6 md:flex-col md:items-end">
          <span className="text-pac max-md:hidden"><FishGlyph size={96} /></span>
          <Link href="/floor" className="btn inline-flex min-h-12 items-center gap-2 rounded-xl bg-floor-line px-6 text-[17px] font-medium text-floor-bg hover:shadow-card">
            Watch the floor <span aria-hidden>→</span>
          </Link>
        </div>
      </section>

      <section aria-label="This round in numbers" className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        {stats.map((s) => (
          <div key={s.label} className="card p-5">
            <div className="text-[32px] font-medium leading-none tracking-[-0.02em] tabular-nums text-ink md:text-[40px]">{s.value}</div>
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
          <Link
            key={t.href}
            href={t.href}
            className="btn card group flex min-h-[160px] flex-col justify-between p-5 hover:-translate-y-0.5 hover:shadow-lift"
          >
            <div>
              <div className="flex items-center justify-between font-mono text-[12px] text-pulse">
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

/** The hero's glass card: the latest round's winner from market rows, or the recorded sample run (labelled SIM) while none has closed. */
function HeroMock({ live, roundId, closed, bids }: { live: boolean; roundId?: string; closed: boolean; bids: ReturnType<typeof bidsFromRows> }) {
  const liveWin = closed ? winningBid(bids) : null;
  const win = liveWin ?? winningBid(SAMPLE_BIDS);
  const pool = liveWin ? bids : SAMPLE_BIDS;
  const vetoed = pool.filter((b) => b.recommendation === "veto").length;
  const out = pool.filter((b) => b.rank === null).length;
  return (
    <div className="glass rise grid gap-4 p-5 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[12px] font-medium uppercase tracking-[0.04em] text-muted">
          {liveWin ? `Latest round · ${roundId} · closed` : "Sample round · GPU · closed"}
        </span>
        {liveWin ? <StatusPill tone="live" pulse={live}>From the market</StatusPill> : <OriginChip origin="SIM" label="SIM sample" />}
      </div>
      {win ? (
        <>
          <div className="text-[40px] font-medium leading-[44px] tracking-[-0.02em] tabular-nums md:text-[48px] md:leading-[52px]">
            {money(win.landed)}<small className="ml-2 text-[15px] font-normal tracking-normal text-muted">landed</small>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[15px] text-ink-2">{win.seller} · {win.condition} <OriginChip origin={win.origin} /></div>
        </>
      ) : (
        <div className="text-[32px] font-medium leading-9 tracking-[-0.02em] text-muted">No winner yet</div>
      )}
      <ul className="grid text-[15px] leading-5">
        <li className="flex items-center gap-3 border-t border-line py-3 first:border-t-0"><span className="h-2 w-2 shrink-0 rounded-full bg-coral-mark" aria-hidden />{vetoed} cheaper {vetoed === 1 ? "bid" : "bids"} vetoed, each with its source</li>
        <li className="flex items-center gap-3 border-t border-line py-3"><span className="h-2 w-2 shrink-0 rounded-full bg-live" aria-hidden />{out} {out === 1 ? "offer" : "offers"} out of the ranking: ineligible, refused or blocked</li>
        <li className="flex items-center gap-3 border-t border-line py-3"><span className="h-2 w-2 shrink-0 rounded-full bg-pulse" aria-hidden />Stripe test mode. No real money moved.</li>
      </ul>
    </div>
  );
}
