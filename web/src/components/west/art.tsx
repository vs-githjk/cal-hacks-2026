// The Western showdown art set: hand-drawn black ink on white paper, after Abhinav's reference (plan/lane-a/shots/west-reference.jpg).
// Every export is a pure, static <g>: props are { x, y, scale, pose?, kind? } only. No data, no motion, no text: ArenaWest places,
// scales, animates and writes everything (prices, reasons, chips, the request). Figures stand with their feet at (0,0), about 120 tall
// and 70 wide, at scale 1. Ink is #1A1A1A at width 4 with round caps and joins; the hand wobble is drawn into static curves. The only
// fills are small black solids (hat crowns, badges, the gavel head) and light grey for hills, shadows and dust. ANCHORS lists the
// points the scene aims at (hand tips, the gavel head, text slots), in the same local units, so motion targets stay stable.
import type { ReactNode } from "react";

export const INK = "#1A1A1A";
export const PAPER = "#FFFFFF";
export const SHADE = "#D9D9D9";

export interface Place { x?: number; y?: number; scale?: number }
export type HatKind = "wide" | "bowler" | "sombrero" | "cap";
export type CowboyPose = "idle" | "toss" | "fold" | "tip" | "ghost";
export type GavelPose = "up" | "down";
export type CardPose = "sealed" | "open";
export type SignKind = "small" | "wide";
export type TailKind = "down" | "left" | "right";

/** Local-unit sizes and aim points. A consumer adds the piece's x, y and multiplies by its scale. */
export const ANCHORS = {
  figure: { w: 70, h: 132, head: { x: 0, y: -100 }, chip: { x: 0, y: 14 } }, // chip: below the feet, centred
  cowboy: { tossHand: { x: 28, y: -106 }, idleHand: { x: 18, y: -48 }, tipHand: { x: 18, y: -108 } },
  auctioneer: { pointTip: { x: -36, y: -98 }, gavelHand: { up: { x: 26, y: -104 }, down: { x: 30, y: -58 } } },
  gavel: { head: { x: 0, y: -27 }, length: 32 }, // drawn with the handle end at (0,0), head up
  priceCard: { w: 72, h: 48, face: { x: -30, y: -18, w: 60, h: 36 } }, // face: the blank text slot, open cards only
  sign: { small: { w: 120, h: 44, box: { x: -52, y: -78, w: 104, h: 32 } }, wide: { w: 200, h: 56, box: { x: -92, y: -90, w: 184, h: 44 } } },
  bubble: { w: 220, h: 70, down: { box: { x: -100, y: -80, w: 200, h: 54 } }, left: { box: { x: 28, y: -27, w: 200, h: 54 } }, right: { box: { x: -228, y: -27, w: 200, h: 54 } } },
  platform: { w: 360, h: 170, deck: { y: -72 }, board: { x: -130, y: -165, w: 260, h: 40 }, stand: { x: 0, y: -72 } }, // stand: where the auctioneer's feet go
  fence: { rx: 420, ry: 90 },
  backdrop: { w: 1200, h: 460 }, // the street above the ring; the scene puts the ring below it
  dust: { w: 90 },
  spotlight: { rx: 100, ry: 30 },
} as const;

function At({ x = 0, y = 0, scale = 1, ink = INK, children, ...rest }: Place & { ink?: string; children: ReactNode; opacity?: number; strokeDasharray?: string }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} fill="none" stroke={ink} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      {children}
    </g>
  );
}

