"use client";
// The 2D scene as a hand-drawn Western price showdown (SVG, black ink on white paper).
// All state comes from boardAt (lib/arenaBoard.ts); positions from westLayout (lib/arenaWest.ts).
import { useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { AnimatePresence, MotionConfig, motion, usePresence } from "motion/react";
import { OriginChip } from "@/components/ui";
import type { ArenaScene } from "@/lib/arenaScene";
import { boardAt, type BoardCard } from "@/lib/arenaBoard";
import { looksFor, type HatKind as LookHat } from "@/lib/arenaLayout";
import { westLayout, type Pt } from "@/lib/arenaWest";
import {
  ANCHORS, Appraiser, Auctioneer, Backdrop, Bubble, Cowboy, DustPuff, Gavel, Platform, PriceCard, Sheriff, Sign, Spotlight,
  type CowboyPose, type HatKind,
} from "@/components/west/art";
import { Referee, RingFence } from "@/components/west/extra";

export interface ArenaWestProps {
  scene: ArenaScene;
  beat: number;
  frozen: boolean;
  reducedMotion: boolean;
  selected: string | null;
  onPick: (key: string) => void;
  bubbles?: Partial<Record<string, string>>;
  chrome?: { sim: boolean; countdown?: ReactNode; bids?: ReactNode };
}

const INK = "#1A1A1A";
const GREY = "#777777";
const HAT: Record<LookHat, HatKind> = { party: "wide", cap: "cap", top: "bowler", beanie: "sombrero" };
const OUT_WORD = (reason: string | null): string =>
  reason === "Vetoed by Advocate" ? "Vetoed" : reason === "Claim check failed" ? "Claim failed" : reason === "Refused by referee" ? "Refused"
  : reason && /^Ranked/.test(reason) ? "Outranked" : reason ?? "Out";

const subscribe = (cb: () => void) => {
  const m = window.matchMedia("(max-width: 639px)");
  m.addEventListener("change", cb);
  return () => m.removeEventListener("change", cb);
};
const usePortrait = () => useSyncExternalStore(subscribe, () => window.matchMedia("(max-width: 639px)").matches, () => false);

const trunc = (t: string, n: number): string => (t.length > n ? `${t.slice(0, n)}...` : t);

/** Greedy wrap into at most `maxLines` lines of about `max` characters; whatever does not fit is cut with "...". */
function wrap(text: string, max: number, maxLines = 2): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = "";
  let i = 0;
  for (; i < words.length; i++) {
    const next = cur ? `${cur} ${words[i]}` : words[i]!;
    if (!cur || next.length <= max) { cur = next; continue; }
    if (lines.length === maxLines - 1) break;
    lines.push(cur);
    cur = words[i]!;
  }
  const overflow = i < words.length;
  if (cur) lines.push(cur);
  const last = lines.length - 1;
  return lines.map((l, k) => (l.length > max || (overflow && k === last) ? `${l.slice(0, max - 3)}...` : l));
}

/** Centred text lines around y = cy. A line wider than `avail` (estimated) is squeezed to fit with textLength. */
function Lines({ lines, size, lh, cy = 0, avail }: { lines: string[]; size: number; lh: number; cy?: number; avail: number }) {
  return (
    <text textAnchor="middle" fontSize={size} fill={INK} stroke="none">
      {lines.map((l, i) => {
        const est = l.length * size * 0.52;
        return (
          <tspan key={i} x="0" y={cy + (i - (lines.length - 1) / 2) * lh + size * 0.35} textLength={est > avail ? avail : undefined} lengthAdjust="spacingAndGlyphs">{l}</tspan>
        );
      })}
    </text>
  );
}

/** A speech bubble over the art Bubble (kind down); the tail tip is at `at`. Text is at least 28 units wide-view, 34 in portrait, two lines at most. */
function Said({ at, text, portrait, vw }: { at: Pt; text: string; portrait: boolean; vw: number }) {
  const fs = portrait ? 34 : 28;
  const s = portrait ? 1.55 : 1.3;
  const box = ANCHORS.bubble.down.box;
  const bw = box.w * s;
  const avail = bw - 24;
  const lines = wrap(text, Math.floor(avail / (fs * 0.52)), 2);
  const x = Math.max(110 * s + 6, Math.min(vw - 110 * s - 6, at.x));
  const y = Math.max(at.y, 6 + (ANCHORS.bubble.h + 18) * s);
  return (
    <g transform={`translate(${x} ${y})`}>
      <Bubble kind="down" scale={s} />
      <g transform={`translate(0 ${(box.y + box.h / 2) * s})`}><Lines lines={lines} size={fs} lh={fs * 1.1} avail={avail} /></g>
    </g>
  );
}

