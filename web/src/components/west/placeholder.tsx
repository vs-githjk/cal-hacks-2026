// Crude stick-figure art for the Western showdown. Same contract as the designer's art.tsx, so the import can be swapped.
const INK = "#1A1A1A";
const base = { stroke: INK, strokeWidth: 4, strokeLinecap: "round", strokeLinejoin: "round", fill: "none" } as const;

export type HatKind = "wide" | "bowler" | "sombrero" | "cap";
export type Pose = "idle" | "toss" | "fold" | "tip" | "ghost";

function Hat({ hat, rot = 0 }: { hat: HatKind; rot?: number }) {
  return (
    <g transform={`rotate(${rot} 0 -108)`}>
      {hat === "wide" && <path d="M-26 -104 H26 M-14 -104 V-122 H14 V-104" />}
      {hat === "bowler" && <path d="M-16 -106 H16 M-13 -106 A13 16 0 0 1 13 -106" />}
      {hat === "sombrero" && <path d="M-40 -102 Q0 -110 40 -102 M-10 -105 Q0 -130 10 -105" />}
      {hat === "cap" && <path d="M-16 -106 H30 M-16 -106 A16 14 0 0 1 16 -106" />}
    </g>
  );
}

function Head({ hat, rot, star }: { hat: HatKind; rot?: number; star?: boolean }) {
  return (
    <g>
      <circle cx="0" cy="-84" r="22" fill="#FFFFFF" />
      <circle cx="-7" cy="-88" r="2" fill={INK} strokeWidth="0" />
      <circle cx="7" cy="-88" r="2" fill={INK} strokeWidth="0" />
      <path d="M-8 -77 Q0 -70 8 -77" strokeWidth="3" />
      <Hat hat={hat} rot={rot} />
      {star && <path d="M0 -122 L3 -115 L10 -115 L5 -110 L7 -103 L0 -107 L-7 -103 L-5 -110 L-10 -115 L-3 -115 Z" fill={INK} strokeWidth="1" />}
    </g>
  );
}

const Body = () => <path d="M0 -62 V-28 M0 -28 L-18 0 M0 -28 L18 0" />;

export function Cowboy({ hat, pose, ink }: { hat: HatKind; pose: Pose; ink?: string }) {
  const ghost = pose === "ghost";
  const arms =
    pose === "toss" ? "M0 -52 L-20 -28 M0 -52 L28 -70 L46 -96" :
    pose === "fold" ? "M-20 -48 L20 -44 M20 -48 L-20 -42" :
    pose === "tip" ? "M0 -52 L-20 -28 M0 -52 L16 -66 L12 -100" :
    "M0 -52 L-20 -28 M0 -52 L20 -28";
  return (
    <g {...base} stroke={ink ?? INK} strokeDasharray={ghost ? "6 6" : undefined} opacity={ghost ? 0.6 : 1}>
      <Body />
      <path d={arms} />
      <Head hat={hat} rot={pose === "tip" ? 15 : 0} />
    </g>
  );
}

export function Auctioneer({ gavel }: { gavel: "up" | "down" }) {
  return (
    <g {...base}>
      <Body />
      <path d="M0 -52 L28 -56 L50 -62" />
      <path d={gavel === "up" ? "M0 -52 L-18 -64 L-30 -90" : "M0 -52 L-18 -40 L-30 -26"} />
      {gavel === "up" ? (
        <g><path d="M-30 -90 L-38 -104" /><rect x="-50" y="-114" width="20" height="10" fill={INK} transform="rotate(-30 -40 -108)" /></g>
      ) : (
        <g><path d="M-30 -26 L-30 -14" /><rect x="-42" y="-14" width="22" height="10" fill={INK} /></g>
      )}
      <Head hat="wide" />
    </g>
  );
}

export function Sheriff() {
  return (
    <g {...base}>
      <Body />
      <path d="M0 -52 L-20 -28 M0 -52 L20 -28" />
      <path d="M-8 -50 L-5 -44 L2 -44 L-3 -40 L-1 -33 L-8 -37 L-15 -33 L-13 -40 L-18 -44 L-11 -44 Z" fill={INK} strokeWidth="1" />
      <Head hat="wide" star />
    </g>
  );
}

export function Appraiser() {
  return (
    <g {...base}>
      <Body />
      <path d="M0 -52 L-20 -28 M0 -52 L16 -40" />
      <path d="M8 -50 L26 -54 L44 -50 V-30 L26 -34 L8 -30 Z M26 -54 V-34" fill="#FFFFFF" strokeWidth="3" />
      <Head hat="bowler" />
      <circle cx="-8" cy="-87" r="7" strokeWidth="2.5" />
      <circle cx="8" cy="-87" r="7" strokeWidth="2.5" />
      <path d="M-1 -87 H1" strokeWidth="2.5" />
    </g>
  );
}

export function Referee() {
  return (
    <g {...base}>
      <Body />
      <path d="M0 -52 L-20 -28 M0 -52 L18 -40" />
      <rect x="6" y="-62" width="30" height="38" fill="#FFFFFF" strokeWidth="3" />
      <path d="M12 -52 H30 M12 -44 H30 M12 -36 H26" strokeWidth="2" />
      <Head hat="cap" />
    </g>
  );
}

export function Platform() {
  return (
    <g {...base}>
      <rect x="-150" y="-110" width="300" height="110" fill="#FFFFFF" />
      <path d="M-150 -110 L150 0 M150 -110 L-150 0 M-150 -55 H150" strokeWidth="2.5" />
      <path d="M-180 0 L-150 -50 M-180 0 H-150 M180 0 L150 -50 M180 0 H150 M-165 -25 H-150 M165 -25 H150" />
      <rect x="-180" y="-120" width="360" height="12" fill="#FFFFFF" />
      <rect x="-110" y="-180" width="220" height="60" fill="#FFFFFF" />
    </g>
  );
}