/** A cowboy hat on a head whose top is at y = -114. The crown is one of the small black solids the look allows. */
function Hat({ kind, tilt = 0 }: { kind: HatKind; tilt?: number }) {
  const t = tilt ? `rotate(${tilt} 0 -112)` : undefined;
  if (kind === "bowler") return <g transform={t}><path d="M-19,-112 Q0,-115 19,-112" /><path d="M-12,-112 Q-12,-131 0,-131 Q12,-131 12,-112 Z" fill={INK} /></g>;
  if (kind === "sombrero") return <g transform={t}><path d="M-32,-117 Q-30,-108 0,-109 Q30,-108 32,-117" /><path d="M-10,-111 Q-9,-128 0,-128 Q9,-128 10,-111 Z" fill={INK} /></g>;
  if (kind === "cap") return <g transform={t}><path d="M-14,-112 Q-14,-128 0,-128 Q14,-128 14,-112 Z" fill={INK} /><path d="M2,-112 Q14,-114 24,-109" /></g>;
  return <g transform={t}><path d="M-26,-110 Q-22,-114 0,-112 Q22,-114 26,-110" /><path d="M-12,-112 L-10,-130 Q0,-134 10,-130 L12,-112 Z" fill={INK} /></g>;
}

/** Round head, dot eyes, a smile; the neck meets the body at y = -86. */
function Head({ glasses = false }: { glasses?: boolean }) {
  return (
    <g>
      <circle cx={0} cy={-100} r={14} />
      <circle cx={-5} cy={-103} r={1.8} fill={INK} stroke="none" />
      <circle cx={5} cy={-103} r={1.8} fill={INK} stroke="none" />
      <path d="M-6,-96 Q0,-90 6,-96" />
      {glasses && <g strokeWidth={2.5}><circle cx={-5.5} cy={-103} r={5.5} /><circle cx={5.5} cy={-103} r={5.5} /><path d="M-0.5,-103 L0.5,-103" /></g>}
    </g>
  );
}

function Body() {
  return <g><path d="M0,-86 Q1,-62 0,-40" /><path d="M0,-40 Q-8,-20 -14,0" /><path d="M0,-40 Q8,-20 14,0" /></g>;
}

function Arms({ pose }: { pose: Exclude<CowboyPose, "ghost"> }) {
  if (pose === "toss") return <g><path d="M0,-78 Q-12,-66 -18,-48" /><path d="M0,-78 Q16,-92 28,-106" /></g>;
  if (pose === "fold") return <g><path d="M0,-78 Q-18,-72 -16,-62 Q0,-58 16,-66" /><path d="M0,-78 Q18,-74 16,-66 Q0,-70 -16,-62" /></g>;
  if (pose === "tip") return <g><path d="M0,-78 Q-12,-66 -18,-48" /><path d="M0,-78 Q14,-92 18,-108" /></g>;
  return <g><path d="M0,-78 Q-12,-66 -18,-48" /><path d="M0,-78 Q12,-66 18,-48" /></g>;
}

/** A stick-figure cowboy; kind picks the hat. ghost is the idle figure as a dotted outline at 60 percent, for one who already left. */
export function Cowboy({ pose, kind = "wide", ...at }: Place & { pose: CowboyPose; kind?: HatKind }) {
  const ghost = pose === "ghost";
  return (
    <At {...at} {...(ghost ? { opacity: 0.6, strokeDasharray: "5 7" } : {})}>
      <Body />
      <Arms pose={ghost ? "idle" : pose} />
      <Head />
      <Hat kind={kind} tilt={pose === "tip" ? -14 : 0} />
    </At>
  );
}

/** The buyer agent as auctioneer: one arm points left, the other hand is up or struck, empty, so the Gavel can be placed and moved on it. */
export function Auctioneer({ pose, ...at }: Place & { pose: GavelPose }) {
  return (
    <At {...at}>
      <Body />
      <path d="M0,-78 Q-16,-90 -30,-96" />
      <path d="M-30,-96 L-36,-98" strokeWidth={3} />
      <path d={pose === "up" ? "M0,-78 Q14,-94 26,-104" : "M0,-78 Q18,-70 30,-58"} />
      <Head />
      <Hat kind="wide" />
    </At>
  );
}

