// Pure layout math for the 2D "Western showdown" scene (SVG). No randomness: same inputs, same output.
export interface Pt { x: number; y: number }
export interface WestLayout {
  w: number; h: number; // the SVG viewBox
  ring: { cx: number; cy: number; rx: number; ry: number }; // the fenced ring (an ellipse)
  auctioneer: Pt; referee: Pt; sheriff: Pt; appraiser: Pt; // fixed actors (feet points)
  sellers: Pt[]; // feet points of n sellers on an arc inside the ring, left to right
  cards: { x: number; y: number; rot: number; scale: number }[]; // seller i's tossed price card (center, tilt in degrees, scale): beside that seller, upper right (left if the right would leave the ring or hit a neighbour); one shared scale, as big as fits without overlap
  sellerSigns: Pt[]; // anchor (the sign's base, at scale 1 the board is 184 x 44 above it) of seller i's wide name sign: below the feet; with many sellers every other sign drops one step so neighbours never touch
  sellerSignScale: number; // scale to draw every seller sign at (1 down to about 0.5)
  outs: Pt[]; // anchor of the k-th eliminated seller's small reason sign (the ghost figure is drawn 56 above it): a row below the lowest seller sign (two rows in portrait with more than 4)
  outSignScale: number; // scale to draw every out sign at
  request: Pt; // the request speech bubble's tail anchor, above the auctioneer's head
  scale: number; // figure scale: 1.7 at landscape with up to 5 sellers, 1.3 with 6 to 8, 1.1 in portrait (0.9 with 6 to 8)
}

const SCALE_L = 1.7, SCALE_L_MANY = 1.3, SCALE_P = 1.1, SCALE_P_MANY = 0.9;

// Name sign: selection ring is 208 wide and reaches 100 above its anchor. Out stack: the ghost's head is 150 above the out anchor.
const SIGN_W = 208, SIGN_H = 100, OUT_UP = 150;
const FIG_W = 70, FIG_H = 132, CARD_W = 72, CARD_H = 48, GAP = 4;
type Box = { l: number; r: number; t: number; b: number };
const hit = (a: Box, b: Box, m: number): boolean => a.l < b.r + m && b.l < a.r + m && a.t < b.b + m && b.t < a.b + m;
const figBox = (p: Pt, s: number): Box => ({ l: p.x - (FIG_W / 2) * s, r: p.x + (FIG_W / 2) * s, t: p.y - FIG_H * s, b: p.y });

// Greedy placement at one shared card scale cs; null when some seller finds no free spot.
function tryCards(sellers: Pt[], s: number, w: number, h: number, cs: number): { x: number; y: number; rot: number; scale: number }[] | null {
  const hw = (CARD_W * cs) / 2, hh = (CARD_H * cs) / 2;
  const figs = sellers.map((p) => figBox(p, s));
  const placed: Box[] = [];
  const out: { x: number; y: number; rot: number; scale: number }[] = [];
  for (let i = 0; i < sellers.length; i++) {
    const p = sellers[i];
    let found: { x: number; y: number; rot: number; scale: number } | null = null;
    // right side first, then left; chest height up to above the head; tight gap first
    search: for (const side of [1, -1]) {
      for (const f of [0.8, 0.95, 1.1, 0.65, 1.25, 1.4, 1.6, 0.5]) {
        for (const gap of [0, 8, 16, 28, -0.3 * hw, -0.6 * hw, -0.9 * hw]) {
          const x = p.x + side * ((FIG_W / 2) * s + hw + gap), y = p.y - FIG_H * s * f;
          const box: Box = { l: x - hw, r: x + hw, t: y - hh, b: y + hh };
          if (box.l < 0 || box.r > w || box.t < 0 || box.b > h) continue;
          if (figs.some((fb) => hit(box, fb, 0))) continue;
          if (placed.some((pb) => hit(box, pb, GAP))) continue;
          const mine = Math.hypot(x - p.x, y - p.y);
          if (sellers.some((q, j) => j !== i && Math.hypot(x - q.x, y - q.y) <= mine)) continue;
          found = { x, y, rot: side * (4 + (i % 3) * 3), scale: cs };
          placed.push(box);
          break search;
        }
      }
    }
    if (!found) return null;
    out.push(found);
  }
  return out;
}

