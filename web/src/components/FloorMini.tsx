"use client";
// web/src/components/FloorMini.tsx
// A generic miniature of the floor for the landing (#448): the buyer's agent at the centre with the cyan pulse, four seller
// agents lapping the ring in the floor's colours, and the round's four status lines typed in. No prices, no names: it is
// the shape of a round, not a deal. The real thing is /floor.
import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";
import { FISH_PATH } from "./BrandMark";

const LINES = ["Goal received", "4 bids sealed", "3 of 4 pass", "Code confirmed"];
const BUBBLES = [
  { left: "12%", size: 5, rise: "11s", delay: "0s" },
  { left: "27%", size: 3, rise: "9s", delay: "-4s" },
  { left: "46%", size: 6, rise: "13s", delay: "-7s" },
  { left: "66%", size: 4, rise: "10s", delay: "-2s" },
  { left: "83%", size: 5, rise: "12s", delay: "-9s" },
  { left: "93%", size: 3, rise: "9s", delay: "-6s" },
];

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
        <span>Round 1 of 3</span>
      </div>
      <div className="relative mx-auto mt-6 h-[240px] w-[480px] max-w-full" aria-hidden>
        <div className="absolute inset-x-[48px] inset-y-[36px] rounded-[22px] border border-white/30" />
        <div className="absolute inset-x-[96px] inset-y-[76px] rounded-[16px] border border-dashed border-white/15" />
        <div className="fm-ring absolute left-1/2 top-1/2 h-10 w-10 -translate-x-1/2 -translate-y-1/2 rounded-full">
          <svg viewBox="0 0 24 24" className="h-10 w-10 text-pac"><path d={FISH_PATH} fill="currentColor" /><circle cx="16.3" cy="8.6" r="1.6" fill="var(--koi)" /></svg>
        </div>
        {GHOSTS.map((g) => (
          <span
            key={g.color}
            className="fm-ghost h-6 w-6 rounded-t-full rounded-b-[5px] shadow-[0_2px_6px_rgba(0,0,0,0.35)]"
            style={{ background: g.color, ["--lap" as string]: g.lap, ["--delay" as string]: g.delay }}
          />
        ))}
      </div>
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
    { x: 24, h: 46, sway: "5.2s", delay: "0s" },
    { x: 58, h: 70, sway: "6.1s", delay: "-2s" },
    { x: 96, h: 38, sway: "4.6s", delay: "-1s" },
    { x: 410, h: 58, sway: "5.7s", delay: "-3s" },
    { x: 452, h: 42, sway: "4.9s", delay: "-1.5s" },
  ];
  return (
    <svg className="pointer-events-none absolute inset-x-0 bottom-0 h-[90px] w-full" viewBox="0 0 480 90" preserveAspectRatio="none" aria-hidden>
      {strands.map((s) => (
        <path
          key={s.x}
          className="fm-weed"
          style={{ transformOrigin: `${s.x}px 90px`, ["--sway" as string]: s.sway, ["--delay" as string]: s.delay }}
          d={`M ${s.x} 90 C ${s.x - 6} ${90 - s.h * 0.35}, ${s.x + 8} ${90 - s.h * 0.65}, ${s.x} ${90 - s.h}`}
          fill="none"
          stroke="rgba(11,27,43,0.28)"
          strokeWidth="5"
          strokeLinecap="round"
        />
      ))}
    </svg>
  );
}
