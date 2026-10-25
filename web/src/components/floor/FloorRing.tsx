"use client";
// The ring: one canvas drawn each frame from a FloorPhase (see floorPhases.ts). Geometry, pieces and colors follow
// docs/design-system/floor.md and floor-standalone.html (v2): a trapezoid mat in a 960 by 540 view, posts and three ropes a side,
// pieces standing on the mat with soft shadows, no crowd. With reduced motion nothing moves: each phase is drawn at its end state.
import { useEffect, useRef } from "react";
import { FLOOR as C, T, type Tint } from "./floorTokens";
export type FloorTheme = "fish" | "ghosts";
import { CHECKER_HOME, REFEREE_AT, type FloorPhase, type Pt, type SellerView } from "./floorPhases";
import { formatMoney } from "@/lib/money";

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const lerpPt = (a: Pt, b: Pt, t: number): Pt => ({ u: lerp(a.u, b.u, t), v: lerp(a.v, b.v, t) });
const TINT: Record<Tint, string> = { slate: C.slate, coral: C.coral, amber: C.amber, mint: C.mint, sky: C.sky, sand: C.sand };
function hex(c: string): [number, number, number] {
  const n = parseInt(c.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function mix(a: string, b: string, t: number): string {
  const x = hex(a), y = hex(b);
  return `rgb(${Math.round(lerp(x[0], y[0], t))},${Math.round(lerp(x[1], y[1], t))},${Math.round(lerp(x[2], y[2], t))})`;
}
/** Depth: nearer is bigger. */
const dz = (v: number) => 0.85 + 0.3 * v;
/** Ice-bed flecks on the mat, fixed so the picture is the same every frame. */
const FLECKS = Array.from({ length: 90 }, (_, i) => ({ x: 150 + ((i * 197) % 660), y: 195 + ((i * 89) % 235), r: 0.8 + ((i * 7) % 5) * 0.5, a: 0.05 + ((i * 13) % 7) * 0.012 }));

/** Floor plane to the 960 by 540 view (before the 24 px drop that clears the HUD). */
const px = (u: number, v: number) => 480 + u * (210 + 150 * v);
const py = (v: number) => 190 + 240 * v;

function tweenMs(p: FloorPhase): number {
  switch (p.kind) {
    case "dash": return T.dash;
    case "shield": return T.block;
    case "winner": return T.grow + 200;
    case "check": return 700;
    default: return 600;
  }
}

let TS = 1; // text scale: 1, or larger in recording mode so labels read at 25 percent zoom
function text(ctx: CanvasRenderingContext2D, s: string, x: number, y: number, size: number, color: string, font: string, align: CanvasTextAlign = "center") {
  ctx.font = `500 ${size * TS}px ${font}`; ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = "middle";
  ctx.fillText(s.toUpperCase(), x, y);
}

export interface RingProps {
  phases: readonly FloorPhase[];
  index: number;
  /** ms since the current phase began; read every frame so React does not rerender 60 times a second. */
  elapsed: { current: number };
  reduced: boolean;
  label: string;
  theme: FloorTheme;
  /** recording mode: bigger labels */
  textScale?: number;
}

export function FloorRing({ phases, index, elapsed, reduced, label, theme, textScale = 1 }: RingProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  const props = useRef({ phases, index, reduced, theme, textScale });
  const redraw = useRef<(() => void) | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const mono = `${getComputedStyle(document.documentElement).getPropertyValue("--font-geist-mono").trim() || "ui-monospace"}, ui-monospace, Menlo, Consolas, monospace`;
    let raf = 0, W = 0, H = 0, dpr = 1;
    const resize = () => {
      const b = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = Math.max(1, Math.round(b.width)); H = Math.max(1, Math.round(b.height));
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    };
    resize();

    function draw(now: number) {
      const { phases: ps, index: i, reduced: red, theme: th0, textScale: ts0 } = props.current;
      TS = ts0;
      const ph = ps[Math.min(i, ps.length - 1)];
      const c = ctx;
      if (!ph || !c) return;
      const prev = ps[i - 1] ?? ph;
      const el = red ? 1e9 : elapsed.current;
      const tt = red ? 1 : ease(clamp01(el / tweenMs(ph)));
      const k = W / 960;
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, W, H);
      c.save();
      c.scale(k, k);
      c.translate(0, 24);
      c.lineCap = "round"; c.lineJoin = "round";
      try { c.letterSpacing = "0.4px"; } catch { /* older engines: no tracking */ }

      // mat: a soft shadow beneath, then the ground with a faint edge
      c.save(); c.shadowColor = "rgba(0,0,0,0.4)"; c.shadowBlur = 20 * k * dpr / dpr; c.fillStyle = "rgba(0,0,0,0.4)";
      c.beginPath(); c.moveTo(270, 206); c.lineTo(690, 206); c.lineTo(850, 452); c.lineTo(110, 452); c.closePath(); c.fill(); c.restore();
      c.fillStyle = C.ground; c.strokeStyle = C.line; c.globalAlpha = 1;
      c.beginPath(); c.moveTo(270, 190); c.lineTo(690, 190); c.lineTo(840, 430); c.lineTo(120, 430); c.closePath(); c.fill();
      c.save(); c.clip();
      for (const f of FLECKS) { c.globalAlpha = f.a; c.fillStyle = "#cfe6f7"; c.beginPath(); c.ellipse(f.x, f.y, f.r * 1.6, f.r, 0, 0, 7); c.fill(); }
      const ice = c.createLinearGradient(0, 190, 0, 430); ice.addColorStop(0, "rgba(207,230,247,0.07)"); ice.addColorStop(1, "rgba(207,230,247,0)");
      c.globalAlpha = 1; c.fillStyle = ice; c.fillRect(100, 190, 760, 240);
      c.restore();
      c.globalAlpha = 0.28; c.lineWidth = 1.5; c.stroke(); c.globalAlpha = 1;

      const line = (x1: number, y1: number, x2: number, y2: number, color: string, w: number, a: number) => {
        c.globalAlpha = a; c.strokeStyle = color; c.lineWidth = w; c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); c.stroke(); c.globalAlpha = 1;
      };
      const disc = (x: number, y: number, r: number, color: string) => { c.fillStyle = color; c.beginPath(); c.arc(x, y, r, 0, 7); c.fill(); };
      // back posts and ropes
      for (const x of [270, 690]) { line(x, 190, x, 126, C.line, 3, 0.75); disc(x, 124, 5, C.line); }
      for (const y of [168, 150, 131]) line(270, y, 690, y, C.rope, 1.5, 0.5);
      [[168, 399], [150, 374], [131, 349]].forEach(([y0, y1]) => { line(270, y0!, 120, y1!, C.rope, 1.5, 0.7); line(690, y0!, 840, y1!, C.rope, 1.5, 0.7); });

      const items: { y: number; draw: () => void }[] = [];
      const bubbles: { x: number; top: number }[] = [];
      const tops: number[] = [];
      const shadow = (rx: number, ry: number) => {
        c.save(); c.translate(0, 2); c.scale(1, ry / rx);
        const g = c.createRadialGradient(0, 0, 0, 0, 0, rx * 1.25); g.addColorStop(0, "rgba(0,0,0,0.5)"); g.addColorStop(1, "rgba(0,0,0,0)");
        c.fillStyle = g; c.beginPath(); c.arc(0, 0, rx * 1.25, 0, 7); c.fill(); c.restore();
      };
      const boost = k < 0.6 ? 1.5 : 1; // phone: pieces stay readable at 366 px
      const at = (x: number, y: number, s: number, f: () => void) => () => { c.save(); c.translate(x, y); c.scale(s * boost, s * boost); f(); c.restore(); };
      const labelSize = (n: number) => Math.max(n, 9 / (k * boost * TS)); // never under 9 px on screen

      // referee
      const rx = px(REFEREE_AT.u, REFEREE_AT.v), ry = py(REFEREE_AT.v);
      items.push({ y: ry, draw: at(rx, ry, dz(REFEREE_AT.v), () => {
        shadow(12, 4);
        c.strokeStyle = C.referee; c.lineWidth = 3; c.beginPath();
        c.moveTo(0, -10); c.lineTo(0, -40);
        if (ph.refereeArms) { c.moveTo(0, -36); c.lineTo(-12, -54); c.moveTo(0, -36); c.lineTo(12, -54); } else { c.moveTo(-12, -24); c.lineTo(12, -24); }
        c.moveTo(0, -10); c.lineTo(-8, 0); c.moveTo(0, -10); c.lineTo(8, 0); c.stroke();
        disc(0, -48, 7, C.referee);
        if (k >= 0.6) text(c, "CRS referee", 0, -66, 10, C.referee, mono);
      }) });

      // checker
      const cp = lerpPt(prev.checker ?? CHECKER_HOME, ph.checker, tt);
      items.push({ y: py(cp.v), draw: at(px(cp.u, cp.v), py(cp.v), dz(cp.v), () => {
        shadow(12, 4);
        c.fillStyle = C.mint; c.beginPath(); c.roundRect(-11, -26, 22, 26, 7); c.fill();
        c.strokeStyle = C.tagInk; c.lineWidth = 2.5; c.beginPath(); c.moveTo(-5, -13); c.lineTo(-1, -9); c.lineTo(6, -17); c.stroke();
        if (k >= 0.6) text(c, "Checker", 0, -34, 10, C.mintText, mono);
      }) });

      // sellers
      ph.sellers.forEach((s: SellerView, n) => {
        const p0 = prev.sellers[n] ?? s;
        const pos = lerpPt(p0.pos, s.pos, tt);
        const sc = lerp(p0.scale, s.scale, tt);
        const eating = s.status === "eaten" && ph.kind === "chomp";
        const alpha = s.status === "eaten" ? (eating ? 1 - clamp01(el / T.chomp) : 0) : 1;
        if (alpha <= 0) return;
        if (s.status === "winner" && (ph.kind === "end" || ph.kind === "paid")) return; // walked out
        const walking = s.status === "winner" && ph.kind === "walkout";
        const x = px(pos.u, pos.v), y = py(pos.v);
        tops.push(y - (56 + ((k < 0.6 || TS > 1) && s.slot % 2 === 0 ? 24 : 0) + 22 + (s.recheck && k >= 0.6 ? 20 : 0) + 40) * sc * dz(pos.v) * boost);
        const look = Math.sign(ph.buyer.u - pos.u) || 1;
        items.push({ y, draw: at(x, y, sc * dz(pos.v), () => {
          c.globalAlpha = alpha;
          shadow(24, 6);
          if (th0 === "fish") {
            const bob = red ? 0 : Math.sin(now / 420 + n * 1.3) * 1.8;
            c.save(); c.translate(0, bob); c.scale(look, 1);
            const col = s.status === "winner" ? mix(C.mint, C.pulse, ph.kind === "winner" ? tt : 1) : TINT[s.tint];
            c.fillStyle = col;
            c.beginPath(); c.moveTo(-20, -34); c.lineTo(-42, -50); c.quadraticCurveTo(-35, -34, -42, -18); c.closePath(); c.fill(); // tail
            c.beginPath(); c.moveTo(-8, -48); c.quadraticCurveTo(2, -62, 12, -48); c.closePath(); c.fill(); // dorsal fin
            c.beginPath(); c.ellipse(0, -34, 26, 17, 0, 0, 7); c.fill(); // body
            c.fillStyle = "rgba(255,255,255,0.22)"; c.beginPath(); c.ellipse(2, -28, 21, 9, 0, 0, Math.PI); c.fill(); // belly
            c.strokeStyle = "rgba(11,27,43,0.35)"; c.lineWidth = 1.6; c.beginPath(); c.arc(6, -34, 11, -1.1, 1.1); c.stroke(); // gill
            c.fillStyle = col; c.beginPath(); c.moveTo(-4, -22); c.quadraticCurveTo(-10, -10, -18, -12); c.quadraticCurveTo(-12, -18, -4, -22); c.fill(); // pectoral
            disc(15, -38, 5, C.tagBg); disc(16.5, -38, 2.4, C.tagInk);
            c.strokeStyle = "rgba(11,27,43,0.5)"; c.lineWidth = 1.4; c.beginPath(); c.moveTo(24, -30); c.lineTo(19, -29); c.stroke(); // mouth
            c.restore();
          } else {
            c.fillStyle = TINT[s.tint];
            c.beginPath(); c.moveTo(-22, 0); c.lineTo(-22, -28); c.arc(0, -28, 22, Math.PI, 0); c.lineTo(22, 0); c.closePath(); c.fill();
            for (const ex of [-8, 8]) { disc(ex, -28, 5, C.tagBg); disc(ex + look * 2, -28, 2.4, C.tagInk); }
          }
          if (s.ring) { c.strokeStyle = C.pulse; c.lineWidth = 2; c.globalAlpha = alpha * clamp01(el / 300); c.beginPath(); c.arc(0, -22, 40, 0, 7); c.stroke(); c.globalAlpha = alpha; }
          // tag: Sealed or the price (a price exists only after close, see floorPhases)
          const label = s.price === null ? "Sealed" : formatMoney(s.price);
          if (walking) { c.globalAlpha = 1; return; }
          const fs = labelSize(11);
          c.font = `500 ${fs * TS}px ${mono}`;
          // phones: tickets of alternate fish ride higher so neighbours never overlap
          const lift = (k < 0.6 || TS > 1) && s.slot % 2 === 0 ? 24 : 0;
          const extra = s.recheck && k >= 0.6 ? Math.max(12, fs * TS * 0.85 + 5) : 0;
          const priceW = c.measureText(label.toUpperCase()).width + 14 / k;
          let tw = Math.max((s.price === null ? 64 : 80) * TS, priceW);
          if (extra) { c.font = `500 ${Math.max(8, fs * 0.72) * TS}px ${mono}`; tw = Math.max(tw, c.measureText(s.recheck!.toUpperCase()).width + 22); c.font = `500 ${fs * TS}px ${mono}`; }
          const th = Math.max(22, fs * TS + 8), thT = th + extra, top = -56 - lift - thT;
          if (th0 === "fish") {
            // a paper price ticket on a string: pointed left end with a punched hole
            const x0 = -tw / 2;
            c.strokeStyle = "rgba(238,243,248,0.55)"; c.lineWidth = 1; c.beginPath(); c.moveTo(0, -52); c.lineTo(0, -56 - lift); c.stroke();
            c.fillStyle = C.paper; c.strokeStyle = C.paperEdge; c.lineWidth = 1;
            c.beginPath(); c.moveTo(x0 + 9, top); c.lineTo(-x0, top); c.lineTo(-x0, -56 - lift); c.lineTo(x0 + 9, -56 - lift); c.lineTo(x0, top + thT / 2); c.closePath(); c.fill(); c.stroke();
            c.fillStyle = C.ground; c.beginPath(); c.arc(x0 + 10, top + thT / 2, 2.2, 0, 7); c.fill();
          } else { c.fillStyle = C.tagBg; c.beginPath(); c.roundRect(-tw / 2, top, tw, thT, 6); c.fill(); }
          const px0 = th0 === "fish" ? 4 : 0;
          text(c, label, px0, top + th / 2 + 0.5, fs, C.tagInk, mono);
          if (extra) text(c, s.recheck!, px0, -56 - lift - extra / 2 + 1, Math.max(8, fs * 0.72), "#4a5a6c", mono);
          if (k >= 0.6 && s.status !== "winner") text(c, s.name, 0, 17, 10, TINT[s.tint] === C.slate ? C.muted : TINT[s.tint], mono); // under the fish, clear of the referee and the tickets
          // status word stacks above the name label, so nothing sits between the ghost and the buyer
          if (s.statusLine && k >= 0.5) text(c, s.statusLine, 0, top - 10, labelSize(10), s.tone === "bad" ? C.coralText : s.tone === "good" ? C.mintText : C.amberText, mono);
          if (s.injection) bubbles.push({ x, top: y - (56 + lift + thT + 40) * sc * dz(pos.v) * boost });
          c.globalAlpha = 1;
        }) });
      });

      // shield: slides from the referee and settles around the ghost it blocks, so it never sits on the buyer or a label
      if (ph.shield) {
        const hit = ph.sellers.find((q) => q.injection || q.statusLine === "SMELL TEST FAILED");
        const target: Pt = hit ? hit.pos : ph.shield;
        const sp = lerpPt(prev.shield ?? REFEREE_AT, target, tt);
        const flash = !red && ph.kind === "shield" && el > T.block && Math.floor((el - T.block) / 120) % 2 === 0 && el < T.block + 480;
        items.push({ y: py(sp.v) + 1, draw: at(px(sp.u, sp.v), py(sp.v), 1, () => {
          c.beginPath(); [[0, -58], [34, -41], [34, -7], [0, 10], [-34, -7], [-34, -41]].forEach(([a, b], j) => (j ? c.lineTo(a!, b!) : c.moveTo(a!, b!))); c.closePath();
          c.fillStyle = C.live; c.globalAlpha = flash || (red && ph.kind === "shield") ? 0.6 : 0.18; c.fill(); c.globalAlpha = 1;
          c.strokeStyle = C.live; c.lineWidth = 2.5; c.stroke();
          if (k >= 0.5) text(c, "Smell Test", 40, -24, 10, C.live, mono, "left");
        }) });
      }

      // the buyer: two half-discs that chomp, an eye, a label
      const bp = lerpPt(prev.buyer, ph.buyer, tt);
      const jaw = red ? 16 : 15 + 9 * Math.sin((now / 600) * Math.PI);
      if (ph.kind !== "end" && ph.kind !== "paid") items.push({ y: py(bp.v), draw: at(px(bp.u, bp.v), py(bp.v), dz(bp.v), () => {
        shadow(26, 7);
        c.save(); c.scale(ph.buyer.face, 1); c.translate(0, -26);
        c.fillStyle = C.pac;
        for (const dir of [-1, 1]) {
          c.save(); c.rotate((dir * jaw * Math.PI) / 180);
          c.beginPath(); if (dir < 0) { c.moveTo(0, 0); c.lineTo(26, 0); c.arc(0, 0, 26, 0, Math.PI, true); } else { c.moveTo(0, 0); c.lineTo(-26, 0); c.arc(0, 0, 26, Math.PI, 0, true); }
          c.closePath(); c.fill(); c.restore();
        }
        disc(7, -12, 3.5, C.tagInk);
        c.restore();
        if (k >= 0.6) text(c, "The buyer", 0, 16, 10, C.pac, mono);
      }) });

      items.sort((a, b) => a.y - b.y).forEach((it) => it.draw());
      // the injection bubble sits above every seller's tag and label (never on another seller's), tail toward its own ghost
      for (const b of bubbles) {
        c.font = `500 ${labelSize(10)}px ${mono}`;
        const bh = Math.max(24, labelSize(10) + 12), bw = Math.min(930, Math.max(236, c.measureText("HIDDEN INSTRUCTION IN THE LISTING").width + 24)), bx = Math.min(Math.max(b.x - bw / 2, 16), 960 - 16 - bw);
        const by = Math.max(-8, Math.min(b.top, ...tops) - bh);
        c.fillStyle = C.coral; c.beginPath(); c.roundRect(bx, by, bw, bh, 8); c.fill();
        const tx = Math.min(Math.max(b.x, bx + 14), bx + bw - 14);
        c.beginPath(); c.moveTo(tx - 6, by + bh); c.lineTo(tx, by + bh + 8); c.lineTo(tx + 6, by + bh); c.closePath(); c.fill();
        text(c, "Hidden instruction in the listing", bx + bw / 2, by + bh / 2, labelSize(10), C.tagBg, mono);
      }
      // front posts and ropes, over the pieces
      for (const x of [120, 840]) { line(x, 430, x, 340, C.line, 3, 0.75); disc(x, 338, 6, C.line); }
      for (const y of [399, 374, 349]) line(120, y, 840, y, C.rope, 1.5, 1);
      c.restore();
    }

    const ro = new ResizeObserver(() => { resize(); draw(performance.now()); });
    ro.observe(canvas);
    const loop = (now: number) => { draw(now); if (!props.current.reduced) raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    redraw.current = () => draw(performance.now());
    return () => { cancelAnimationFrame(raf); ro.disconnect(); redraw.current = null; };
  }, [elapsed]);

  useEffect(() => {
    props.current = { phases, index, reduced, theme, textScale };
    if (reduced) redraw.current?.();
  }, [reduced, index, phases, theme, textScale]);

  return <canvas ref={ref} role="img" aria-label={label} className="block aspect-video w-full" />;
}