/** The gavel, handle end at (0,0), head at the far end. up stands it upright; down lays it struck, head to the right. */
export function Gavel({ pose, ...at }: Place & { pose: GavelPose }) {
  return (
    <At {...at}>
      <g transform={pose === "up" ? "rotate(-30)" : "rotate(70)"}>
        <path d="M0,0 L0,-22" />
        <rect x={-11} y={-32} width={22} height={11} rx={3} fill={INK} />
      </g>
    </At>
  );
}

function Star({ cx, cy, r }: { cx: number; cy: number; r: number }) {
  const pts: string[] = [];
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 === 0 ? r : r * 0.45;
    pts.push(`${(cx + rr * Math.cos(a)).toFixed(1)},${(cy + rr * Math.sin(a)).toFixed(1)}`);
  }
  return <polygon points={pts.join(" ")} fill={INK} stroke="none" />;
}

/** The Shield as sheriff: hands on hips, a star on the hat and one on the chest. */
export function Sheriff(at: Place) {
  return (
    <At {...at}>
      <Body />
      <path d="M0,-78 Q-16,-70 -16,-60 Q-10,-56 -4,-58" />
      <path d="M0,-78 Q16,-70 16,-60 Q10,-56 4,-58" />
      <Head />
      <Hat kind="wide" />
      <Star cx={0} cy={-122} r={5} />
      <Star cx={-6} cy={-70} r={6} />
    </At>
  );
}

/** The Advocate as appraiser: round glasses and an open ledger in both hands. */
export function Appraiser(at: Place) {
  return (
    <At {...at}>
      <Body />
      <path d="M0,-78 Q-14,-72 -16,-62" />
      <path d="M0,-78 Q14,-72 16,-62" />
      <path d="M-22,-66 L-2,-60 L-2,-46 L-22,-52 Z" fill={PAPER} />
      <path d="M22,-66 L2,-60 L2,-46 L22,-52 Z" fill={PAPER} />
      <path d="M-17,-59 L-7,-56 M-17,-54 L-7,-51 M7,-56 L17,-59" strokeWidth={2.5} />
      <Head glasses />
      <Hat kind="bowler" />
    </At>
  );
}

/** The wooden auctioneer stand: 360 by 170, base at (0,0), the deck at y = -72 (ANCHORS.platform.stand), a blank board on two posts at the top. */
export function Platform(at: Place) {
  return (
    <At {...at}>
      <rect x={-180} y={-72} width={360} height={72} rx={3} fill={PAPER} />
      <path d="M-180,-72 L-120,-2 M-120,-72 L-180,-2 M-60,-72 L0,-2 M0,-72 L-60,-2 M60,-72 L120,-2 M120,-72 L60,-2" strokeWidth={2.5} stroke={SHADE} />
      <path d="M-120,-72 L-120,0 M-60,-72 L-60,0 M0,-72 L0,0 M60,-72 L60,0 M120,-72 L120,0" strokeWidth={3} />
      <path d="M-184,-74 Q0,-79 184,-74" />
      <path d="M-120,-74 L-120,-124 M120,-74 L120,-124" />
      <rect x={-130} y={-165} width={260} height={40} rx={4} fill={PAPER} />
    </At>
  );
}

/** A blank wooden sign on two legs, base at (0,0); kind small (120 by 44) or wide (200 by 56). The board is ANCHORS.sign[kind].box. */
export function Sign({ kind = "small", ...at }: Place & { kind?: SignKind }) {
  const { w, h } = ANCHORS.sign[kind];
  const leg = Math.round(w / 3);
  return (
    <At {...at}>
      <path d={`M-${leg},-40 L-${leg},0 M${leg},-40 L${leg},0`} />
      <rect x={-w / 2} y={-(h + 40)} width={w} height={h} rx={5} fill={PAPER} />
    </At>
  );
}

