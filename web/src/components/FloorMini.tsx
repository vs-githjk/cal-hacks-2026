"use client";
// web/src/components/FloorMini.tsx
// A generic miniature of the floor for the landing (#448): the buyer's agent at the centre with the cyan pulse, four seller
// agents lapping the ring in the floor's colours, and the round's four status lines typed in. No prices, no names: it is
// the shape of a round, not a deal. The real thing is /floor.
import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";
import { SHIELD } from "@/lib/brand";
import { FISH_PATH } from "./BrandMark";

const LINES = ["Goal received", "4 bids sealed", `${SHIELD}: 3 of 4 pass`, "Code confirmed"];
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
      className={`relative overflow-hidden rounded-2xl border border-[rgba(214,235,253,0.19)] bg-floor-bg p-5 text-floor-line shadow-[0_30px_80px_-20px_rgba(11,27,43,0.45)] md:p-6 ${className}`}
      aria-label="The floor, in miniature"
      role="img"
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[rgba(255,255,255,0.08)]" aria-hidden />
      <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-[0.08em] text-ghost-1">
        <span className="inline-flex items-center gap-2"><span className="dot text-shield" aria-hidden /> The floor</span>
        <span>Round 1 of 3</span>
      </div>
      <div className="relative mx-auto mt-5 h-[160px] w-[320px] max-w-full" aria-hidden>
        <div className="absolute inset-x-[40px] inset-y-[28px] rounded-[18px] border border-[rgba(238,243,248,0.14)]" />
        <div className="absolute inset-x-[72px] inset-y-[56px] rounded-[14px] border border-dashed border-[rgba(238,243,248,0.1)]" />
        <div className="fm-ring absolute left-1/2 top-1/2 h-7 w-7 -translate-x-1/2 -translate-y-1/2 rounded-full">
          <svg viewBox="0 0 24 24" className="h-7 w-7 text-pac"><path d={FISH_PATH} fill="currentColor" /><circle cx="16.3" cy="8.6" r="1.6" fill="var(--koi)" /></svg>
        </div>
        {GHOSTS.map((g) => (
          <span
            key={g.color}
            className="fm-ghost h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-t-full rounded-b-[3px]"
            style={{ background: g.color, ["--lap" as string]: g.lap, ["--delay" as string]: g.delay }}
          />
        ))}
      </div>
      <ol className="mt-4 grid gap-1 font-mono text-[13px] leading-[18px] text-floor-line/80">
        {LINES.slice(0, shown).map((l, i) => (
          <li key={l} className="fm-line flex items-center gap-2">
            <span className={`h-1.5 w-1.5 rounded-full ${i === shown - 1 ? "bg-shield" : "bg-ghost-1"}`} aria-hidden />
            {l}
          </li>
        ))}
      </ol>
    </div>
  );
}
