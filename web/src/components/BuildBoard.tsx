"use client";
// The build panel plus the planner's steps as the agent explains them: plan, knockouts, the socket clash (red), the
// swap and the budget it moved, then the locked build. Play, Next and Reset replay the run for the screen and the video.

import { useEffect, useState } from "react";
import { buildAt, type BuildResult, type StepKind } from "@/lib/build";
import { BuildPanel } from "./build";
import { Card, Label } from "./ui";

const TONE: Record<StepKind, [string, string]> = {
  plan: ["text-ink-2", "Plan"], pick: ["text-mint", "Won"], knockout: ["text-coral", "Out"], clash: ["text-coral", "Clash"],
  swap: ["text-accent", "Swap"], reallocate: ["text-accent", "Budget"], locked: ["text-mint", "Locked"], blocked: ["text-coral", "Blocked"],
};
const STEP_MS = 1200;

export function BuildBoard({ build, origin }: { build: BuildResult; origin?: string }) {
  const total = build.steps.length;
  const [upTo, setUpTo] = useState(total);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    if (upTo >= total) return setPlaying(false);
    const t = setTimeout(() => setUpTo((n) => n + 1), STEP_MS);
    return () => clearTimeout(t);
  }, [playing, upTo, total]);
  // A live build (it carries its feed origin) is drawn as it stands: its events have no per-part pick step to replay.
  const live = !!build.origin;
  const now = live ? build : buildAt(build, upTo);
  const btn = "rounded-md border border-line-2 px-2.5 py-1 text-[12px] font-semibold disabled:opacity-40";
  return (
    <div className="grid gap-3.5 lg:grid-cols-[7fr_5fr]">
      <BuildPanel build={now} origin={origin} />
      <Card>
        <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
          <Label>What the agent did</Label>
          {!live && <div className="flex gap-1.5">
            <button className={btn} onClick={() => { if (upTo >= total) setUpTo(1); setPlaying(true); }} disabled={playing}>Play</button>
            <button className={btn} onClick={() => { setPlaying(false); setUpTo((n) => Math.min(total, n + 1)); }} disabled={upTo >= total}>Next</button>
            <button className={btn} onClick={() => { setPlaying(false); setUpTo(1); }}>Reset</button>
          </div>}
        </div>
        <ol className="grid gap-1.5" aria-live="polite">
          {now.steps.map((s, i) => (
            <li key={i} className={`grid grid-cols-[58px_1fr] gap-2 rounded-lg px-2 py-1.5 text-[13px] ${s.kind === "clash" ? "bg-coral-soft" : ""}`}>
              <span className={`text-[11px] font-bold uppercase tracking-[0.04em] ${TONE[s.kind][0]}`}>{TONE[s.kind][1]}</span>
              <span className="min-w-0 text-ink-2">{s.line}</span>
            </li>
          ))}
        </ol>
        <p className="mt-2 font-mono text-[11px] text-muted tabular-nums">Step {now.steps.length} of {total}</p>
      </Card>
    </div>
  );
}