/** A 72 by 48 price card centred at (0,0). sealed shows the back (a flap and a wax dot, nothing else); open is a blank face for the scene's price. */
export function PriceCard({ pose, ...at }: Place & { pose: CardPose }) {
  const { w, h } = ANCHORS.priceCard;
  return (
    <At {...at}>
      <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={6} fill={PAPER} />
      {pose === "sealed" && (
        <g>
          <path d={`M${-w / 2},${-h / 2} L0,${h * 0.05} L${w / 2},${-h / 2}`} strokeWidth={3} />
          <circle cx={0} cy={h * 0.1} r={5} fill={INK} stroke="none" />
        </g>
      )}
    </At>
  );
}

/** A 220 by 70 speech bubble with its tail tip at (0,0); kind says which side the tail is on. The body is ANCHORS.bubble[kind].box. */
export function Bubble({ kind = "down", ...at }: Place & { kind?: TailKind }) {
  const { w, h } = ANCHORS.bubble;
  if (kind === "down") {
    return (
      <At {...at}>
        <rect x={-w / 2} y={-(h + 18)} width={w} height={h} rx={16} fill={PAPER} />
        <path d="M-9,-18 L0,0 L9,-18" fill={PAPER} stroke="none" />
        <path d="M-10,-18 L0,0 L10,-18" />
        <path d="M-8,-18 L8,-18" stroke={PAPER} strokeWidth={5} />
      </At>
    );
  }
  const base = kind === "left" ? 18 : -18;
  const x = kind === "left" ? 18 : -(w + 18);
  return (
    <At {...at}>
      <rect x={x} y={-h / 2} width={w} height={h} rx={16} fill={PAPER} />
      <path d={`M${base},-9 L0,0 L${base},9`} fill={PAPER} stroke="none" />
      <path d={`M${base},-10 L0,0 L${base},10`} />
      <path d={`M${base},-8 L${base},8`} stroke={PAPER} strokeWidth={5} />
    </At>
  );
}

/** A dust puff around (0,0), about 90 wide: grey puffs with a few ink curls. */
export function DustPuff(at: Place) {
  return (
    <At {...at}>
      <circle cx={-28} cy={-10} r={14} fill={SHADE} stroke="none" />
      <circle cx={0} cy={-18} r={18} fill={SHADE} stroke="none" />
      <circle cx={26} cy={-8} r={12} fill={SHADE} stroke="none" />
      <circle cx={10} cy={2} r={9} fill={SHADE} stroke="none" />
      <path d="M-40,-4 Q-44,-22 -26,-24" strokeWidth={3} />
      <path d="M14,-34 Q30,-36 34,-20" strokeWidth={3} />
      <path d="M-6,8 Q4,14 18,8" strokeWidth={3} />
    </At>
  );
}

/** The spotlight on the ground around (0,0): three dotted ellipses, 200 wide, with a grey pool. */
export function Spotlight(at: Place) {
  return (
    <At {...at}>
      <ellipse cx={0} cy={0} rx={40} ry={12} fill={SHADE} stroke="none" />
      <ellipse cx={0} cy={0} rx={100} ry={30} strokeWidth={3} strokeDasharray="4 8" />
      <ellipse cx={0} cy={0} rx={70} ry={21} strokeWidth={3} strokeDasharray="4 8" />
      <ellipse cx={0} cy={0} rx={40} ry={12} strokeWidth={3} strokeDasharray="4 8" />
    </At>
  );
}

