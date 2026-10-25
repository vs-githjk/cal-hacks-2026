// Pure helpers for FloorRing3D: palette, seats, easing, tweens, tag text. No React, no three imports.

export const COL = {
  bg: 0x0b1b2b,
  ground: 0x112437,
  line: 0xeef3f8,
  rope: 0x5b6b7c,
  pac: 0xeef3f8,
  ghosts: [0x8fa0b2, 0xe5484d, 0xfcd34d, 0x0f9d76] as const,
  eaten: 0x334155,
  shield: 0x22d3ee,
  checker: 0x0f9d76,
  referee: 0xc7d4ff,
  tagBg: "#eef3f8",
  tagInk: "#0b1b2b",
  coral: "#f26d5b",
} as const;

export const ELEV = (34 * Math.PI) / 180;
export const LOOK: [number, number, number] = [0, 0.2, -0.4];
export const NARROW_PX = 640;

/** Stage box in CSS px: 16:9 at 640 px and wider, 1:1.1 below. */
export function stageSize(width: number): { w: number; h: number; narrow: boolean } {
  const w = Math.max(1, Math.round(width));
  const narrow = w < NARROW_PX;
  return { w, h: Math.round(narrow ? w * 1.1 : (w * 9) / 16), narrow };
}

/** World height shown by the orthographic camera; the 1.35 is the narrow-stage camera distance factor. */
export const viewHeight = (narrow: boolean) => (narrow ? 5.4 * 1.35 : 5.4);

export const REFEREE_AT: [number, number] = [0, -2.6];
export const CENTRE: [number, number] = [0, 0.9];
export const APRON: [number, number] = [3.7, -0.6];

/** Fixed seat on the mat: a semicircle in front of the referee. */
export function seatFor(index: number, count: number): [number, number] {
  const half = count > 4 ? 70 : 60;
  const deg = count <= 1 ? 0 : -half + (2 * half * index) / (count - 1);
  const a = (deg * Math.PI) / 180;
  return [Math.sin(a) * 2.55, -Math.cos(a) * 1.6];
}

export const depthScale = (z: number) => 1 + z * 0.02;

export const formatPrice = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function tagLines(price: number | null, checkedAgo: number | null): [string, string | null] {
  const first = price === null ? "Sealed" : formatPrice(price);
  const second = checkedAgo !== null && Number.isFinite(checkedAgo) ? `re-checked ${Math.max(0, Math.round(checkedAgo))}s ago` : null;
  return [first, second];
}

// ---- tweens ---------------------------------------------------------------------------------------------------------
export const clamp01 = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t);
export const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const wrapPi = (a: number) => {
  const t = (a + Math.PI) % (2 * Math.PI);
  return (t < 0 ? t + 2 * Math.PI : t) - Math.PI;
};

/** A number that eases to a goal. dur 0 means it is already there. */
export interface Track { v: number; from: number; to: number; t0: number; dur: number }
export const track = (v: number): Track => ({ v, from: v, to: v, t0: 0, dur: 0 });
export function goTo(tr: Track, to: number, now: number, dur: number, delay = 0): void {
  tr.from = tr.v;
  tr.to = to;
  tr.t0 = now + delay;
  tr.dur = dur;
  if (dur <= 0) tr.v = to;
}
/** Advance one track; true while it is still moving (including a delay not yet started). */
export function stepTrack(tr: Track, now: number): boolean {
  if (tr.dur <= 0) {
    tr.v = tr.to;
    return false;
  }
  const u = clamp01((now - tr.t0) / tr.dur);
  tr.v = tr.from + (tr.to - tr.from) * ease(u);
  return u < 1;
}
