"use client";
// web/src/components/FloorMini.tsx
// A generic miniature of the floor for the landing (#448): the buyer's agent at the centre with the cyan pulse, four seller
// agents lapping the ring in the floor's colours, and the round's four status lines typed in. No prices, no names: it is
// the shape of a round, not a deal. The real thing is /floor.
import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";
import { SHIELD } from "@/lib/brand";
import { FISH_PATH } from "./BrandMark";

const LINES = ["Goal received", "4 bids sealed", "3 of 4 pass", "Code confirmed"];
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
      className={`relative overflow-hidden rounded-2xl border border-[rgba(214,235,253,0.22)] bg-[linear-gradient(180deg,#1b3a58_0%,#14314c_100%)] p-5 text-floor-line shadow-[0_30px_80px_-20px_rgba(11,27,43,0.45)] md:p-6 ${className}`}
      aria-label="The floor, in miniature"
      role="img"
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[rgba(255,255,255,0.08)]" aria-hidden />
      <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-[0.08em] text-ghost-1">
        <span className="inline-flex items-center gap-2"><span className="dot text-shield" aria-hidden /> The floor</span>
        <span>Round 1 of 3</span>
      </div>
      <div className="relative mx-auto mt-6 h-[240px] w-[480px] max-w-full" aria-hidden>
        <div className="absolute inset-x-[48px] inset-y-[36px] rounded-[22px] border border-[rgba(238,243,248,0.16)]" />
        <div className="absolute inset-x-[96px] inset-y-[76px] rounded-[16px] border border-dashed border-[rgba(238,243,248,0.1)]" />
        <div className="fm-ring absolute left-1/2 top-1/2 h-10 w-10 -translate-x-1/2 -translate-y-1/2 rounded-full">
          <svg viewBox="0 0 24 24" className="h-10 w-10 text-pac"><path d={FISH_PATH} fill="currentColor" /><circle cx="16.3" cy="8.6" r="1.6" fill="var(--koi)" /></svg>
        </div>
        {GHOSTS.map((g) => (
          <span
            key={g.color}
            className="fm-ghost h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-t-full rounded-b-[4px]"
            style={{ background: g.color, ["--lap" as string]: g.lap, ["--delay" as string]: g.delay }}
          />
        ))}
      </div>
      <ol className="mt-6 grid grid-cols-4 gap-2" aria-label="Round progress">
        {LINES.map((l, i) => {
          const done = i < shown - 1; const now = i === shown - 1;
          return (
            <li key={l} className="grid gap-2">
              <span className={`h-1 rounded-full transition-colors duration-300 ${done ? "bg-shield/70" : now ? "bg-shield" : "bg-[rgba(238,243,248,0.14)]"}`} aria-hidden />
              <span className={`whitespace-nowrap text-[11px] font-medium leading-[14px] transition-colors duration-300 md:text-[12px] ${done || now ? "text-floor-line" : "text-floor-line/40"}`}>{l}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
