"use client";

import { useEffect, useRef, useState } from "react";

type Box = [number, number, number, number];

/** Eases an svg viewBox toward a target window (the "follow Pac-Man" camera). Returns the viewBox string, or null when not following.
 * Under reduced motion it jumps straight to the target. */
export function useFollowViewBox(target: Box | null, reducedMotion: boolean): string | null {
  const [box, setBox] = useState<Box | null>(target);
  const cur = useRef<Box | null>(target);
  const goal = useRef<Box | null>(target);
  const key = target ? target.join(",") : "";
  useEffect(() => {
    goal.current = target;
    let raf = 0;
    const tick = () => {
      const g = goal.current;
      if (!g) { cur.current = null; setBox(null); return; }
      const c = cur.current ?? g;
      const next = (reducedMotion ? g : c.map((v, i) => v + (g[i]! - v) * 0.18)) as Box;
      const done = next.every((v, i) => Math.abs(v - g[i]!) < 0.3);
      cur.current = done ? g : next;
      setBox(cur.current);
      if (!done) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, reducedMotion]);
  const b = target ? (box ?? target) : null;
  return b ? b.map((v) => Math.round(v * 10) / 10).join(" ") : null;
}
