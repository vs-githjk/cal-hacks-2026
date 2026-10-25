"use client";
// Home (#448 step 2): minimal. Hero, one deal card, three measured numbers, four steps, one seller line, a footer.
// Every fact that used to be a paragraph is one tap away: the step details, /floor, the README.

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { BrandMark, FishGlyph } from "@/components/BrandMark";
import { bidsFromRows, latestRound, roundTitle, winningBid, type RankedBid } from "@/lib/screens";
import { rankedBids as SAMPLE_BIDS, receipt as SAMPLE_RECEIPT } from "@/lib/sample";
import { BRAND, SHIELD, SHIELD_LINE, TAGLINE } from "@/lib/brand";
import { OriginChip, README_URL, StatusPill, money } from "@/components/ui";

// Measured results, copied from data/scoreboard.json (Oct 24 run) and the README. Update when the scoreboard is regenerated.
const PROOF: { value: string; label: string }[] = [
  { value: "39 of 39", label: "fit checks right" },
  { value: "13 of 20", label: `attacks stopped by ${SHIELD}` },
  { value: "9 of 10", label: "voice attacks denied" },
];

const STEPS: { title: string; detail: string; icon: ReactNode }[] = [
  { title: "State a goal", detail: "A part, a price cap and a date. Your agent does the rest.", icon: <GoalIcon /> },
  { title: "Sealed rounds", detail: `Seller agents bid blind. ${SHIELD} throws out fishy listings. A checker confirms the fit.`, icon: <SealedIcon /> },
  { title: "Say the code", detail: "Above your allowance, we call you. Only the code on your screen approves.", icon: <PhoneIcon /> },
  { title: "Get a receipt", detail: "A Stripe test charge and a signed receipt, one per part.", icon: <ReceiptIcon /> },
];

/** Home: the first screen a visitor sees. The deal card and the numbers are real; everything else is one line. */
export default function Home() {
  const conn = useSpacetimeDB();
  const [rounds] = useTable(tables.round);
  const [results] = useTable(tables.roundResult);
  const [events] = useTable(tables.floorEvent);
  const r = latestRound(rounds);
  const bids = useMemo(() => bidsFromRows(results, events, r?.id), [results, events, r]);
  const liveWin = r?.state === "closed" ? winningBid(bids) : undefined;

  return (
    <div className="mx-auto grid w-full max-w-[1120px] grid-cols-[minmax(0,1fr)] md:px-4">
      <section className="grid min-h-[calc(100vh-140px)] items-center gap-10 py-14 md:py-24 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
        <div>
          <h1 className="text-[40px] font-medium leading-[44px] tracking-[-0.025em] text-balance md:text-[64px] md:leading-[68px] md:tracking-[-0.03em]">
            Your agent shops. <span className="text-muted">You approve.</span>
          </h1>
          <p className="mt-5 max-w-[34ch] text-[17px] leading-[26px] text-ink-2 md:text-[20px] md:leading-[30px]">
            Sellers compete for your PC parts. {SHIELD_LINE}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/start" className="btn inline-flex min-h-12 items-center rounded-xl bg-pulse px-6 text-[17px] font-medium text-pulse-ink hover:shadow-card">Start a goal</Link>
            <Link href="/floor" className="btn inline-flex min-h-12 items-center rounded-xl bg-surface px-6 text-[17px] font-medium text-ink shadow-ring hover:bg-surface-2">Watch the floor</Link>
          </div>
        </div>
        <DealCard win={liveWin ?? winningBid(SAMPLE_BIDS)} part={liveWin ? (roundTitle(r!.id) ?? "") : (SAMPLE_RECEIPT.item ?? "")} live={!!liveWin} connected={conn.isActive} />
      </section>

      <section aria-label="Measured results" className="grid grid-cols-3 gap-4 border-t border-line py-14 md:gap-8 md:py-24">
        {PROOF.map((p) => (
          <div key={p.value} className="grid gap-1">
            <span className="text-[28px] font-medium leading-8 tracking-[-0.02em] tabular-nums md:text-[48px] md:leading-[52px]">{p.value}</span>
            <span className="text-[13px] leading-[18px] text-muted md:text-[15px] md:leading-5">{p.label}</span>
          </div>
        ))}
      </section>

      <section aria-labelledby="how" className="border-t border-line py-14 md:py-24">
        <h2 id="how" className="text-[28px] font-medium leading-[34px] tracking-[-0.015em] md:text-[40px] md:leading-[44px]">How it works</h2>
        <ol className="mt-8 grid gap-3 md:mt-12 md:grid-cols-4 md:gap-4">
          {STEPS.map((s, i) => <Step key={s.title} n={i + 1} {...s} />)}
        </ol>
      </section>

      <section aria-label="For sellers" className="flex flex-wrap items-center justify-between gap-5 border-t border-line py-14 md:py-24">
        <p className="text-[22px] font-medium leading-7 tracking-[-0.015em] md:text-[28px] md:leading-[34px]">Sell here. Your agent bids, never below your floor.</p>
        <Link href="/sell" className="btn inline-flex min-h-12 items-center rounded-xl bg-surface px-6 text-[17px] font-medium text-ink shadow-ring hover:bg-surface-2">List your shop</Link>
      </section>

      <footer className="flex flex-wrap items-center gap-x-6 gap-y-4 border-t border-line py-10 pb-20 text-[15px] text-muted">
        <span className="inline-flex items-center gap-2 font-medium text-ink"><BrandMark /> {BRAND}</span>
        <span>{TAGLINE}</span>
        <StatusPill tone="caution">Test mode: no real money moves</StatusPill>
        <a href="https://github.com/vs-githjk/cal-hacks-2026" target="_blank" rel="noreferrer" className="font-medium text-pulse">GitHub</a>
        <a href={README_URL} target="_blank" rel="noreferrer" className="font-medium text-pulse">What is real</a>
      </footer>
    </div>
  );
}