function Actor({ at, label, lit, scale, children }: { at: Pt; label: string; lit: boolean; scale: number; children: ReactNode }) {
  return (
    <g transform={`translate(${at.x} ${at.y})`}>
      {lit && <Spotlight />}
      <g transform={`scale(${scale})`}>{children}</g>
      <g transform="translate(0 70)">
        <Sign kind="small" />
        <text y="-54" textAnchor="middle" fontSize="22" fill={INK} stroke="none" textLength={Math.min(96, label.length * 12)} lengthAdjust="spacingAndGlyphs">{label}</text>
      </g>
    </g>
  );
}

interface SellerProps {
  card: BoardCard | null; // null = anonymous (names not revealed)
  at: Pt;
  signAt?: Pt;
  scale: number;
  signScale: number;
  hat: HatKind;
  pose: CowboyPose;
  selected: boolean;
  spot: boolean;
  onPick: (key: string) => void;
  showRank: boolean;
  snap: boolean;
}

function Seller({ card, at, signAt, scale, signScale, hat, pose, selected, spot, onPick, showRank, snap }: SellerProps) {
  const [present, safeToRemove] = usePresence();
  useEffect(() => {
    if (present) return;
    if (snap) { safeToRemove?.(); return; }
    const t = setTimeout(() => safeToRemove?.(), 900);
    return () => clearTimeout(t);
  }, [present, safeToRemove, snap]);
  const leaving = !present;
  const pick = card ? () => onPick(card.key) : undefined;
  const interactive = card ? { role: "button", tabIndex: 0, onClick: pick, "aria-pressed": selected,
    "aria-label": `${card.name}, ${card.price ?? "sealed"}, ${card.state}`,
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter") pick?.(); } } : {};
  const name = card ? trunc(card.name, 20) : "";
  const chipW = card ? card.origin.length * 8 + 10 : 0;
  const nameX = -88;
  const avail = 88 - chipW - 8 - nameX; // room for the name left of the chip
  const rankWord = card && showRank ? (card.state === "winner" ? "Winner" : card.rank !== null ? `Ranked #${card.rank}` : null) : null;
  return (
    <g transform={`translate(${at.x} ${at.y})`} style={{ cursor: card ? "pointer" : undefined, outline: "none" }} {...interactive}>
      <motion.g animate={{ opacity: leaving ? 0 : 1 }} transition={snap ? { duration: 0 } : { duration: 0.3, delay: leaving ? 0.3 : 0 }}>
        <g transform={`scale(${scale})`}>
          {spot && <Spotlight />}
          <rect x="-70" y="-130" width="140" height="220" fill="transparent" stroke="none" />
          <Cowboy kind={hat} pose={leaving ? "tip" : pose} />
        </g>
        {card && (
          <g transform={`translate(${signAt ? signAt.x - at.x : 0} ${signAt ? signAt.y - at.y : 70}) scale(${signScale})`}>
            <Sign kind="wide" />
            {selected && <rect x="-104" y="-100" width="208" height="64" rx="6" fill="none" stroke={INK} strokeWidth="3" />}
            <text x={nameX} y="-68" fontSize="18" fill={INK} stroke="none" textLength={Math.min(avail, name.length * 9.5)} lengthAdjust="spacingAndGlyphs">{name}</text>
            <g transform={`translate(${88 - chipW} -88)`}>
              <rect width={chipW} height="18" fill="none" stroke={INK} strokeWidth="2" />
              <text x={chipW / 2} y="13" textAnchor="middle" fontSize="12" fill={INK} stroke="none">{card.origin}</text>
            </g>
            {rankWord && <text y="-50" textAnchor="middle" fontSize="14" fill={GREY} stroke="none">{rankWord}</text>}
          </g>
        )}
      </motion.g>
      {leaving && !snap && (
        <motion.g initial={{ scale: 0.6, opacity: 1 }} animate={{ scale: 1.3, opacity: 0 }} transition={{ duration: 0.6 }}><DustPuff /></motion.g>
      )}
    </g>
  );
}

/** A price card. Its resting state comes from data: no price means sealed at the seller's hand; a price means open at its fan slot.
 * Mounted open (jumping to a late beat) it renders there at once; a change from sealed to open while mounted flies and cross-fades. */
function Card({ card, hand, to, delay, snap }: { card: BoardCard; hand: Pt; to: { x: number; y: number; rot: number; scale: number }; delay: number; snap: boolean }) {
  const open = card.price !== null;
  const pos = open ? { x: to.x, y: to.y, rot: to.rot } : { x: hand.x, y: hand.y, rot: 0 };
  const fly = snap ? { duration: 0 } : { duration: 0.6, ease: "easeOut" as const, delay };
  const fade = snap ? { duration: 0 } : { duration: 0.35, delay: open ? delay + 0.4 : 0 };
  const price = card.price ?? "";
  const cond = trunc(card.condition, 12);
  const face = ANCHORS.priceCard.face;
  return (
    <motion.g initial={false} animate={{ x: pos.x, y: pos.y, rotate: pos.rot }} transition={{ x: fly, y: fly, rotate: fly }} style={{ pointerEvents: "none" }}>
      <g transform={`scale(${to.scale})`}>
        <motion.g initial={false} animate={{ opacity: open ? 0 : 1 }} transition={fade}><PriceCard pose="sealed" /></motion.g>
        <motion.g initial={false} animate={{ opacity: open ? 1 : 0 }} transition={fade}>
          <PriceCard pose="open" />
          {open && (
            <>
              <text textAnchor="middle" x={face.x + face.w / 2} y="-3" fontSize="20" fill={INK} stroke="none" textLength={Math.min(face.w - 4, price.length * 11)} lengthAdjust="spacingAndGlyphs">{price}</text>
              <text textAnchor="middle" x={face.x + face.w / 2} y="13" fontSize="9" fill={INK} stroke="none">{cond}</text>
            </>
          )}
        </motion.g>
      </g>
    </motion.g>
  );
}

/** The compact results list under the scene: winner first, then survivors by rank, then the out cards in knock order. */
function Results({ rows }: { rows: { card: BoardCard; label: string | null }[] }) {
  return (
    <div className="border-t border-[#E8DCCB] bg-[#FFFDF8] px-4 py-3 font-sans text-[13px] text-[#2B2A33]">
      <ol aria-label="Results" className="m-0 grid list-none gap-2 p-0">
        {rows.map(({ card, label }) => (
          <li key={card.key} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="font-semibold">{card.name}</span>
            <OriginChip origin={card.origin} />
            <span>{card.price ?? "Sealed"}</span>
            {label && <span className="font-medium">{label}</span>}
            {card.reasonText && <span className="text-[12px] text-[#6b6b6b]">{card.reasonText}</span>}
            {card.sourceUrl && <a href={card.sourceUrl} target="_blank" rel="noreferrer" className="text-[12px] underline">source</a>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Smallest horizontal gap between neighbours on the same row, so wide signs can shrink to fit. */
function minGap(pts: Pt[]): number {
  let g = Infinity;
  for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) if (pts[i]!.y === pts[j]!.y) g = Math.min(g, Math.abs(pts[i]!.x - pts[j]!.x));
  return g;
}
const fitScale = (gap: number, width: number): number => Math.max(0.5, Math.min(1, (0.95 * gap) / width));

export function ArenaWest({ scene, beat, frozen, reducedMotion, selected, onPick, bubbles, chrome }: ArenaWestProps) {
  const b = useMemo(() => boardAt(scene, beat), [scene, beat]);
  const kind = scene.beats[beat - 1]?.kind;
  const looks = useMemo(() => looksFor(scene.offers), [scene.offers]);
  const portrait = usePortrait();
  const snap = reducedMotion || frozen;
  const anon = b.track.length === 0;
  const anonCount = Math.min(b.sealedCount, 8);
  const drawn = anon ? anonCount : Math.min(b.track.length, 8);
  const L = westLayout(drawn, b.out.length, portrait);
  const signs = (L as { sellerSigns?: Pt[] }).sellerSigns;
  const lit = (k: string) => b.lit.includes(k as "buyer");
  const gavel = b.winner ? "down" : "up";
  const request = bubbles?.buyer ?? (b.request ? `Looking for ${b.request}` : "Waiting for a request");
  const final = !!b.winner || (b.phase !== "open" && beat >= scene.beats.length && b.track.length > 0);
  const sealedAnon = b.track.length > 0 && b.track.every((c) => c.price === null);
  const note = b.stageNote ?? (b.phase === "closed" ? null : b.buyerLine);
  const standY = L.auctioneer.y + ANCHORS.platform.stand.y; // the auctioneer's feet, on the deck
  const cs = L.cards[0]?.scale ?? 1.5;
  const cardOf = (i: number) => L.cards[i] ?? L.cards[0] ?? { x: L.ring.cx, y: L.ring.cy, rot: 0, scale: cs };
  const hand = ANCHORS.auctioneer.gavelHand[gavel];
  const hatOf = (c: BoardCard): HatKind => HAT[looks[c.key]?.hat ?? "party"];
  const handOf = (p: Pt): Pt => ({ x: p.x + 48 * L.scale, y: p.y - 56 * L.scale });
  const said = (key: string) => bubbles?.[key];
  const bubbleAt = (p: Pt): Pt => ({ x: p.x, y: p.y - 140 * L.scale });
  const sellerSign = fitScale(minGap(L.sellers), ANCHORS.sign.wide.w);
  const outSign = fitScale(minGap(L.outs), ANCHORS.sign.small.w);

  const showResults = b.track.some((c) => c.price !== null) || b.out.length > 0;
  const rows = useMemo(() => {
    const survivors = [...b.track].sort((x, y) => (x.state === "winner" ? -1 : y.state === "winner" ? 1 : (x.rank ?? 1e9) - (y.rank ?? 1e9)));
    return [
      ...survivors.map((card) => ({ card, label: card.state === "winner" ? "Winner" : card.rank !== null ? `Ranked #${card.rank}` : null })),
      ...b.out.map((card) => ({ card, label: card.reason })),
    ];
  }, [b.track, b.out]);

  return (
    <MotionConfig reducedMotion={snap ? "always" : "user"}>
      <div className="relative bg-white text-[#1A1A1A]" style={{ fontFamily: "var(--font-hand), 'Comic Sans MS', cursive" }}>
        <svg className="block h-auto w-full" viewBox={`0 0 ${L.w} ${L.h}`} preserveAspectRatio="xMidYMid meet" role="group" aria-label="Price showdown">
          <rect width={L.w} height={L.h} fill="#FFFFFF" />
          <Backdrop scale={L.w / ANCHORS.backdrop.w} />
          <RingFence cx={L.ring.cx} cy={L.ring.cy} rx={L.ring.rx} ry={L.ring.ry} />

          {lit("buyer") && <Spotlight x={L.auctioneer.x} y={L.auctioneer.y} scale={1.8} />}
          <Auctioneer x={L.auctioneer.x} y={standY} scale={L.scale} pose={gavel} />
          <Platform x={L.auctioneer.x} y={L.auctioneer.y} />
          <Gavel x={L.auctioneer.x + hand.x * L.scale} y={standY + hand.y * L.scale} scale={L.scale} pose={gavel} />
          <text x={L.auctioneer.x - 24} y={L.auctioneer.y - 136} textAnchor="middle" fontSize="26" fill={INK} stroke="none">Buyer agent</text>
          <Actor at={L.sheriff} label="Shield" lit={lit("shield")} scale={L.scale}><Sheriff /></Actor>
          <Actor at={L.appraiser} label="Advocate" lit={lit("advocate")} scale={L.scale}><Appraiser /></Actor>
          <Actor at={L.referee} label="Referee" lit={lit("referee")} scale={L.scale}><Referee /></Actor>


          <AnimatePresence>
            {!anon && b.track.slice(0, 8).map((c, i) => (
              <Seller
                key={c.key} card={sealedAnon ? null : c} at={L.sellers[i] ?? L.ring} signAt={signs?.[i]} scale={L.scale} signScale={sellerSign} hat={sealedAnon ? "wide" : hatOf(c)}
                pose={kind === "arrive" ? "toss" : "idle"} selected={selected === c.key} spot={c.state === "focus" || c.state === "winner"}
                onPick={onPick} showRank={final} snap={snap}
              />
            ))}
          </AnimatePresence>
          {anon && Array.from({ length: anonCount }, (_, i) => L.sellers[i] && (
            <g key={i}>
              <Seller card={null} at={L.sellers[i]!} signAt={signs?.[i]} scale={L.scale} signScale={1} hat="wide" pose="idle" selected={false} spot={false} onPick={onPick} showRank={false} snap={snap} />
              <g transform={`translate(${handOf(L.sellers[i]!).x} ${handOf(L.sellers[i]!).y})`}><PriceCard pose="sealed" scale={cs} /></g>
            </g>
          ))}
          {anon && b.sealedCount > 8 && <text x={L.ring.cx} y={L.ring.cy + L.ring.ry * 0.9} textAnchor="middle" fontSize="28" fill={INK} stroke="none">+{b.sealedCount - 8} more</text>}

          {b.track.length > 0 && b.track.slice(0, 8).map((c, i) => (
            <Card key={c.key} card={c} hand={handOf(L.sellers[i] ?? L.ring)} to={cardOf(i)} delay={i * 0.08} snap={snap} />
          ))}

          {b.winner && (() => {
            const c = L.cards[0];
            return c ? (
              <g transform={`translate(${c.x} ${c.y})`}>
                <ellipse rx="100" ry="62" fill="none" stroke={INK} strokeWidth="3" strokeDasharray="10 7" />
                <text y="-72" textAnchor="middle" fontSize="30" fill={INK} stroke="none">Sold</text>
              </g>
            ) : null;
          })()}

          {b.out.map((c, k) => {
            const p = L.outs[k];
            if (!p) return null;
            return (
              <g key={c.key}>
                <g transform={`translate(${p.x} ${p.y - 56}) scale(0.7)`}><Cowboy kind={hatOf(c)} pose="ghost" /></g>
                <g
                  transform={`translate(${p.x} ${p.y}) scale(${outSign})`} role="button" tabIndex={0} style={{ cursor: "pointer", outline: "none" }}
                  aria-label={`${c.name}, ${c.reason ?? "out"}${c.reasonText ? `, ${c.reasonText}` : ""}`}
                  onClick={() => onPick(c.key)} onKeyDown={(e) => { if (e.key === "Enter") onPick(c.key); }}
                >
                  <Sign kind="small" />
                  {selected === c.key && <rect x="-64" y="-88" width="128" height="52" rx="6" fill="none" stroke={INK} strokeWidth="3" />}
                  <text y="-62" textAnchor="middle" fontSize="20" fill={INK} stroke="none" textLength={Math.min(100, OUT_WORD(c.reason).length * 11)} lengthAdjust="spacingAndGlyphs">{OUT_WORD(c.reason)}</text>
                  <text y="-49" textAnchor="middle" fontSize="12" fill="#555555" stroke="none">{trunc(c.name, 15)}</text>
                </g>
              </g>
            );
          })}

          <Said at={{ x: L.auctioneer.x, y: standY - 140 * L.scale }} text={request} portrait={portrait} vw={L.w} />
          {(["shield", "advocate", "referee"] as const).map((k) => {
            const t = said(k);
            const at = k === "shield" ? L.sheriff : k === "advocate" ? L.appraiser : L.referee;
            return t ? <Said key={k} at={bubbleAt(at)} text={t} portrait={portrait} vw={L.w} /> : null;
          })}

          {b.phase === "inconsistent" && (() => {
            const k = portrait ? 2.6 : 1.9;
            const fs = portrait ? 30 : 26;
            const box = ANCHORS.sign.wide.box;
            const avail = box.w * k - 24;
            return (
              <g transform={`translate(${L.ring.cx} ${L.ring.cy - 100 + 40 * k})`}>
                <Sign kind="wide" scale={k} />
                <g transform={`translate(0 ${(box.y + box.h / 2) * k})`}><Lines lines={wrap(b.buyerLine, Math.floor(avail / (fs * 0.52)), 3)} size={fs} lh={fs * 1.1} avail={avail} /></g>
              </g>
            );
          })()}

          {chrome?.sim && (
            <g transform={`translate(${L.w - 200} 50)`}><rect x="-8" y="-30" width="184" height="42" fill="none" stroke={INK} strokeWidth="3" /><text fontSize="28" fill={INK} stroke="none">SIM example</text></g>
          )}
        </svg>
        {note && <p className="pointer-events-none absolute left-3 top-2 m-0 line-clamp-2 max-w-[36%] text-[13px] leading-tight sm:text-[18px]">{note}</p>}
        {chrome?.countdown && <div className="absolute right-3 top-14 sm:top-16">{chrome.countdown}</div>}
        {showResults && <Results rows={rows} />}
        {chrome?.bids}
      </div>
    </MotionConfig>
  );
}
