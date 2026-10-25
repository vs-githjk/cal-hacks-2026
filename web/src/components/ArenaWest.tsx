"use client";
// The 2D scene as a hand-drawn Western price showdown (SVG, black ink on white paper).
// All state comes from boardAt (lib/arenaBoard.ts); positions from westLayout (lib/arenaWest.ts).
import { useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { AnimatePresence, MotionConfig, motion, usePresence } from "motion/react";
import type { ArenaScene } from "@/lib/arenaScene";
import { boardAt, type BoardCard } from "@/lib/arenaBoard";
import { looksFor, type HatKind as LookHat } from "@/lib/arenaLayout";
import { westLayout, type Pt } from "@/lib/arenaWest";
import {
  Appraiser, Auctioneer, Backdrop, Bubble, Cowboy, DustPuff, Fence, Platform, PriceCard, Referee, Sheriff, Sign, Spotlight,
  type HatKind, type Pose,
} from "@/components/west/placeholder";

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

/** Split into at most two lines of about `max` characters. */
function wrap(text: string, max = 22): string[] {
  const lines: string[] = [];
  let cur = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    if (cur && (cur + " " + word).length > max && lines.length < 1) { lines.push(cur); cur = word; } else cur = cur ? `${cur} ${word}` : word;
  }
  if (cur) lines.push(cur);
  return lines.slice(0, 2).map((l, i, a) => (i === 1 && a.length === 2 && l.length > max + 6 ? l.slice(0, max + 3) : l));
}

function Lines({ lines, size, dy = 0 }: { lines: string[]; size: number; dy?: number }) {
  return (
    <text textAnchor="middle" fontSize={size} fill={INK} stroke="none">
      {lines.map((l, i) => <tspan key={i} x="0" y={dy + (i - (lines.length - 1) / 2) * size * 1.05}>{l}</tspan>)}
    </text>
  );
}

function Said({ at, text, w = 190, h = 60 }: { at: Pt; text: string; w?: number; h?: number }) {
  return (
    <g transform={`translate(${at.x} ${at.y})`}>
      <Bubble w={w} h={h} tail="down" />
      <g transform={`translate(0 ${-h / 2 - 18})`}><Lines lines={wrap(text, 24)} size={20} dy={7} /></g>
    </g>
  );
}

function Actor({ at, label, lit, children }: { at: Pt; label: string; lit: boolean; children: ReactNode }) {
  return (
    <g transform={`translate(${at.x} ${at.y})`}>
      {lit && <Spotlight />}
      {children}
      <g transform="translate(0 6)"><Sign w={140} h={44} /><text y="-28" textAnchor="middle" fontSize="26" fill={INK} stroke="none">{label}</text></g>
    </g>
  );
}

interface SellerProps {
  card: BoardCard | null; // null = anonymous (names not revealed)
  at: Pt;
  scale: number;
  hat: HatKind;
  pose: Pose;
  selected: boolean;
  spot: boolean;
  onPick: (key: string) => void;
  showRank: boolean;
  hold?: { final: boolean; previous: string[] };
}

