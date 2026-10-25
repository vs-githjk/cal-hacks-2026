"use client";
// web/src/components/Corral.tsx
// The auction corral: the one interactive scene the home page is built around. A buyer agent posts a goal,
// sellers reveal sealed bids, the advocate rules on each, the winner is picked. Tokens only, no literal colors.
// Falls back to the sample run (lib/sample.ts) when no round has bids yet, labelled SIM like every other sample card.

import { useEffect, useMemo, useState } from "react";
import type { RankedBid } from "@/lib/screens";
import { rankedBids as sampleBids, goal as sampleGoal } from "@/lib/sample";
import { OriginChip, Tag, Verdict, money } from "@/components/ui";

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
      <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <p className="text-[13px] font-medium text-ink-2">Agent auction</p>
        {sample && <OriginChip origin="SIM" label="SIM example" />}
      </div>

      <svg viewBox="0 0 960 360" role="img" aria-label={`${bubble}. ${sellers.length} sellers bidding.`} className="block w-full">
        <path d="M0 160 L130 90 L240 160 Z" fill="var(--line)" opacity="0.5" />
        <path d="M680 160 L800 80 L960 160 Z" fill="var(--line)" opacity="0.5" />
        <line x1="20" y1="212" x2="940" y2="212" stroke="var(--line-2)" strokeWidth="2" />
        {Array.from({ length: 12 }, (_, i) => 40 + i * 80).map((x) => (
          <line key={x} x1={x} y1="202" x2={x} y2="222" stroke="var(--line-2)" strokeWidth="2" />
        ))}

        {/* Buyer agent, centered on a podium */}
        <g className={step >= 2 ? "torch" : undefined} style={{ transformOrigin: "480px 150px" }}>
          <Figure x={480} y={120} label="Buyer agent" />
        </g>
        <rect x="432" y="150" width="96" height="40" rx="4" fill="none" stroke="var(--line-2)" strokeWidth="2" />
        {bubble && (
          <g className="transition-opacity duration-500" opacity={step === 0 ? 1 : 0.45}>
            <rect x="330" y="26" width="300" height="40" rx="14" fill="var(--panel)" stroke="var(--line)" strokeWidth="1.5" />
            <polygon points="470,66 486,66 472,80" fill="var(--panel)" stroke="var(--line)" strokeWidth="1.5" />
            <text x="480" y="51" textAnchor="middle" className="fill-ink" fontSize="13" fontWeight="500">
              {bubble.length > 48 ? `${bubble.slice(0, 46)}…` : bubble}
            </text>
          </g>
        )}

        {/* Shield (left) and Advocate (right), flanking the corral */}
        <Figure x={120} y={150} label="Shield" small />
        <Figure x={840} y={150} label="Advocate" small />

        {/* Sellers */}
        {sellers.map((b, i) => {
          const x = xFor(i);
          const vetoed = step >= 2 && b.recommendation === "veto";
          const won = step >= 3 && b.won;
          const faded = step >= 3 && !b.won;
          return (
            <g key={b.seller} opacity={vetoed || faded ? 0.4 : 1} className="transition-opacity duration-500">
              <Figure x={x} y={220} label={`Seller ${i + 1}`} small />
              <g
                className="transition-[opacity,transform] duration-500"
                opacity={step >= 1 ? 1 : 0}
                transform={step >= 1 ? `translate(${x} 304) scale(${won ? 1.08 : 1})` : `translate(${x} 316) scale(1)`}
                style={{ transformOrigin: `${x}px 327px` }}
              >
                <rect x={-66} y="0" width="132" height="46" rx="10" fill="var(--panel)" stroke={won ? "var(--mint)" : "var(--line)"} strokeWidth={won ? 2 : 1.5} />
                <text x="0" y="19" textAnchor="middle" className="fill-ink" fontSize="14" fontWeight="600" style={{ textDecoration: vetoed ? "line-through" : undefined }}>
                  {money(b.landed)}
                </text>
                <text x="0" y="36" textAnchor="middle" fontSize="10" className="fill-muted" fontWeight="500">
                  {vetoed ? "VETOED" : won ? "WINNER" : b.origin}
                </text>
              </g>
            </g>
          );
        })}
      </svg>

      {/* Verdict line: fills in once the review step runs */}
      <div className="flex min-h-[34px] flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-4 py-2.5 text-[13px]">
        {step >= 2 ? (
          sellers.map((b) => (
            <span key={b.seller} className="inline-flex items-center gap-1.5">
              <Verdict kind={b.recommendation === "veto" ? "veto" : b.won ? "buy" : "caution"}>{b.seller}</Verdict>
              {b.won && step >= 3 && <Tag>Winner</Tag>}
            </span>
          ))
        ) : (
          <span className="text-muted">Sellers bid sealed. Nobody sees another bid until the round closes.</span>
        )}
      </div>

      {/* Stepper and transport */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-soft/60 px-4 py-2.5">
        <div className="flex gap-1" role="tablist" aria-label="Auction step">
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
              className={`rounded-full px-3 py-1.5 text-[12.5px] font-medium transition-colors ${step === i ? "bg-accent text-accent-ink" : "text-ink-2 hover:bg-panel"}`}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 text-[12.5px] text-ink-2">
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            disabled={step >= STEPS.length - 1}
            className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 font-medium hover:bg-panel disabled:opacity-40"
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            onClick={() => {
              setStep(0);
              setPlaying(true);
            }}
            className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 font-medium hover:bg-panel"
          >
            Replay
          </button>
        </div>
      </div>
    </section>
  );
}

function Figure({ x, y, label, small }: { x: number; y: number; label: string; small?: boolean }) {
  const s = small ? 0.82 : 1;
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`}>
      <path d="M-13 -6 Q0 -20 13 -6 L10 -4 Q0 -14 -10 -4 Z" fill="var(--ink-2)" />
      <circle cx="0" cy="0" r="9" fill="none" stroke="var(--ink-2)" strokeWidth="2" />
      <line x1="0" y1="9" x2="0" y2="34" stroke="var(--ink-2)" strokeWidth="2" />
      <line x1="0" y1="16" x2="-12" y2="26" stroke="var(--ink-2)" strokeWidth="2" strokeLinecap="round" />
      <line x1="0" y1="16" x2="12" y2="26" stroke="var(--ink-2)" strokeWidth="2" strokeLinecap="round" />
      <line x1="0" y1="34" x2="-9" y2="50" stroke="var(--ink-2)" strokeWidth="2" strokeLinecap="round" />
      <line x1="0" y1="34" x2="9" y2="50" stroke="var(--ink-2)" strokeWidth="2" strokeLinecap="round" />
      <text x="0" y="68" textAnchor="middle" fontSize="11" fontWeight="600" className="fill-muted">
        {label}
      </text>
    </g>
  );
}
