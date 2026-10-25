"use client";
// Home (#448 step 2, reworked on Vidyut's feedback): the secure agentic marketplace, with depth and a little pulse that leads
// into the floor. One animated gradient zone (the hero), flat sections, a gradient band that descends into the dark floor,
// then back to light for payment. Numbers are labelled; nothing on this page is a made-up deal.

import Link from "next/link";
import { useMemo, type ReactNode } from "react";
import { useSpacetimeDB, useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { BrandMark } from "@/components/BrandMark";
import { FloorMini } from "@/components/FloorMini";
import { OriginChip, README_URL, StatusPill } from "@/components/ui";
import { toDate } from "@/lib/stdb";
import { BRAND, SHIELD, SHIELD_LINE, TAGLINE } from "@/lib/brand";

// Measured results, copied from data/scoreboard.json (Oct 24 run) and the README. Update when the scoreboard is regenerated.
const PROOF: { value: string; label: string; origin: "SIM" | "MIRROR" | "LIVE" }[] = [
  { value: "39 of 39", label: "fit checks right", origin: "SIM" },
  { value: "13 of 20", label: `held-out attacks stopped by ${SHIELD}`, origin: "SIM" },
  { value: "9 of 10", label: "voice attacks denied", origin: "SIM" },
];

const STEPS: { title: string; text: string }[] = [
  { title: "State a goal", text: "A part, a price cap and a date. Your agent takes it from there." },
  { title: "Sealed bids", text: "Seller agents bid blind. No one sees your cap or another bid." },
  { title: "Referee ranks", text: `One rule ranks every bid. ${SHIELD} and the fit checker throw out the bad ones.` },
  { title: "Approve by phone", text: "Above your allowance, we call you. Only the code on your screen pays." },
];

// Ticker lines while the market has no events yet. Each is labelled SIM on screen.
const SAMPLE_TICKER = ["Round opened: GPU", "4 bids sealed", `${SHIELD}: 1 listing blocked`, "Fit confirmed, 304 mm", "Referee: ranked", "Approved by phone", "Paid: test mode"];

export default function Home() {
  const conn = useSpacetimeDB();
  const [events] = useTable(tables.floorEvent);
  const ticker = useMemo(() => {
    const live = [...events].sort((a, b) => (a.id < b.id ? 1 : -1)).slice(0, 12).map((e) => ({ text: e.label, origin: e.origin, at: toDate(e.at) }));
    return live.length >= 4 ? live : SAMPLE_TICKER.map((text) => ({ text, origin: "SIM", at: null as Date | null }));
  }, [events]);

  return (
    <div className="-mx-4 grid grid-cols-[minmax(0,1fr)]">
      {/* 1. Hero: the one animated gradient zone. */}
      <section className="relative overflow-hidden px-4">
        <div className="fm-orb fm-orb-a left-[-8%] top-[-20%] h-[420px] w-[520px] bg-[rgba(34,211,238,0.28)]" aria-hidden />
        <div className="fm-orb fm-orb-b right-[-6%] top-[10%] h-[360px] w-[420px] bg-[rgba(30,78,216,0.16)]" aria-hidden />
        <div className="relative mx-auto grid max-w-[1120px] items-center gap-10 py-16 md:px-4 md:py-28 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
          <div>
            <span className="inline-flex items-center gap-2 text-[13px] font-medium uppercase tracking-[0.08em] text-ink-2">
              <span className="dot text-live" aria-hidden /> {conn.isActive ? "Market live" : "Sandbox"}
            </span>
            <h1 className="mt-5 text-[40px] font-medium leading-[44px] tracking-[-0.025em] text-balance md:text-[60px] md:leading-[64px] md:tracking-[-0.03em]">
              The secure agentic marketplace.
            </h1>
            <p className="mt-5 max-w-[36ch] text-[18px] leading-[27px] text-ink-2 md:text-[20px] md:leading-[30px]">
              Where buyers and sellers thrive. {SHIELD_LINE}
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/start" className="btn inline-flex min-h-12 items-center rounded-xl bg-pulse px-6 text-[17px] font-medium text-pulse-ink hover:shadow-card">Start a goal</Link>
              <Link href="/floor" className="btn inline-flex min-h-12 items-center rounded-xl bg-surface px-6 text-[17px] font-medium text-ink shadow-ring hover:bg-surface-2">Watch the floor</Link>
            </div>
          </div>
          <FloorMini className="rise" />
        </div>
      </section>

      {/* 2. Proof strip with the honesty footnote. */}
      <section aria-label="Measured results" className="border-t border-line px-4">
        <div className="mx-auto grid max-w-[1120px] gap-6 py-14 md:px-4 md:py-20">
          <div className="grid grid-cols-3 gap-4 md:gap-8">
            {PROOF.map((p) => (
              <div key={p.value} className="grid gap-1.5">
                <span className="text-[28px] font-medium leading-8 tracking-[-0.02em] tabular-nums md:text-[48px] md:leading-[52px]">{p.value}</span>
                <span className="text-[13px] leading-[18px] text-muted md:text-[15px] md:leading-5">{p.label}</span>
                <span><OriginChip origin={p.origin} /></span>
              </div>
            ))}
          </div>
          <p className="text-[13px] leading-[18px] text-muted">Test identities and sandbox payments. Every number on this site carries LIVE, MIRROR or SIM.</p>
        </div>
      </section>

      {/* 3. How it works: four steps, one line each. */}
      <section aria-labelledby="how" className="border-t border-line px-4">
        <div className="mx-auto max-w-[1120px] py-14 md:px-4 md:py-24">
          <h2 id="how" className="text-[28px] font-medium leading-[34px] tracking-[-0.015em] md:text-[40px] md:leading-[44px]">How it works</h2>
          <ol className="mt-8 grid gap-3 md:mt-12 md:grid-cols-4 md:gap-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="card grid gap-3 p-5 md:p-6">
                <span className="font-mono text-[12px] uppercase tracking-[0.08em] text-muted">Step 0{i + 1}</span>
                <span className="text-[17px] font-semibold leading-[22px]">{s.title}</span>
                <span className="text-[15px] leading-5 text-ink-2">{s.text}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* 4. The descent: light to ink, with the ticker of market events. */}
      <section aria-label="Recent market events" className="relative overflow-hidden bg-[linear-gradient(180deg,var(--color-canvas)_0%,var(--color-floor-bg)_100%)] py-12">
        <div className="flex w-max gap-3 whitespace-nowrap fm-ticker">
          {[...ticker, ...ticker].map((t, i) => (
            <span key={i} className="inline-flex h-9 items-center gap-2 rounded-full border border-[rgba(214,235,253,0.19)] bg-[rgba(11,27,43,0.55)] px-4 font-mono text-[12px] text-floor-line backdrop-blur">
              {t.text} <OriginChip origin={t.origin} />
            </span>
          ))}
        </div>
      </section>

      {/* 5 and 6. The floor, and the two guards, on ink. */}
      <section aria-labelledby="floor" className="bg-floor-bg px-4 text-floor-line">
        <div className="mx-auto grid max-w-[1120px] gap-12 py-16 md:px-4 md:py-24">
          <div className="grid items-center gap-10 lg:grid-cols-[0.95fr_1.05fr] lg:gap-16">
            <FloorMini />
            <div>
              <span className="inline-flex items-center gap-2 text-[13px] font-medium uppercase tracking-[0.08em] text-ghost-1"><span className="dot text-shield" aria-hidden /> The floor</span>
              <h2 id="floor" className="mt-4 text-[32px] font-medium leading-[36px] tracking-[-0.02em] md:text-[48px] md:leading-[52px]">Every round, played live.</h2>
              <p className="mt-4 max-w-[40ch] text-[17px] leading-[26px] text-ghost-1">Your agent eats the worst offer each round. Every move on the floor is a market row.</p>
              <Link href="/floor" className="btn mt-7 inline-flex min-h-12 items-center gap-2 rounded-xl bg-floor-line px-6 text-[17px] font-medium text-floor-bg">Watch the floor <span aria-hidden>→</span></Link>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <DarkCard eyebrow={SHIELD} title="Fishy listings never reach your agent.">Every listing and message is screened first. One that hides instructions or swaps the payee is blocked, with the rules that fired.</DarkCard>
            <DarkCard eyebrow="Referee" title="One rule ranks every bid.">Sealed bids, one flat fee, no pay for rank. The fit checker vetoes a part that does not fit, with its source.</DarkCard>
          </div>
        </div>
      </section>

      {/* 7. Payment: back to light. */}
      <section aria-labelledby="pay" className="bg-[linear-gradient(180deg,var(--color-floor-bg)_0%,var(--color-canvas)_18%)] px-4">
        <div className="mx-auto grid max-w-[1120px] gap-8 py-20 md:px-4 md:py-28 lg:grid-cols-[1fr_1fr] lg:items-center">
          <div>
            <h2 id="pay" className="text-[32px] font-medium leading-[36px] tracking-[-0.02em] md:text-[48px] md:leading-[52px]">Nothing pays without you.</h2>
            <p className="mt-4 max-w-[40ch] text-[17px] leading-[26px] text-ink-2">Above your allowance, we call. You say the code on your screen. Then a test charge and a receipt, one per part.</p>
          </div>
          <div className="card grid gap-4 p-6">
            <div className="flex flex-wrap gap-2">
              <StatusPill tone="live" pulse>Calling you</StatusPill>
              <StatusPill tone="good">Approved</StatusPill>
              <StatusPill tone="good">Paid</StatusPill>
              <StatusPill tone="caution">Test mode</StatusPill>
            </div>
            <div className="rounded-xl bg-surface-2 px-4 py-4 text-center">
              <div className="mb-1 text-[12px] font-medium uppercase tracking-[0.06em] text-muted">Say this, then &quot;approve&quot;</div>
              <div className="font-mono text-[32px] font-medium leading-9 tracking-[0.04em]">word · pair</div>
            </div>
            <p className="text-[13px] leading-[18px] text-muted">One use, one deal, this screen only. Silence or a wrong code pays nothing.</p>
          </div>
        </div>
      </section>

      {/* 8. Sellers, closing, footer. */}
      <section aria-label="For sellers" className="border-t border-line px-4">
        <div className="mx-auto flex max-w-[1120px] flex-wrap items-center justify-between gap-5 py-14 md:px-4 md:py-20">
          <p className="text-[22px] font-medium leading-7 tracking-[-0.015em] md:text-[28px] md:leading-[34px]">Sell here. Your agent bids, never below your floor.</p>
          <Link href="/sell" className="btn inline-flex min-h-12 items-center rounded-xl bg-surface px-6 text-[17px] font-medium text-ink shadow-ring hover:bg-surface-2">List your shop</Link>
        </div>
      </section>
      <footer className="border-t border-line px-4">
        <div className="mx-auto flex max-w-[1120px] flex-wrap items-center gap-x-6 gap-y-4 py-10 pb-20 text-[15px] text-muted md:px-4">
          <span className="inline-flex items-center gap-2 font-medium text-ink"><BrandMark /> {BRAND}</span>
          <span>{TAGLINE}</span>
          <StatusPill tone="caution">Test mode: no real money moves</StatusPill>
          <a href="https://github.com/vs-githjk/cal-hacks-2026" target="_blank" rel="noreferrer" className="font-medium text-pulse">GitHub</a>
          <a href={README_URL} target="_blank" rel="noreferrer" className="font-medium text-pulse">What is real</a>
        </div>
      </footer>
    </div>
  );
}

function DarkCard({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return (
    <div className="relative grid gap-2 rounded-2xl border border-[rgba(214,235,253,0.19)] bg-floor-ground p-6">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[rgba(255,255,255,0.08)]" aria-hidden />
      <span className="font-mono text-[12px] uppercase tracking-[0.08em] text-shield">{eyebrow}</span>
      <span className="text-[20px] font-semibold leading-6 tracking-[-0.01em]">{title}</span>
      <span className="text-[15px] leading-[22px] text-ghost-1">{children}</span>
    </div>
  );
}