function Seller({ card, at, scale, hat, pose, selected, spot, onPick, showRank, hold }: SellerProps) {
  const [present, safeToRemove] = usePresence();
  useEffect(() => {
    if (present) return;
    const t = setTimeout(() => safeToRemove?.(), 900);
    return () => clearTimeout(t);
  }, [present, safeToRemove]);
  const leaving = !present;
  const pick = card ? () => onPick(card.key) : undefined;
  const interactive = card ? { role: "button", tabIndex: 0, onClick: pick, "aria-pressed": selected,
    "aria-label": `${card.name}, ${card.price ?? "sealed"}, ${card.state}`,
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter") pick?.(); } } : {};
  return (
    <g transform={`translate(${at.x} ${at.y}) scale(${scale})`} style={{ cursor: card ? "pointer" : undefined, outline: "none" }} {...interactive}>
      <motion.g animate={{ opacity: leaving ? 0 : 1 }} transition={{ duration: 0.3, delay: leaving ? 0.3 : 0 }}>
        {spot && <Spotlight />}
        <rect x="-70" y="-130" width="140" height="220" fill="transparent" stroke="none" />
        <Cowboy hat={hat} pose={leaving ? "tip" : pose} />
        {card && (
          <g transform="translate(0 70)">
            <Sign w={170} h={44} />
            {selected && <rect x="-90" y="-66" width="180" height="54" rx="4" fill="none" stroke={INK} strokeWidth="3" />}
            <text y="-24" textAnchor="middle" fontSize="20" fill={INK} stroke="none">{card.name.length > 14 ? `${card.name.slice(0, 13)}.` : card.name}</text>
            <g transform="translate(112 -30)"><rect x="-4" y="-16" width={card.origin.length * 11 + 8} height="22" fill="none" stroke={INK} strokeWidth="2" /><text fontSize="14" fill={INK} stroke="none">{card.origin}</text></g>
            {showRank && card.rank !== null && <text y="30" textAnchor="middle" fontSize="18" fill={GREY} stroke="none">Ranked #{card.rank}</text>}
          </g>
        )}
        {hold && (
          <g transform="translate(70 -10)">
            {hold.previous.map((p, i) => <g key={i} transform={`translate(${i * 8} ${-i * 8})`}><PriceCard w={60} h={40} sealed={false} /><text textAnchor="middle" y="6" fontSize="16" fill={GREY} stroke="none">{p}</text></g>)}
            {hold.final && <g transform="translate(0 40)"><rect x="-44" y="-12" width="88" height="22" fill="#FFFFFF" stroke={INK} strokeWidth="2" /><text textAnchor="middle" y="4" fontSize="15" fill={INK} stroke="none">Final offer</text></g>}
          </g>
        )}
      </motion.g>
      {leaving && (
        <motion.g initial={{ scale: 0.6, opacity: 1 }} animate={{ scale: 1.3, opacity: 0 }} transition={{ duration: 0.6 }}><DustPuff /></motion.g>
      )}
    </g>
  );
}

/** A card face: sealed envelope-ish or the price. The two faces flip at the midpoint of the scaleX squash. */
function Card({ card, from, to, scale, delay }: { card: BoardCard; from: Pt; to: { x: number; y: number; rot: number }; scale: number; delay: number }) {
  const open = card.price !== null;
  const t = { duration: 0.6, ease: "easeOut" as const, delay };
  const flip = { duration: 0.4, delay: delay + 0.6, times: [0, 0.49, 0.5, 1] };
  return (
    <motion.g
      initial={{ x: from.x, y: from.y, rotate: 0, scaleX: 1 }}
      animate={open ? { x: to.x, y: to.y, rotate: to.rot, scaleX: [1, 0, 0, 1] } : { x: from.x, y: from.y, rotate: 0, scaleX: 1 }}
      transition={{ x: t, y: t, rotate: t, scaleX: flip }}
      style={{ pointerEvents: "none" }}
    >
      <g transform={`scale(${open ? 1 : scale})`}>
        <motion.g initial={{ opacity: 1 }} animate={{ opacity: open ? [1, 1, 0, 0] : 1 }} transition={flip}><PriceCard w={110} h={70} sealed /></motion.g>
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: open ? [0, 0, 1, 1] : 0 }} transition={flip}>
          <PriceCard w={110} h={70} sealed={false} />
          <text textAnchor="middle" y="4" fontSize="34" fill={INK} stroke="none">{card.price}</text>
          <text textAnchor="middle" y="24" fontSize="16" fill={INK} stroke="none">{card.condition.length > 16 ? card.condition.slice(0, 15) : card.condition}</text>
        </motion.g>
      </g>
    </motion.g>
  );
}

