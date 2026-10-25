"use client";
// The build panel plus the planner's steps as the agent explains them: plan, knockouts, the socket clash (red), the
// swap and the budget it moved, then the locked build. Play, Next and Reset replay the run for the screen and the video.

import { useEffect, useState } from "react";
import { buildAt, type BuildResult, type StepKind } from "@/lib/build";
import { BuildPanel } from "./build";
import { Card, Label } from "./ui";

// The dot carries the kind; each line already says what happened ("Clash: ...", "GPU: Best Buy out ..."), so no kind word.
const DOT: Record<StepKind, string> = {
  plan: "bg-ink-2", pick: "bg-ink-2", knockout: "bg-coral", clash: "bg-coral",
  swap: "bg-pulse", reallocate: "bg-pulse", locked: "bg-mint", blocked: "bg-coral",
};
const STEP_MS = 1200;

export function BuildBoard({ build, origin }: { build: BuildResult; origin?: string }) {
  const total = build.steps.length;
  const [upTo, setUpTo] = useState(total);
  const [started, setPlaying] = useState(false);
  const playing = started && upTo < total; // the replay stops itself at the last step: derived, so no setState inside the effect
  useEffect(() => {
    if (!playing) return;
    const t = setTimeout(() => setUpTo((n) => n + 1), STEP_MS);
    return () => clearTimeout(t);
  }, [playing, upTo]);
  // A live build (it carries its feed origin) is drawn as it stands: its events have no per-part pick step to replay.
  const live = !!build.origin;
  const now = live ? build : buildAt(build, upTo);
  const btn = "rounded-md px-2.5 py-1 text-[13px] text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-40";
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
        <ol className="relative ml-1 border-l border-line" aria-live="polite">
          {now.steps.map((s, i) => (
            <li key={i} className="relative py-1.5 pl-4 text-[13.5px] leading-snug">
              <span className={`absolute -left-[4px] top-[11px] h-[7px] w-[7px] rounded-full ${DOT[s.kind]}`} aria-hidden />
              <span className="text-ink-2">{s.line}</span>
            </li>
          ))}
        </ol>
        <p className="mt-2 text-[12px] text-muted tabular-nums">Step {now.steps.length} of {total}</p>
      </Card>
    </div>
  );
}
