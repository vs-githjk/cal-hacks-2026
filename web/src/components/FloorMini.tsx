"use client";
// web/src/components/FloorMini.tsx
// A generic miniature of the floor for the landing (#448): the buyer's agent at the centre with the cyan pulse, four seller
// agents lapping the ring in the floor's colours, and the round's four status lines typed in. No prices, no names: it is
// the shape of a round, not a deal. The real thing is /floor.
import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";
import { FISH_PATH } from "./BrandMark";
import { OriginChip } from "./ui";

const LINES = ["Goal received", "4 bids sealed", "3 of 4 pass", "Code confirmed"];
const BUBBLES = [
  { left: "12%", size: 5, rise: "11s", delay: "0s" },
  { left: "27%", size: 3, rise: "9s", delay: "-4s" },
  { left: "46%", size: 6, rise: "13s", delay: "-7s" },
  { left: "66%", size: 4, rise: "10s", delay: "-2s" },
  { left: "83%", size: 5, rise: "12s", delay: "-9s" },
  { left: "93%", size: 3, rise: "9s", delay: "-6s" },
];

// The ring as a path: the sellers follow it exactly (SMIL animateMotion scales with the viewBox).
const RING_PATH = "M 70 36 H 410 A 22 22 0 0 1 432 58 V 182 A 22 22 0 0 1 410 204 H 70 A 22 22 0 0 1 48 182 V 58 A 22 22 0 0 1 70 36 Z";

const GHOSTS = [
  { color: "var(--color-ghost-1)", lap: "9s", delay: "0s" },
  { color: "var(--color-ghost-2)", lap: "11s", delay: "-3s" },
  { color: "var(--color-ghost-3)", lap: "10s", delay: "-6s" },
  { color: "var(--color-ghost-4)", lap: "12s", delay: "-8s" },
];

export function FloorMini({ className = "" }: { className?: string }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? LINES.length : 1);
  useEffect(() => {
    if (reduce) return;
    const t = setInterval(() => setShown((n) => (n >= LINES.length ? 1 : n + 1)), 1400);
    return () => clearInterval(t);
  }, [reduce]);
  return (
    <div
      className={`fm-aquarium relative overflow-hidden rounded-[22px] p-5 text-white md:p-6 ${className}`}
      aria-label="The floor, in miniature"
      role="img"
    >
      <Seaweed />
      {BUBBLES.map((b) => (
        <span key={b.left} className="fm-bubble" style={{ left: b.left, width: b.size, height: b.size, ["--rise" as string]: b.rise, ["--delay" as string]: b.delay }} aria-hidden />
      ))}
      <div className="relative flex items-center justify-between text-[11px] font-medium uppercase tracking-[0.08em] text-white/80">
        <span className="inline-flex items-center gap-2"><span className="dot text-white" aria-hidden /> The floor</span>
        <span className="inline-flex items-center gap-2">Round 1 of 3 <OriginChip origin="SIM" /></span>
      </div>
      {/* The ring, the buyer and the four sellers in one SVG, so the sellers ride the same line at every width. */}
      <svg className="relative mx-auto mt-6 block w-full max-w-[520px]" viewBox="0 0 480 240" aria-hidden>
        <rect x="48" y="36" width="384" height="168" rx="22" fill="none" stroke="rgba(255,255,255,0.3)" />
        <rect x="96" y="76" width="288" height="88" rx="16" fill="none" stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />
        <g transform="translate(240 120)">
          <circle r="20" fill="none" stroke="#22d3ee" strokeWidth="2" opacity="0.6">
            {!reduce && <animate attributeName="r" values="20;44" dur="2.4s" repeatCount="indefinite" />}
            {!reduce && <animate attributeName="opacity" values="0.6;0" dur="2.4s" repeatCount="indefinite" />}
          </circle>
          <circle r="20" fill="none" stroke="#22d3ee" strokeWidth="2" />
          <g transform="translate(-14 -14) scale(1.17)">
            <path d={FISH_PATH} fill="#eef3f8" />
            <circle cx="16.3" cy="8.6" r="1.6" fill="var(--koi)" />
          </g>
        </g>
        {GHOSTS.map((g, i) => (
          <path key={g.color} d="M -12 12 V 0 A 12 12 0 0 1 12 0 V 12 Q 12 14 10 14 H -10 Q -12 14 -12 12 Z" fill={g.color} style={{ filter: "drop-shadow(0 2px 4px rgba(0,0,0,0.35))" }} transform={reduce ? `translate(${[70, 432, 410, 48][i]} ${[36, 120, 204, 120][i]})` : undefined}>
            {!reduce && <animateMotion dur={g.lap} begin={g.delay} repeatCount="indefinite" path={RING_PATH} />}
          </path>
        ))}
      </svg>
      <ol className="relative mt-6 grid grid-cols-4 gap-2" aria-label="Round progress">
        {LINES.map((l, i) => {
          const done = i < shown - 1; const now = i === shown - 1;
          return (
            <li key={l} className="grid gap-2">
              <span className={`h-1 rounded-full transition-colors duration-300 ${done ? "bg-white/70" : now ? "bg-white" : "bg-white/20"}`} aria-hidden />
              <span className={`whitespace-nowrap text-[11px] font-medium leading-[14px] transition-colors duration-300 md:text-[12px] ${done || now ? "text-white" : "text-white/45"}`}>{l}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Faint seaweed along the aquarium floor: five strands that sway. Decorative. */
function Seaweed() {
  const strands = [
    { x: 14, h: 62, sway: "5.4s", delay: "-0.5s" },
    { x: 30, h: 96, sway: "6.2s", delay: "-2s" },
    { x: 48, h: 53, sway: "4.8s", delay: "-1s" },
    { x: 70, h: 115, sway: "6.6s", delay: "-3s" },
    { x: 92, h: 71, sway: "5.1s", delay: "-1.6s" },
    { x: 118, h: 46, sway: "4.5s", delay: "-0.8s" },
    { x: 160, h: 59, sway: "5.6s", delay: "-2.4s" },
    { x: 215, h: 40, sway: "4.7s", delay: "-1.2s" },
    { x: 262, h: 50, sway: "5.0s", delay: "-2.8s" },
    { x: 318, h: 65, sway: "5.9s", delay: "-0.3s" },
    { x: 362, h: 43, sway: "4.6s", delay: "-1.9s" },
    { x: 398, h: 87, sway: "6.0s", delay: "-3.4s" },
    { x: 426, h: 56, sway: "5.2s", delay: "-0.9s" },
    { x: 448, h: 102, sway: "6.4s", delay: "-2.2s" },
    { x: 468, h: 68, sway: "4.9s", delay: "-1.4s" },
  ];
  return (
    <svg className="pointer-events-none absolute inset-x-0 bottom-0 h-[130px] w-full" viewBox="0 0 480 130" preserveAspectRatio="none" aria-hidden>
      {strands.map((s) => (
        <path
          key={s.x}
          className="fm-weed"
          style={{ transformOrigin: `${s.x}px 130px`, ["--sway" as string]: s.sway, ["--delay" as string]: s.delay }}
          d={`M ${s.x} 130 C ${s.x - 7} ${130 - s.h * 0.35}, ${s.x + 9} ${130 - s.h * 0.65}, ${s.x} ${130 - s.h}`}
          fill="none"
          stroke="rgba(11,27,43,0.32)"
          strokeWidth="6"
          strokeLinecap="round"
        />
      ))}
    </svg>
  );
}
