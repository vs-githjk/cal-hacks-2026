"use client";
// web/src/components/Corral.tsx
// The auction corral: the one interactive scene the home page is built around. A buyer agent posts a goal,
// sellers reveal sealed bids, the advocate rules on each, the winner is picked. Tokens only, no literal colors.
// Falls back to the sample run (lib/sample.ts) when no round has bids yet, labelled SIM like every other sample card.

import { useEffect, useMemo, useState } from "react";
import type { RankedBid } from "@/lib/screens";
import { rankedBids as sampleBids, goal as sampleGoal } from "@/lib/sample";
import { OriginChip, Tag, Verdict, money } from "@/components/ui";
import { SHIELD } from "@/lib/brand";

const STEPS = ["Request", "Offers", "Review", "Selected"] as const;
const STEP_MS = 2600;

function pickSample(): RankedBid[] {
  const byName = (n: string) => sampleBids.find((b) => b.seller === n)!;
  return [byName("Shady Sam's Deals"), byName("Fair Price PC"), byName("Best Buy")];
}

export function Corral({ bids, goalLine }: { bids: RankedBid[]; goalLine: string }) {
  const sample = bids.length === 0;
  const sellers = useMemo(() => (sample ? pickSample() : bids.slice(0, 3)), [sample, bids]);
  const bubble = sample ? sampleGoal.text.split(",")[0]! : goalLine;

  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(() => typeof window === "undefined" || !window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  useEffect(() => {
    if (!playing || step >= STEPS.length - 1) return;
    const t = setTimeout(() => {
      setStep((s) => {
        const next = s + 1;
        if (next >= STEPS.length - 1) setPlaying(false);
        return next;
      });
    }, STEP_MS);
    return () => clearTimeout(t);
  }, [playing, step]);

  const n = sellers.length;
  const xFor = (i: number) => (n === 1 ? 480 : 300 + (i * (360 / Math.max(1, n - 1))));

  return (
    <section aria-label="Agent auction" className="card overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-line px-5 py-4">
        <p className="text-[16px] font-semibold text-ink">Agent auction</p>
        {sample && <OriginChip origin="SIM" label="SIM example" />}
      </div>

      <svg viewBox="0 0 960 420" role="img" aria-label={`${bubble}. ${sellers.length} sellers bidding.`} className="block w-full">
        <defs>
          <linearGradient id="hatGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--ink)" />
            <stop offset="100%" stopColor="var(--ink-2)" />
          </linearGradient>
          <linearGradient id="groundGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--soft)" stopOpacity="0" />
            <stop offset="100%" stopColor="var(--soft)" stopOpacity="0.9" />
          </linearGradient>
        </defs>

        <path d="M0 190 L140 100 L260 190 Z" fill="var(--line)" opacity="0.55" />
        <path d="M670 190 L800 90 L960 190 Z" fill="var(--line)" opacity="0.55" />
        <rect x="0" y="248" width="960" height="172" fill="url(#groundGrad)" />
        <line x1="20" y1="248" x2="940" y2="248" stroke="var(--line-2)" strokeWidth="2.5" />
        {Array.from({ length: 12 }, (_, i) => 40 + i * 80).map((x) => (
          <line key={x} x1={x} y1="236" x2={x} y2="260" stroke="var(--line-2)" strokeWidth="2.5" />
        ))}

        {/* Buyer agent, centered on a podium */}
        <g className={step >= 2 ? "torch" : undefined} style={{ transformOrigin: "480px 180px" }}>
          <Figure x={480} y={148} label="Buyer agent" scale={1.2} />
        </g>
        <rect x="408" y="188" width="144" height="60" rx="8" fill="none" stroke="var(--line-2)" strokeWidth="2.5" />
        {bubble && (
          <g className="transition-opacity duration-500" opacity={step === 0 ? 1 : 0.5}>
            <rect x="290" y="24" width="380" height="52" rx="18" fill="var(--panel)" stroke="var(--line)" strokeWidth="1.5" style={{ filter: "drop-shadow(0 3px 6px rgba(24,19,13,0.1))" }} />
            <polygon points="460,80 480,80 466,96" fill="var(--panel)" stroke="var(--line)" strokeWidth="1.5" />
            <text x="480" y="57" textAnchor="middle" className="fill-ink" fontSize="16" fontWeight="600">
              {bubble.length > 48 ? `${bubble.slice(0, 46)}…` : bubble}
            </text>
          </g>
        )}

        {/* The Smell Test (left) and the advocate (right), flanking the corral */}
        <Figure x={120} y={172} label={SHIELD} scale={1.05} />
        <Figure x={840} y={172} label="Advocate" scale={1.05} />

        {/* Sellers */}
        {sellers.map((b, i) => {
          const x = xFor(i);
          const vetoed = step >= 2 && b.recommendation === "veto";
          const won = step >= 3 && b.won;
          const faded = step >= 3 && !b.won;
          return (
            <g key={b.seller} opacity={vetoed || faded ? 0.4 : 1} className="transition-opacity duration-500">
              <Figure x={x} y={268} label={`Seller ${i + 1}`} scale={1.05} />
              <g
                className="transition-[opacity,transform] duration-500"
                opacity={step >= 1 ? 1 : 0}
                transform={step >= 1 ? `translate(${x} 364) scale(${won ? 1.1 : 1})` : `translate(${x} 378) scale(1)`}
                style={{ transformOrigin: `${x}px 388px`, filter: "drop-shadow(0 3px 5px rgba(24,19,13,0.12))" }}
              >
                <rect x={-78} y="0" width="156" height="56" rx="14" fill="var(--panel)" stroke={won ? "var(--mint)" : "var(--line)"} strokeWidth={won ? 2.5 : 1.5} />
                <text x="0" y="24" textAnchor="middle" className="fill-ink" fontSize="18" fontWeight="700" style={{ textDecoration: vetoed ? "line-through" : undefined }}>
                  {b.landed > 0 ? money(b.landed) : "·"}
                </text>
                <text x="0" y="43" textAnchor="middle" fontSize="12" className="fill-muted" fontWeight="600">
                  {vetoed ? "VETOED" : won ? "WINNER" : b.origin}
                </text>
              </g>
            </g>
          );
        })}
      </svg>

      {/* Verdict line: fills in once the review step runs */}
      <div className="flex min-h-[48px] flex-wrap items-center gap-x-5 gap-y-2 border-t border-line px-5 py-4 text-[15px]">
        {step >= 2 ? (
          sellers.map((b) => (
            <span key={b.seller} className="inline-flex items-center gap-2">
              <Verdict kind={b.recommendation === "veto" ? "veto" : b.won ? "buy" : "caution"}>{b.seller}</Verdict>
              {b.won && step >= 3 && <Tag>Winner</Tag>}
            </span>
          ))
        ) : (
          <span className="text-muted">Sellers bid sealed. Nobody sees another bid until the round closes.</span>
        )}
      </div>

      {/* Stepper and transport */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-soft/60 px-5 py-3.5">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Auction step">
          {STEPS.map((s, i) => (
            <button
              key={s}
              type="button"
              role="tab"
              aria-selected={step === i}
              onClick={() => {
                setStep(i);
                setPlaying(false);
              }}
              className={`btn rounded-full px-5 py-2.5 text-[15px] font-semibold ${step === i ? "bg-accent text-accent-ink shadow-[0_2px_8px_rgba(24,19,13,0.18)]" : "text-ink-2 hover:bg-panel"}`}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 text-[15px] text-ink-2">
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            disabled={step >= STEPS.length - 1}
            className="btn inline-flex items-center gap-1 rounded-full px-5 py-2.5 font-semibold hover:bg-panel disabled:opacity-40"
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            onClick={() => {
              setStep(0);
              setPlaying(true);
            }}
            className="btn inline-flex items-center gap-1 rounded-full px-5 py-2.5 font-semibold hover:bg-panel"
          >
            Replay
          </button>
        </div>
      </div>
    </section>
  );
}

function Figure({ x, y, label, scale = 1 }: { x: number; y: number; label: string; scale?: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`}>
      <ellipse cx="0" cy="55" rx="17" ry="4.5" fill="var(--ink)" opacity="0.14" />
      <path d="M-15 -7 Q0 -25 15 -7 L15 -3 L-15 -3 Z" fill="url(#hatGrad)" />
      <circle cx="0" cy="0" r="10" fill="var(--ink-2)" />
      <rect x="-7" y="9" width="14" height="27" rx="7" fill="var(--ink-2)" />
      <line x1="0" y1="17" x2="-13" y2="27" stroke="var(--ink-2)" strokeWidth="4" strokeLinecap="round" />
      <line x1="0" y1="17" x2="13" y2="27" stroke="var(--ink-2)" strokeWidth="4" strokeLinecap="round" />
      <line x1="-3" y1="35" x2="-10" y2="52" stroke="var(--ink-2)" strokeWidth="4.5" strokeLinecap="round" />
      <line x1="3" y1="35" x2="10" y2="52" stroke="var(--ink-2)" strokeWidth="4.5" strokeLinecap="round" />
      <text x="0" y="72" textAnchor="middle" fontSize="13" fontWeight="700" className="fill-ink-2">
        {label}
      </text>
    </g>
  );
}
