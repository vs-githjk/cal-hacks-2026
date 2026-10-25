"use client";
// Home (#448, round 3 of Vidyut's feedback): an aquarium hero, boxed numbers, the dashboard in miniature, four clean steps,
// the dark floor, approval and receipt, sellers, footer. No ticker, no gradient band. Every value is labelled; nothing is a made-up deal.

import Link from "next/link";
import type { ReactNode } from "react";
import { DashboardPreview } from "@/components/DashboardPreview";
import { FloorMini } from "@/components/FloorMini";
import { HomeMore } from "@/components/HomeMore";
import { ScrollProgress } from "@/components/ScrollProgress";
import { Reveal } from "@/components/Reveal";
import { OriginChip, README_URL, StatusPill } from "@/components/ui";
import { proofStats } from "@/lib/scoreboard";
import { BRAND, SHIELD } from "@/lib/brand";

// Measured results, computed from data/scoreboard.json (lib/scoreboard.ts). A test keeps the fixture copy identical to the file.
const PROOF = proofStats(SHIELD);

const STEPS: { title: string; text: string; icon: ReactNode }[] = [
  { title: "State a goal", text: "A part, a price cap and a date. Your agent hunts.", icon: <GoalIcon /> },
  { title: "Sealed bids", text: "Seller agents bid blind. No one sees your cap or another bid.", icon: <SealedIcon /> },
  { title: "Referee ranks", text: `One fixed rule, no pay for rank. ${SHIELD} screens first.`, icon: <RankIcon /> },
  { title: "Approve by phone", text: "Above your allowance we call you. Only your spoken code pays.", icon: <PhoneIcon /> },
];

const BUBBLES = [
  { left: "8%", size: 10, rise: "16s", delay: "0s" },
  { left: "22%", size: 6, rise: "13s", delay: "-5s" },
  { left: "41%", size: 14, rise: "19s", delay: "-9s" },
  { left: "63%", size: 8, rise: "15s", delay: "-2s" },
  { left: "78%", size: 12, rise: "18s", delay: "-11s" },
  { left: "91%", size: 7, rise: "14s", delay: "-7s" },
];

