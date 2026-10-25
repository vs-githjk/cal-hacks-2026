// Pieces the art set does not have yet, drawn in the same ink style as art.tsx (black #1A1A1A, stroke 4, round caps and joins,
// hand wobble baked into static curves, small black solids only). Pure static <g>, no text, no motion, no data.
import { INK, PAPER, SHADE, type Place } from "./art";

function Ink({ x = 0, y = 0, scale = 1, children }: Place & { children: React.ReactNode }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} fill="none" stroke={INK} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </g>
  );
}

/** The referee: a flat cap with a visor, a clipboard held in front with both hands. Feet at (0,0), about 70 by 132. */
export function Referee(at: Place) {
  return (
    <Ink {...at}>
      <path d="M0,-86 Q1,-62 0,-40" />
      <path d="M0,-40 Q-8,-20 -14,0" />
      <path d="M0,-40 Q8,-20 14,0" />
      <path d="M0,-78 Q-14,-72 -15,-60" />
      <path d="M0,-78 Q14,-72 15,-60" />
      <rect x={-17} y={-80} width={34} height={44} rx={3} fill={PAPER} transform="rotate(-3 0 -58)" />
      <rect x={-6} y={-85} width={12} height={8} rx={2} fill={INK} transform="rotate(-3 0 -58)" />
      <path d="M-10,-68 Q0,-70 10,-68 M-10,-60 Q0,-62 10,-60 M-10,-52 Q-2,-54 6,-52" strokeWidth={2.5} stroke={SHADE} />
      <circle cx={0} cy={-100} r={14} />
      <circle cx={-5} cy={-103} r={1.8} fill={INK} stroke="none" />
      <circle cx={5} cy={-103} r={1.8} fill={INK} stroke="none" />
      <path d="M-6,-96 Q0,-90 6,-96" />
      <path d="M-15,-109 Q-14,-123 0,-122 Q14,-123 15,-109 Z" fill={INK} />
      <path d="M8,-109 Q20,-111 26,-106" />
    </Ink>
  );
}

/** Closed hand-wobbled ellipse as static quadratic curves (deterministic, no randomness). */
function wobblyEllipse(cx: number, cy: number, rx: number, ry: number, seed: number, amp = 2.2): string {
  const n = 28;
  const pt = (i: number): [number, number] => {
    const a = (i / n) * Math.PI * 2;
    const k = 1 + (amp / 100) * (Math.sin(a * 3 + seed) + 0.6 * Math.sin(a * 5 + seed * 2.3));
    return [cx + rx * k * Math.cos(a), cy + ry * k * Math.sin(a)];
  };
  const pts = Array.from({ length: n }, (_, i) => pt(i));
  const mid = (i: number): [number, number] => {
    const p = pts[i % n]!;
    const q = pts[(i + 1) % n]!;
    return [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
  };
  const f = (v: number) => v.toFixed(1);
  const m0 = mid(n - 1);
  let d = `M${f(m0[0])},${f(m0[1])}`;
  for (let i = 0; i < n; i++) {
    const c = pts[i]!;
    const m = mid(i);
    d += ` Q${f(c[0])},${f(c[1])} ${f(m[0])},${f(m[1])}`;
  }
  return `${d} Z`;
}

/** The ring fence drawn natively on the ellipse (cx, cy, rx, ry): two rails 14 apart, posts about every 110 units, all at stroke 4. */
export function RingFence({ cx, cy, rx, ry }: { cx: number; cy: number; rx: number; ry: number }) {
  const per = Math.PI * (3 * (rx + ry) - Math.sqrt((3 * rx + ry) * (rx + 3 * ry)));
  const n = Math.max(8, Math.round(per / 110));
  const idx = Array.from({ length: n }, (_, i) => i);
  const post = (i: number) => {
    const a = ((i + 0.5) / n) * Math.PI * 2;
    const x = cx + rx * Math.cos(a);
    const y = cy + ry * Math.sin(a);
    const lean = Math.sin(i * 7.3) * 1.2;
    return <path key={i} d={`M${x.toFixed(1)},${(y + 2).toFixed(1)} Q${(x + lean).toFixed(1)},${(y - 16).toFixed(1)} ${x.toFixed(1)},${(y - 32).toFixed(1)}`} />;
  };
  const back = idx.filter((i) => Math.sin(((i + 0.5) / n) * Math.PI * 2) <= 0);
  const front = idx.filter((i) => Math.sin(((i + 0.5) / n) * Math.PI * 2) > 0);
  return (
    <Ink>
      {back.map(post)}
      <path d={wobblyEllipse(cx, cy - 14, rx, ry, 1.3)} />
      <path d={wobblyEllipse(cx, cy - 28, rx, ry, 4.1)} />
      {front.map(post)}
    </Ink>
  );
}