function placeCards(sellers: Pt[], s: number, w: number, h: number, maxScale: number): { x: number; y: number; rot: number; scale: number }[] {
  for (let cs = maxScale; cs > 0.3; cs -= 0.05) {
    const r = tryCards(sellers, s, w, h, cs);
    if (r) return r;
  }
  return tryCards(sellers, s, w, h, 0.3) ?? [];
}

const clamp8 = (v: number): number => Math.max(0, Math.min(8, Math.floor(Number.isFinite(v) ? v : 0)));

export function westLayout(n: number, outs: number, portrait: boolean): WestLayout {
  n = clamp8(n);
  outs = clamp8(outs);
  const w = portrait ? 900 : 1600;
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
  // Seller name signs sit 70 below the feet (wide sign, selection ring 208 x 64 at scale 1, reaching 100 above the anchor).
  // When neighbours are too close, odd signs drop below the even ones and the shared scale can grow back.
  let adj = Infinity;
  for (let i = 1; i < n; i++) adj = Math.min(adj, sellers[i].x - sellers[i - 1].x);
  let signScale = n < 2 ? 1 : Math.min(1, (0.95 * adj) / SIGN_W);
  const stagger = n >= 2 && signScale < 0.75;
  if (stagger) signScale = Math.min(1, (0.95 * 2 * adj) / SIGN_W);
  const sellerSigns: Pt[] = sellers.map((p) => ({ x: p.x, y: p.y + 70 }));
  if (stagger) {
    for (let j = 1; j < n; j += 2) {
      const above = Math.max(sellerSigns[j - 1].y, j + 1 < n ? sellerSigns[j + 1].y : -Infinity);
      sellerSigns[j] = { x: sellers[j].x, y: Math.max(sellerSigns[j].y, above + 6 + SIGN_H * signScale) };
    }
  }
  const lowestSign = n > 0 ? Math.max(...sellerSigns.map((q) => q.y)) : ring.cy + ring.ry * 0.78 + 70;
  const outY = Math.max(Math.round(lowestSign + OUT_UP + 10), portrait ? ring.cy + ring.ry + 40 : ring.cy + ring.ry + 36);
  // Out signs: a row (landscape) or up to two rows (portrait, more than 4) below the ring, evenly spread.
  const spread = (k: number, lo: number, hi: number, i: number) => (k === 1 ? (lo + hi) / 2 : lo + (i * (hi - lo)) / (k - 1));
  const outPts: Pt[] = [];
  if (!portrait) {
    for (let k = 0; k < outs; k++) outPts.push({ x: spread(outs, 260, 1340, k), y: outY });
  } else {
    const first = Math.min(outs, 4);
    const y = outY;
    for (let k = 0; k < first; k++) outPts.push({ x: spread(first, 120, 780, k), y });
    const rest = outs - first;
    for (let k = 0; k < rest; k++) outPts.push({ x: spread(rest, 120, 780, k), y: y + OUT_UP + 6 });
  }
  const lastOut = outY + (outs > 4 && portrait ? OUT_UP + 6 : 0);
  const h = Math.max(portrait ? 1200 : 900, lastOut + 40);
  const scale = portrait ? (n >= 6 ? SCALE_P_MANY : SCALE_P) : n >= 6 ? SCALE_L_MANY : SCALE_L;
  const cards = placeCards(sellers, scale, w, h, portrait ? 1.5 : 1.8);
  return {
    w, h, ring,
    auctioneer: portrait ? { x: 450, y: 450 } : { x: 800, y: 420 },
    referee: portrait ? { x: 600, y: 470 } : { x: 960, y: 430 },
    sheriff: portrait ? { x: 110, y: 520 } : { x: 150, y: 430 },
    appraiser: portrait ? { x: 790, y: 520 } : { x: 1450, y: 430 },
    sellers, cards, sellerSigns, sellerSignScale: signScale, outs: outPts, outSignScale: 1,
    request: portrait ? { x: 450, y: 300 } : { x: 800, y: 230 },
    scale,
  };
}