/** One deal: part, price, three chips. From the latest closed round, or the recorded sample labelled SIM. */
function DealCard({ win, part, live, connected }: { win: RankedBid | undefined; part: string; live: boolean; connected: boolean }) {
  return (
    <div className="glass rise relative grid gap-5 overflow-hidden p-6 md:p-8">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[12px] font-medium uppercase tracking-[0.04em] text-muted">{live ? "Latest deal" : "Sample deal"}</span>
        {live ? <StatusPill tone="live" pulse={connected}>LIVE</StatusPill> : <OriginChip origin="SIM" />}
      </div>
      {win ? (
        <>
          <div className="grid gap-1">
            <span className="text-[44px] font-medium leading-[48px] tracking-[-0.02em] tabular-nums md:text-[56px] md:leading-[60px]">{money(win.landed)}</span>
            <span className="text-[17px] leading-6 text-ink-2">{[part, win.seller, win.condition].filter(Boolean).join(" · ")}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusPill tone="good">Fit ✓</StatusPill>
            <StatusPill tone="referee">CRS verified</StatusPill>
            <StatusPill tone="caution">Test mode</StatusPill>
            <OriginChip origin={win.origin} />
          </div>
        </>
      ) : (
        <span className="text-[28px] font-medium leading-8 text-muted">No deal yet</span>
      )}
      <span className="pointer-events-none absolute -right-4 -top-4 text-ink opacity-[0.06]" aria-hidden><FishGlyph size={120} /></span>
    </div>
  );
}

/** A step: icon, three words, and the one-line detail on tap. */
function Step({ n, title, detail, icon }: { n: number; title: string; detail: string; icon: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="card p-5 md:p-6">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="grid w-full gap-4 text-left">
        <span className="flex items-center justify-between">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-surface-2 text-ink">{icon}</span>
          <span className="font-mono text-[12px] text-muted">0{n}</span>
        </span>
        <span className="flex items-center justify-between gap-2 text-[17px] font-semibold leading-[22px]">
          {title}
          <span className={`text-muted transition-transform ${open ? "rotate-45" : ""}`} aria-hidden>+</span>
        </span>
      </button>
      {open && <p className="mt-3 text-[15px] leading-5 text-ink-2">{detail}</p>}
    </li>
  );
}

function Icon({ children }: { children: ReactNode }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="h-6 w-6">{children}</svg>;
}
function GoalIcon() { return <Icon><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3.5" /></Icon>; }
function SealedIcon() { return <Icon><rect x="4" y="9" width="16" height="11" rx="2" /><path d="M6 9 12 4l6 5" /></Icon>; }
function PhoneIcon() { return <Icon><path d="M7 4h3l1.5 4-2 1.5a11 11 0 0 0 5 5L16 12.5l4 1.5v3a2 2 0 0 1-2.2 2A14 14 0 0 1 5 6.2 2 2 0 0 1 7 4Z" /></Icon>; }
function ReceiptIcon() { return <Icon><path d="M6 3h12v18l-3-2-3 2-3-2-3 2Z" /><path d="M9 8h6M9 12h6" /></Icon>; }