export function ArenaWest({ scene, beat, frozen, reducedMotion, selected, onPick, bubbles, chrome }: ArenaWestProps) {
  const b = useMemo(() => boardAt(scene, beat), [scene, beat]);
  const kind = scene.beats[beat - 1]?.kind;
  const looks = useMemo(() => looksFor(scene.offers), [scene.offers]);
  const portrait = usePortrait();
  const anon = b.track.length === 0;
  const anonCount = Math.min(b.sealedCount, 8);
  const drawn = anon ? anonCount : Math.min(b.track.length, 8);
  const L = westLayout(drawn, b.out.length, portrait);
  const lit = (k: string) => b.lit.includes(k as "buyer");
  const gavel = b.winner ? "down" : "up";
  const request = bubbles?.buyer ?? (b.request ? `Looking for ${b.request}` : "Waiting for a request");
  const final = !!b.winner || (b.phase !== "open" && beat >= scene.beats.length && b.track.length > 0);
  const sealedAnon = b.track.length > 0 && b.track.every((c) => c.price === null);
  const note = b.stageNote ?? (b.phase === "closed" ? null : b.buyerLine);
  const aY = L.auctioneer.y - 120; // feet on the platform deck
  const hatOf = (c: BoardCard): HatKind => HAT[looks[c.key]?.hat ?? "party"];
  const handOf = (p: Pt): Pt => ({ x: p.x + 30 * L.scale, y: p.y - 70 * L.scale });
  const said = (key: string) => bubbles?.[key];
  const bubbleAt = (p: Pt): Pt => ({ x: p.x, y: p.y - 140 });

  return (
    <MotionConfig reducedMotion={reducedMotion || frozen ? "always" : "user"}>
      <div className="relative bg-white text-[#1A1A1A]" style={{ fontFamily: "var(--font-hand), 'Comic Sans MS', cursive" }}>
        <svg className="block h-auto w-full" viewBox={`0 0 ${L.w} ${L.h}`} preserveAspectRatio="xMidYMid meet" role="group" aria-label="Price showdown">
          <rect width={L.w} height={L.h} fill="#FFFFFF" />
          <Backdrop w={L.w} h={L.h} />
          <Fence {...L.ring} />

          <g transform={`translate(${L.auctioneer.x} ${L.auctioneer.y})`}>
            {lit("buyer") && <Spotlight />}
            <Platform />
            <text y="-136" textAnchor="middle" fontSize="38" fill={INK} stroke="none">Buyer agent</text>
          </g>
          <g transform={`translate(${L.auctioneer.x} ${aY})`}><Auctioneer gavel={gavel} /></g>
          <Actor at={L.sheriff} label="Shield" lit={lit("shield")}><Sheriff /></Actor>
          <Actor at={L.appraiser} label="Advocate" lit={lit("advocate")}><Appraiser /></Actor>
          <Actor at={L.referee} label="Referee" lit={lit("referee")}><Referee /></Actor>

          {b.phase === "inconsistent" && (
            <g transform={`translate(${L.ring.cx} ${L.ring.cy + 20})`}><Sign w={320} h={64} /><text y="-30" textAnchor="middle" fontSize="34" fill={INK} stroke="none">Winner under review</text></g>
          )}

          <AnimatePresence>
            {!anon && b.track.slice(0, 8).map((c, i) => (
              <Seller
                key={c.key} card={sealedAnon ? null : c} at={L.sellers[i] ?? L.ring} scale={L.scale} hat={sealedAnon ? "wide" : hatOf(c)}
                pose={kind === "arrive" ? "toss" : "idle"} selected={selected === c.key} spot={c.state === "focus" || c.state === "winner"}
                onPick={onPick} showRank={final}
              />
            ))}
          </AnimatePresence>
          {anon && Array.from({ length: anonCount }, (_, i) => L.sellers[i] && (
            <g key={i}>
              <Seller card={null} at={L.sellers[i]!} scale={L.scale} hat="wide" pose="idle" selected={false} spot={false} onPick={onPick} showRank={false} />
              <g transform={`translate(${handOf(L.sellers[i]!).x} ${handOf(L.sellers[i]!).y}) scale(${L.scale})`}><PriceCard w={110} h={70} sealed /></g>
            </g>
          ))}
          {anon && b.sealedCount > 8 && <text x={L.ring.cx} y={L.ring.cy + L.ring.ry * 0.9} textAnchor="middle" fontSize="28" fill={INK} stroke="none">+{b.sealedCount - 8} more</text>}

          {b.track.length > 0 && b.track.slice(0, 8).map((c, i) => (
            <Card key={c.key} card={sealedAnon ? { ...c, price: null } : c} from={handOf(L.sellers[i] ?? L.ring)} to={L.cards[i] ?? L.cards[0] ?? { x: L.ring.cx, y: L.ring.cy, rot: 0 }} scale={L.scale} delay={i * 0.08} />
          ))}

          {b.winner && (() => {
            const c = L.cards[0];
            return c ? (
              <g transform={`translate(${c.x} ${c.y})`}>
                <ellipse rx="86" ry="56" fill="none" stroke={INK} strokeWidth="3" strokeDasharray="10 7" />
                <text y="-66" textAnchor="middle" fontSize="30" fill={INK} stroke="none">Sold</text>
              </g>
            ) : null;
          })()}

          {b.out.map((c, k) => {
            const p = L.outs[k];
            if (!p) return null;
            return (
              <g key={c.key}>
                <g transform={`translate(${p.x} ${p.y - 56}) scale(0.7)`}><Cowboy hat={hatOf(c)} pose="ghost" /></g>
                <g
                  transform={`translate(${p.x} ${p.y})`} role="button" tabIndex={0} style={{ cursor: "pointer", outline: "none" }}
                  aria-label={`${c.name}, ${c.reason ?? "out"}${c.reasonText ? `, ${c.reasonText}` : ""}`}
                  onClick={() => onPick(c.key)} onKeyDown={(e) => { if (e.key === "Enter") onPick(c.key); }}
                >
                  <Sign w={200} h={56} />
                  {selected === c.key && <rect x="-106" y="-78" width="212" height="68" rx="4" fill="none" stroke={INK} strokeWidth="3" />}
                  <text y="-44" textAnchor="middle" fontSize="26" fill={INK} stroke="none">{OUT_WORD(c.reason)}</text>
                  <text y="-26" textAnchor="middle" fontSize="15" fill={GREY} stroke="none">{c.name.length > 22 ? `${c.name.slice(0, 21)}.` : c.name}</text>
                  {c.sourceUrl && <a href={c.sourceUrl} target="_blank" rel="noreferrer"><text y="22" textAnchor="middle" fontSize="16" fill={INK} textDecoration="underline" stroke="none">source</text></a>}
                </g>
              </g>
            );
          })}

          <Said at={{ x: L.request.x + 40, y: Math.min(L.request.y, aY - 135) }} text={request} w={portrait ? 240 : 270} h={portrait ? 90 : 84} />
          {(["shield", "advocate", "referee"] as const).map((k) => {
            const t = said(k);
            const at = k === "shield" ? L.sheriff : k === "advocate" ? L.appraiser : L.referee;
            return t ? <Said key={k} at={bubbleAt(at)} text={t} w={170} h={56} /> : null;
          })}

          {chrome?.sim && (
            <g transform={`translate(${L.w - 200} 50)`}><rect x="-8" y="-30" width="184" height="42" fill="none" stroke={INK} strokeWidth="3" /><text fontSize="28" fill={INK} stroke="none">SIM example</text></g>
          )}
        </svg>
        {note && <p className="pointer-events-none absolute left-3 top-2 m-0 line-clamp-2 max-w-[55%] text-[15px] leading-tight sm:text-[20px]">{note}</p>}
        {chrome?.countdown && <div className="absolute right-3 top-14 sm:top-16">{chrome.countdown}</div>}
        {chrome?.bids}
      </div>
    </MotionConfig>
  );
}
