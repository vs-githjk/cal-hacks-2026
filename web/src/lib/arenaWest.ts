// Pure layout math for the 2D "Western showdown" scene (SVG). No randomness: same inputs, same output.
export interface Pt { x: number; y: number }
export interface WestLayout {
  w: number; h: number; // the SVG viewBox
  ring: { cx: number; cy: number; rx: number; ry: number }; // the fenced ring (an ellipse)
  auctioneer: Pt; referee: Pt; sheriff: Pt; appraiser: Pt; // fixed actors (feet points)
  sellers: Pt[]; // feet points of n sellers on an arc inside the ring, left to right
  cards: { x: number; y: number; rot: number }[]; // where seller i's card lands, fanned near the ring's center
  outs: Pt[]; // where the k-th eliminated seller's reason sign sits: a row below the ring (two rows in portrait with more than 4)
  request: Pt; // the request speech bubble's tail anchor, above the auctioneer's head
  scale: number; // figure scale: 1.5 at landscape with up to 5 sellers, 1.2 with 6 to 8, 1.1 in portrait (0.9 with 6 to 8)
}

const clamp8 = (v: number): number => Math.max(0, Math.min(8, Math.floor(Number.isFinite(v) ? v : 0)));

export function westLayout(n: number, outs: number, portrait: boolean): WestLayout {
  n = clamp8(n);
  outs = clamp8(outs);
  const w = portrait ? 900 : 1600;
  const h = portrait ? 1200 : 900;
  const ring = portrait ? { cx: 450, cy: 760, rx: 400, ry: 260 } : { cx: 800, cy: 600, rx: 620, ry: 210 };
  const rx = ring.rx * 0.78;
  const ry = ring.ry * 0.78;
  // Lower arc: SVG y points down, so angles 20..160 degrees have sin > 0 (below the center).
  // Sellers are spread evenly in x between cos(160 deg) and cos(20 deg) (n = 2 uses 150 and 30 degrees),
  // then y is read off the ellipse, so neighbours never crowd at the arc's flat ends.
  const half = Math.cos(((n === 2 ? 150 : 160) * Math.PI) / 180); // negative: the left end
  const sellers: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const t = n === 1 ? 0 : half + (i * -2 * half) / (n - 1); // -0.94 .. 0.94 left to right
    sellers.push({ x: ring.cx + rx * t, y: ring.cy + ry * Math.sqrt(1 - t * t) });
  }
  const step = portrait ? 90 : 120;
  const cards = Array.from({ length: n }, (_, i) => ({
    x: ring.cx + (i - (n - 1) / 2) * step,
    y: ring.cy - (portrait ? 70 : 60),
    rot: (i % 2 === 0 ? -1 : 1) * (6 + (i % 3) * 3),
  }));
  // Out signs: a row (landscape) or up to two rows (portrait, more than 4) below the ring, evenly spread.
  const spread = (k: number, lo: number, hi: number, i: number) => (k === 1 ? (lo + hi) / 2 : lo + (i * (hi - lo)) / (k - 1));
  const outPts: Pt[] = [];
  if (!portrait) {
    const y = ring.cy + ring.ry + 36;
    for (let k = 0; k < outs; k++) outPts.push({ x: spread(outs, 260, 1340, k), y });
  } else {
    const first = Math.min(outs, 4);
    const y = ring.cy + ring.ry + 40;
    for (let k = 0; k < first; k++) outPts.push({ x: spread(first, 120, 780, k), y });
    const rest = outs - first;
    for (let k = 0; k < rest; k++) outPts.push({ x: spread(rest, 120, 780, k), y: y + 70 });
  }
  const scale = portrait ? (n >= 6 ? 0.9 : 1.1) : n >= 6 ? 1.2 : 1.5;
  return {
    w, h, ring,
    auctioneer: portrait ? { x: 450, y: 450 } : { x: 800, y: 420 },
    referee: portrait ? { x: 600, y: 470 } : { x: 960, y: 430 },
    sheriff: portrait ? { x: 110, y: 520 } : { x: 150, y: 430 },
    appraiser: portrait ? { x: 790, y: 520 } : { x: 1450, y: 430 },
    sellers, cards, outs: outPts,
    request: portrait ? { x: 450, y: 300 } : { x: 800, y: 230 },
    scale,
  };
}