/** A false-front building, base at (0,0): parapet, a window, a door, and a porch rail. */
function Building({ w, h, flip = false }: { w: number; h: number; flip?: boolean }) {
  const x = -w / 2;
  return (
    <g transform={flip ? "scale(-1 1)" : undefined}>
      <path d={`M${x},0 L${x},${-h * 0.78} L${x + w * 0.5},${-h} L${x + w},${-h * 0.78} L${x + w},0`} fill={PAPER} />
      <path d={`M${x},${-h * 0.62} L${x + w},${-h * 0.62}`} strokeWidth={3} />
      <rect x={x + w * 0.16} y={-h * 0.5} width={w * 0.2} height={h * 0.2} strokeWidth={3} />
      <path d={`M${x + w * 0.6},0 L${x + w * 0.6},${-h * 0.42} Q${x + w * 0.72},${-h * 0.5} ${x + w * 0.84},${-h * 0.42} L${x + w * 0.84},0`} strokeWidth={3} />
      <path d={`M${x - w * 0.3},${-h * 0.36} L${x},${-h * 0.36} M${x - w * 0.3},${-h * 0.36} L${x - w * 0.3},0 M${x - w * 0.3},${-h * 0.2} L${x},${-h * 0.2}`} strokeWidth={3} />
    </g>
  );
}

/** The street behind the ring, 1200 by 460 from (0,0): grey hills, two false-front buildings, a cactus, two clouds; the ring goes below. */
export function Backdrop(at: Place) {
  const { w, h } = ANCHORS.backdrop;
  const g = h;
  const bh = h * 0.56;
  const bw = bh * 1.1;
  const hills = `M0,${g} Q${w * 0.15},${h * 0.3} ${w * 0.32},${h * 0.56} Q${w * 0.5},${h * 0.22} ${w * 0.68},${h * 0.56} Q${w * 0.85},${h * 0.3} ${w},${g}`;
  return (
    <At {...at}>
      <path d={`${hills} Z`} fill={SHADE} stroke="none" />
      <path d={hills} strokeWidth={3} />
      <g transform={`translate(${w * 0.17} ${g})`}><Building w={bw} h={bh} /></g>
      <g transform={`translate(${w * 0.83} ${g})`}><Building w={bw} h={bh} flip /></g>
      <g transform={`translate(${w * 0.66} ${g})`}>
        <path d={`M0,0 L0,${-bh * 0.6} M-14,${-bh * 0.26} L-14,${-bh * 0.44} Q-14,${-bh * 0.52} -7,${-bh * 0.52} L0,${-bh * 0.52} M14,${-bh * 0.18} L14,${-bh * 0.36} Q14,${-bh * 0.44} 7,${-bh * 0.44} L0,${-bh * 0.44}`} />
        <path d={`M-7,${-bh * 0.6} Q0,${-bh * 0.7} 7,${-bh * 0.6}`} />
      </g>
      <path d={`M${w * 0.22},${h * 0.2} q10,-16 26,-6 q10,-16 28,-4 q12,-6 14,8 Z`} fill={PAPER} strokeWidth={3} />
      <path d={`M${w * 0.7},${h * 0.14} q8,-12 20,-5 q8,-12 22,-3 q10,-4 12,7 Z`} fill={PAPER} strokeWidth={3} />
      <path d={`M0,${g} Q${w * 0.5},${g + 4} ${w},${g}`} />
    </At>
  );
}

/** The oval fence on the ellipse rx 420, ry 90 around (0,0): two rails and posts, the far side first so the near rails sit on top. */
export function Fence(at: Place) {
  const { rx, ry } = ANCHORS.fence;
  const n = 16;
  const post = (i: number) => {
    const a = (i / n) * Math.PI * 2;
    const x = (rx * Math.cos(a)).toFixed(1);
    const y = ry * Math.sin(a);
    return <path key={i} d={`M${x},${(y + 2).toFixed(1)} L${x},${(y - 28).toFixed(1)}`} />;
  };
  const idx = Array.from({ length: n }, (_, i) => i);
  return (
    <At {...at}>
      {idx.filter((i) => Math.sin((i / n) * Math.PI * 2) <= 0).map(post)}
      <ellipse cx={0} cy={-9} rx={rx} ry={ry} strokeWidth={3} />
      <ellipse cx={0} cy={-21} rx={rx} ry={ry} strokeWidth={3} />
      {idx.filter((i) => Math.sin((i / n) * Math.PI * 2) > 0).map(post)}
    </At>
  );
}