export function Sign({ w, h }: { w: number; h: number }) {
  return (
    <g {...base}>
      <path d={`M${-w / 3} -16 V0 M${w / 3} -16 V0`} />
      <rect x={-w / 2} y={-h - 16} width={w} height={h} rx="3" fill="#FFFFFF" />
    </g>
  );
}

export function PriceCard({ w, h, sealed }: { w: number; h: number; sealed: boolean }) {
  return (
    <g {...base}>
      <rect x={-w / 2} y={-h / 2} width={w} height={h} rx="3" fill="#FFFFFF" />
      {sealed && (
        <g>
          <path d={`M${-w / 2} ${-h / 2} L${w / 2} ${h / 2}`} strokeWidth="2.5" />
          <circle cx="0" cy="0" r="6" fill={INK} />
        </g>
      )}
    </g>
  );
}

export function Bubble({ w, h, tail }: { w: number; h: number; tail: "down" | "left" | "right" }) {
  const t = 18;
  return (
    <g {...base}>
      {tail === "down" && (
        <g>
          <rect x={-w / 2} y={-h - t} width={w} height={h} rx="14" fill="#FFFFFF" />
          <path d={`M-12 ${-t} L0 0 L12 ${-t}`} fill="#FFFFFF" />
          <path d={`M-10 ${-t} H10`} stroke="#FFFFFF" strokeWidth="6" />
        </g>
      )}
      {tail === "left" && (
        <g>
          <rect x={t} y={-h / 2} width={w} height={h} rx="14" fill="#FFFFFF" />
          <path d={`M${t} ${-8} L0 0 L${t} 8`} fill="#FFFFFF" />
          <path d={`M${t} -6 V6`} stroke="#FFFFFF" strokeWidth="6" />
        </g>
      )}
      {tail === "right" && (
        <g>
          <rect x={-t - w} y={-h / 2} width={w} height={h} rx="14" fill="#FFFFFF" />
          <path d={`M${-t} ${-8} L0 0 L${-t} 8`} fill="#FFFFFF" />
          <path d={`M${-t} -6 V6`} stroke="#FFFFFF" strokeWidth="6" />
        </g>
      )}
    </g>
  );
}

export function DustPuff() {
  return (
    <g {...base} fill="#FFFFFF" strokeWidth="3">
      <circle cx="-16" cy="-8" r="14" />
      <circle cx="12" cy="-14" r="18" />
      <circle cx="22" cy="2" r="10" />
      <circle cx="-4" cy="4" r="12" />
    </g>
  );
}

export function Spotlight() {
  return (
    <g {...base} strokeWidth="2.5" strokeDasharray="8 6">
      <ellipse cx="0" cy="0" rx="100" ry="30" />
      <ellipse cx="0" cy="0" rx="70" ry="20" />
      <ellipse cx="0" cy="0" rx="40" ry="12" />
    </g>
  );
}

export function Backdrop({ w, h }: { w: number; h: number }) {
  const hill = `M0 ${h * 0.45} L${w * 0.1} ${h * 0.3} L${w * 0.2} ${h * 0.4} L${w * 0.32} ${h * 0.22} L${w * 0.45} ${h * 0.4} L${w * 0.6} ${h * 0.3} L${w * 0.75} ${h * 0.42} L${w * 0.88} ${h * 0.25} L${w} ${h * 0.4} V${h * 0.5} H0 Z`;
  const building = (cx: number) => (
    <g key={cx} {...base}>
      <rect x={cx - 70} y={h * 0.28} width="140" height={h * 0.18} fill="#FFFFFF" />
      <path d={`M${cx - 80} ${h * 0.28} L${cx} ${h * 0.2} L${cx + 80} ${h * 0.28} Z`} fill="#FFFFFF" />
      <rect x={cx - 14} y={h * 0.36} width="28" height={h * 0.1} />
    </g>
  );
  const cx = w * 0.65;
  const cloud = (x: number, y: number) => <path key={x} d={`M${x} ${y} q0 -24 24 -24 q10 -22 36 -8 q26 -4 24 22 q20 4 0 10 H${x} Z`} {...base} strokeWidth="3" fill="#FFFFFF" />;
  return (
    <g>
      <path d={hill} fill="#D9D9D9" stroke="none" />
      {building(w * 0.15)}
      {building(w * 0.85)}
      <g {...base}>
        <path d={`M${cx} ${h * 0.46} V${h * 0.3} M${cx} ${h * 0.4} H${cx - 20} V${h * 0.35} M${cx} ${h * 0.37} H${cx + 20} V${h * 0.32}`} />
      </g>
      {cloud(w * 0.25, h * 0.14)}
      {cloud(w * 0.78, h * 0.12)}
    </g>
  );
}

export function Fence({ cx, cy, rx, ry }: { cx: number; cy: number; rx: number; ry: number }) {
  const posts = Array.from({ length: 16 }, (_, i) => {
    const a = (i / 16) * Math.PI * 2;
    const x = cx + rx * Math.cos(a), y = cy + ry * Math.sin(a);
    return <path key={i} d={`M${x} ${y - 26} V${y + 4}`} strokeWidth="6" />;
  });
  return (
    <g {...base}>
      <ellipse cx={cx} cy={cy} rx={rx} ry={ry} />
      <ellipse cx={cx} cy={cy} rx={rx} ry={ry - 12} />
      {posts}
    </g>
  );
}