export default function Home() {
  return (
    <div className="-mx-4 -mb-[72px] grid grid-cols-[minmax(0,1fr)]">
      <ScrollProgress />

      {/* 1. Hero: the aquarium. */}
      <section className="relative -mt-[84px] overflow-hidden bg-[linear-gradient(180deg,#cfe4fb_0%,#d9eafc_45%,#e7f0fa_80%,#eef3f8_100%)] px-4 pt-[84px] max-sm:-mt-[132px] max-sm:pt-[132px]">
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-48 bg-[linear-gradient(180deg,rgba(238,243,248,0)_0%,rgba(238,243,248,0.6)_55%,#eef3f8_100%)]" aria-hidden />
        <div className="fm-caustic" aria-hidden />
        <div className="fm-orb fm-orb-a left-[-8%] top-[-20%] h-[420px] w-[520px] bg-[rgba(255,255,255,0.55)]" aria-hidden />
        <div className="fm-orb fm-orb-b right-[-6%] top-[0%] h-[360px] w-[420px] bg-[rgba(30,78,216,0.14)]" aria-hidden />
        {BUBBLES.map((b) => (
          <span key={b.left} className="fm-bubble" style={{ left: b.left, width: b.size, height: b.size, ["--rise" as string]: b.rise, ["--delay" as string]: b.delay }} aria-hidden />
        ))}
        <div className="relative z-[2] mx-auto grid max-w-[1120px] items-center gap-10 pb-16 pt-14 md:px-4 md:pb-24 md:pt-20 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
          <div>
            <h1 className=" text-[40px] font-semibold leading-[44px] tracking-[-0.03em] text-balance md:text-[62px] md:leading-[66px] md:tracking-[-0.035em]">
              The <span className="fm-headline-accent">secure agentic</span> marketplace.
            </h1>
            <p className="mt-5 max-w-[36ch] text-[18px] leading-[27px] text-ink-2 md:text-[20px] md:leading-[30px]">
              Where buyers and sellers thrive.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/start" className="btn fm-btn fm-grad inline-flex min-h-12 items-center rounded-2xl px-6 text-[17px] font-medium text-white transition-transform motion-safe:hover:-translate-y-0.5">Start a goal</Link>
              <Link href="/floor" className="btn fm-ghostbtn inline-flex min-h-12 items-center rounded-2xl px-6 text-[17px] font-medium text-ink transition-transform motion-safe:hover:-translate-y-0.5">Watch the floor</Link>
            </div>
          </div>
          <FloorMini className="rise" />
        </div>
      </section>

      {/* 3. The product: the dashboard in miniature. */}
      <section aria-labelledby="dash" className="px-4">
        <Reveal className="mx-auto grid max-w-[1120px] gap-6 pb-10 pt-4 md:px-4 md:pb-16 md:pt-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h2 id="dash" className="text-[28px] font-semibold leading-[34px] tracking-[-0.02em] md:text-[40px] md:leading-[44px] md:tracking-[-0.025em]">Your dashboard, in one glance.</h2>
            <Link href="/start" className="inline-flex min-h-11 items-center gap-1.5 text-[15px] font-medium text-pulse">Open yours <span aria-hidden>→</span></Link>
          </div>
          <DashboardPreview />
        </Reveal>
      </section>

      {/* 4. How it works: four steps on one line. */}
      <section aria-labelledby="how" className="relative px-4 py-[136px] text-floor-line [background:linear-gradient(180deg,#eef3f8_0px,#e8edf2_15px,#d6dde3_30px,#bdc4cc_45px,#9ea7b0_60px,#7c8792_75px,#5b6773_90px,#3c4a57_105px,#233140_120px,#112131_135px,#0b1b2b_150px,#0b1b2b_calc(100%-150px),#112131_calc(100%-135px),#233140_calc(100%-120px),#3c4a57_calc(100%-105px),#5b6773_calc(100%-90px),#7c8792_calc(100%-75px),#9ea7b0_calc(100%-60px),#bdc4cc_calc(100%-45px),#d6dde3_calc(100%-30px),#e8edf2_calc(100%-15px),#eef3f8_calc(100%-0px))]">
        <Reveal className="mx-auto max-w-[1120px] md:px-4">
          <h2 id="how" className="text-[28px] font-semibold leading-[34px] tracking-[-0.02em] md:text-[40px] md:leading-[44px] md:tracking-[-0.025em]">How it works</h2>
          <ol className="relative mt-8 grid gap-3 md:grid-cols-4 md:gap-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="fm-glass-dark relative grid grid-cols-[44px_1fr] gap-x-3.5 gap-y-1 rounded-2xl p-4 md:grid-cols-1 md:gap-3 md:p-5">
                <span className="grid h-11 w-11 place-items-center rounded-xl bg-white/10 text-white md:h-12 md:w-12">{s.icon}</span>
                <span className="absolute right-4 top-4 grid h-6 w-6 place-items-center rounded-full bg-white font-mono text-[11px] text-ink md:right-5 md:top-5">{i + 1}</span>
                <div className="col-start-2 md:col-start-1">
                  <p className="text-[16px] font-semibold leading-5">{s.title}</p>
                  <p className="mt-1 text-[13px] leading-[18px] text-ghost-1">{s.text}</p>
                </div>
              </li>
            ))}
          </ol>
          <details className="group mt-6">
            <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 text-[15px] font-medium text-shield [&::-webkit-details-marker]:hidden">
              More: the five beats, the auction, this round in numbers <span className="text-ghost-1 transition-transform group-open:rotate-45" aria-hidden>+</span>
            </summary>
            <div className="text-ink"><HomeMore /></div>
          </details>
        </Reveal>
      </section>

      {/* 4b. Proof: three measured numbers with their caveats, once the visitor knows what the product is. */}
      <section aria-label="Measured results" className="px-4">
        <Reveal className="mx-auto max-w-[1120px] py-6 md:px-4 md:py-10">
          <h2 className="mb-6 text-[28px] font-semibold leading-[34px] tracking-[-0.02em] md:text-[40px] md:leading-[44px] md:tracking-[-0.025em]">Measured, not promised.</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {PROOF.map((p) => (
              <div key={p.value} className="fm-tile rounded-2xl p-5 md:p-6">
                <div className="flex items-start justify-between gap-3">
                  <span className={`text-[36px] font-medium leading-10 tracking-[-0.02em] tabular-nums md:text-[44px] md:leading-[48px] ${p.measured ? "" : "text-muted"}`}>{p.value}</span>
                  <OriginChip origin="SIM" />
                </div>
                <p className="mt-2 text-[15px] font-medium leading-5">{p.label}</p>
                <p className="mt-1 text-[13px] leading-[18px] text-muted">{p.caveat}</p>
              </div>
            ))}
          </div>
          <p className="mt-4 text-[13px] leading-[18px] text-muted">Sandbox only. <a href={README_URL} target="_blank" rel="noreferrer" className="font-medium text-pulse">What is real</a></p>
        </Reveal>
      </section>

      {/* 5 and 6. The floor, and the two guards, on ink. */}
      <section aria-labelledby="floor" className="relative px-4 py-[136px] text-floor-line [background:linear-gradient(180deg,#eef3f8_0px,#e8edf2_15px,#d6dde3_30px,#bdc4cc_45px,#9ea7b0_60px,#7c8792_75px,#5b6773_90px,#3c4a57_105px,#233140_120px,#112131_135px,#0b1b2b_150px,#0b1b2b_calc(100%-150px),#112131_calc(100%-135px),#233140_calc(100%-120px),#3c4a57_calc(100%-105px),#5b6773_calc(100%-90px),#7c8792_calc(100%-75px),#9ea7b0_calc(100%-60px),#bdc4cc_calc(100%-45px),#d6dde3_calc(100%-30px),#e8edf2_calc(100%-15px),#eef3f8_calc(100%-0px))]">
        <Reveal className="mx-auto grid max-w-[1120px] gap-10 md:px-4">
          <div className="grid items-center gap-8 lg:grid-cols-[1fr_auto] lg:gap-16">
            <div>
              <span className="inline-flex items-center gap-2 text-[13px] font-medium uppercase tracking-[0.08em] text-ghost-1"><span className="dot text-[#4f8df7]" aria-hidden /> The floor</span>
              <h2 id="floor" className="mt-4 text-[32px] font-medium leading-[36px] tracking-[-0.02em] md:text-[48px] md:leading-[52px]">Every round, played live.</h2>
              <p className="mt-4 max-w-[40ch] text-[17px] leading-[26px] text-ghost-1">Your agent eats the worst offer each round. Every move is a market row.</p>
            </div>
            <Link href="/floor" className="btn fm-btn inline-flex min-h-12 items-center gap-2 rounded-2xl bg-[linear-gradient(135deg,#f6fafd,#dbe9f5)] px-6 text-[17px] font-medium text-floor-bg transition-transform motion-safe:hover:-translate-y-0.5">Watch the floor <span aria-hidden>→</span></Link>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <DarkCard eyebrow={SHIELD} title={`${SHIELD} screens every listing first.`}>Hidden instructions or a swapped payee: blocked, with the rules that fired.</DarkCard>
            <DarkCard eyebrow="Referee" title="One rule ranks every bid.">Sealed bids, one flat fee, no pay for rank.</DarkCard>
          </div>
        </Reveal>
      </section>

      {/* 7. Payment. */}
      <section aria-labelledby="pay" className="px-4">
        <Reveal className="mx-auto grid max-w-[1120px] gap-8 pb-14 md:px-4 md:pb-20 lg:grid-cols-[1fr_1fr] lg:items-center">
          <div>
            <h2 id="pay" className="text-[32px] font-medium leading-[36px] tracking-[-0.02em] md:text-[48px] md:leading-[52px]">Above your allowance, nothing pays without you.</h2>
            <p className="mt-4 max-w-[40ch] text-[17px] leading-[26px] text-ink-2">We call. You say the code. Then a test charge and a receipt.</p>
          </div>
          <div className="fm-glass grid gap-4 rounded-[22px] p-6">
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
            <p className="text-[13px] leading-[18px] text-muted">One use, one deal. A wrong code pays nothing.</p>
          </div>
        </Reveal>
      </section>

      {/* 8. Sellers, footer. */}
      <section aria-label="For sellers" className="border-t border-line px-4">
        <div className="mx-auto flex max-w-[1120px] flex-wrap items-center justify-between gap-5 py-12 md:px-4 md:py-20">
          <p className="text-[22px] font-medium leading-7 tracking-[-0.015em] md:text-[28px] md:leading-[34px]">Sell here. Your agent bids, never below your floor.</p>
          <Link href="/sell" className="btn fm-ghostbtn inline-flex min-h-12 items-center rounded-2xl px-6 text-[17px] font-medium text-ink transition-transform motion-safe:hover:-translate-y-0.5">List your shop</Link>
        </div>
      </section>
      <footer className="border-t border-line px-4">
        <div className="mx-auto flex max-w-[1120px] flex-wrap items-center gap-x-5 gap-y-2 py-6 text-[13px] text-muted md:px-4">
          <span>&copy; 2026 {BRAND}</span>
          <Link href="/privacy" className="hover:text-ink">Privacy</Link>
          <Link href="/terms" className="hover:text-ink">Terms</Link>
          <span>Sandbox only: test cards, test identities, no real money.</span>
        </div>
      </footer>
    </div>
  );
}

function DarkCard({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return (
    <div className="fm-glass-dark grid gap-2 rounded-2xl p-6">
      <span className="font-mono text-[12px] uppercase tracking-[0.08em] text-shield">{eyebrow}</span>
      <span className="text-[20px] font-semibold leading-6 tracking-[-0.01em]">{title}</span>
      <span className="text-[15px] leading-[22px] text-ghost-1">{children}</span>
    </div>
  );
}

function Icon({ children }: { children: ReactNode }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="h-6 w-6">{children}</svg>;
}
function GoalIcon() { return <Icon><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3.5" /></Icon>; }
function SealedIcon() { return <Icon><rect x="4" y="9" width="16" height="11" rx="2" /><path d="M6 9 12 4l6 5" /></Icon>; }
function RankIcon() { return <Icon><path d="M5 19V10M12 19V5M19 19v-7" /></Icon>; }
function PhoneIcon() { return <Icon><path d="M7 4h3l1.5 4-2 1.5a11 11 0 0 0 5 5L16 12.5l4 1.5v3a2 2 0 0 1-2.2 2A14 14 0 0 1 5 6.2 2 2 0 0 1 7 4Z" /></Icon>; }
