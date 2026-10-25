"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { phaseAt, type FloorPhase, type FloorScript } from "@/components/floor/floorPhases";

const REDUCED_STEP_S = 3; // reduced motion jumps to the next phase start this often
const TICK_S = 0.1; // state updates at most this often, so the page re-renders about 10 times a second, not 60

export interface FloorClock { seconds: number; phase: FloorPhase; playing: boolean; play: () => void; pause: () => void; restart: () => void }

/** The playback clock for the floor: seconds into the loop, driven by requestAnimationFrame, looping at script.duration.
 * Reduced motion jumps between phase starts every 3 s. `replay` ignores pausing and always loops from 0 (the video capture). */
export function useFloorClock(script: FloorScript, opts: { paused?: boolean; reducedMotion?: boolean; replay?: boolean } = {}): FloorClock {
  const { paused = false, reducedMotion = false, replay = false } = opts;
  const [userPaused, setUserPaused] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const elapsed = useRef(0);
  const playing = replay || !(paused || userPaused);
  const { duration, phases } = script;

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const secondsFor = (e: number) => (reducedMotion ? (phases[Math.floor(e / REDUCED_STEP_S) % phases.length]?.at ?? 0) : e % duration);
    const frame = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.25); // a hidden tab does not fast-forward the story
      last = now;
      elapsed.current += dt;
      const next = secondsFor(elapsed.current);
      setSeconds((cur) => (reducedMotion || Math.abs(next - cur) >= TICK_S || next < cur ? next : cur));
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [playing, reducedMotion, duration, phases]);

  const phase = useMemo(() => phaseAt(script, seconds), [script, seconds]);
  const play = useCallback(() => setUserPaused(false), []);
  const pause = useCallback(() => setUserPaused(true), []);
  const restart = useCallback(() => {
    elapsed.current = 0;
    setSeconds(0);
    setUserPaused(false);
  }, []);
  return { seconds, phase, playing, play, pause, restart };
}
