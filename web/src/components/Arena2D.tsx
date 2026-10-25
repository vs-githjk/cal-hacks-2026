"use client";
// The 2D round board drawn as the golden hour terrace: officials on the back step under the arch, the knocked sellers walked out
// beyond it, the sellers still in on the stone floor with their sealed envelope or price tag, the buyer at the left.
// All state comes from boardAt (lib/arenaBoard.ts); looks (color, hat) from looksFor so the figures match the 3D ones.
import { useMemo, type CSSProperties, type ReactNode } from "react";
import { OriginChip } from "@/components/ui";
import type { ArenaScene } from "@/lib/arenaScene";
import { boardAt, type BoardCard, type OfficialKey } from "@/lib/arenaBoard";
import { looksFor, type HatKind } from "@/lib/arenaLayout";

export interface Arena2DProps {
  scene: ArenaScene;
  beat: number;
  frozen: boolean;
  reducedMotion: boolean;
  selected: string | null;
  onPick: (key: string) => void;
  bubbles?: Partial<Record<string, string>>;
  chrome?: { sim: boolean; countdown?: ReactNode; bids?: ReactNode };
}

// The house side keeps the token colors the rest of the app gives these roles (royal is the referee's, teal the buyer's).
const OFFICIALS: { key: OfficialKey; name: string; initial: string; color: string }[] = [
  { key: "shield", name: "Shield", initial: "S", color: "var(--accent)" },
  { key: "referee", name: "Referee", initial: "R", color: "var(--royal)" },
  { key: "advocate", name: "Advocate", initial: "A", color: "var(--mint)" },
];

/** The veto's cited page, once lib/arenaBoard carries it on the card (optional until then, so this renders either way). */
const sourceOf = (card: BoardCard) => (card as BoardCard & { sourceUrl?: string | null }).sourceUrl || undefined;

const hex = (c: number) => `#${c.toString(16).padStart(6, "0")}`;

/** A clay figure: a round body with the seller's initial and a hat (none for officials). Lit figures sit in the key light. */
function Figure({ color, hat, hatColor, initial, lit, dim, winner, small, light }: {
  color: string; hat?: HatKind; hatColor?: string; initial: string; lit?: boolean; dim?: boolean; winner?: boolean; small?: boolean; light?: boolean;
}) {
  const size = small ? "h-7 w-7 text-[11px]" : "h-11 w-11 text-[15px]";
  const ring = winner ? "terrace-winner" : lit ? "terrace-lit" : "";
  return (
    <span aria-hidden="true" className={`relative inline-grid place-items-center ${dim ? "saturate-[.35] opacity-70" : ""}`}>
      {hat && !small && <span className={`terrace-hat terrace-hat-${hat}`} style={{ "--hat": hatColor } as CSSProperties} />}
      <span
        style={{ background: color }}
        className={`grid shrink-0 place-items-center rounded-full border-2 font-display font-bold ${size} ${light ? "border-white/40 text-accent-ink" : "border-ink/15 text-ink"} ${ring}`}
      >
        {initial}
      </span>
    </span>
  );
}

/** The sealed envelope: cream paper, red wax, no price. */
function Envelope({ className = "" }: { className?: string }) {
  return (
    <span aria-hidden="true" className={`terrace-envelope relative block h-[26px] w-[40px] overflow-hidden rounded-[3px] border border-line-2 bg-panel ${className}`}>
      <span className="absolute left-0 top-0 h-[55%] w-1/2" style={{ background: "linear-gradient(135deg, transparent 49%, var(--line-2) 49.5%, var(--line-2) 50.5%, transparent 51%)" }} />
      <span className="absolute right-0 top-0 h-[55%] w-1/2" style={{ background: "linear-gradient(225deg, transparent 49%, var(--line-2) 49.5%, var(--line-2) 50.5%, transparent 51%)" }} />
      <span className="absolute left-1/2 top-[52%] h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-coral" />
    </span>
  );
}

// Until lib/arenaBoard carries card.kind, the reason word splits the rail: a rank means outbid, anything else means caught.
const isOutbid = (card: BoardCard) => /^(Ranked #\d+|Outranked)$/.test(card.reason ?? "");
const OUT_GROUPS = [
  { kind: "caught", title: "Caught" },
  { kind: "outbid", title: "Outbid" },
] as const;

/** One knocked seller: caught rows are struck and muted with the red reason word; outbid rows stay neutral and show the condition. */
function OutRow({ card, caught, selected, onPick }: { card: BoardCard; caught: boolean; selected: boolean; onPick: (key: string) => void }) {
  const source = sourceOf(card);
  return (
    <button
      type="button"
      onClick={() => onPick(card.key)}
      aria-pressed={selected}
      className={`terrace-walk grid min-h-[44px] min-w-0 max-w-full grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2 gap-y-0.5 rounded-lg px-1 py-1 text-left text-[13px] ${selected ? "ring-2 ring-accent" : ""}`}
    >
      <span className="row-span-2 pt-0.5"><Figure color={hex(card.color)} initial={card.initial} small dim={caught} /></span>
      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
        <span className={`min-w-0 break-words ${caught ? "text-ink-2 line-through" : "font-medium text-ink"}`}>{card.name}</span>
        <OriginChip origin={card.origin} />
        {card.price && <span className={`font-mono tabular-nums ${caught ? "text-muted line-through" : "text-ink-2"}`}>{card.price}</span>}
        {caught ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-coral-soft px-2 text-[12px] font-semibold text-coral">
            <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-coral" />
            {card.reason}
          </span>
        ) : (
          <>
            {card.condition && <span className="text-[12px] text-muted">{card.condition}</span>}
            <span className="rounded-full bg-soft px-2 text-[12px] font-semibold text-ink">{card.reason}</span>
          </>
        )}
      </span>
      {(card.reasonText || source) && (
        <span className="col-start-2 min-w-0 break-words text-[12px] leading-[1.3] text-ink-2">
          {card.reasonText}
          {source && (
            <>
              {card.reasonText ? " " : ""}
              <a
                href={source}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="-my-3 inline px-1 py-3 font-semibold text-sky underline underline-offset-2"
              >
                source
              </a>
            </>
          )}
        </span>
      )}
    </button>
  );
}

function Word({ card }: { card: BoardCard }) {
  if (card.state === "winner") return <span className="text-[12.5px] font-bold text-gold-ink">Winner</span>;
  if (card.rank !== null) return <span className="rounded-full bg-soft px-2 text-[12px] font-semibold text-ink">Ranked #{card.rank}</span>;
  return null;
}

export function Arena2D({ scene, beat, frozen, reducedMotion, selected, onPick, bubbles, chrome }: Arena2DProps) {
  const b = useMemo(() => boardAt(scene, beat), [scene, beat]);
  const looks = useMemo(() => looksFor(scene.offers), [scene.offers]);
  const still = reducedMotion || frozen;
  // The buyer card already says the buyer line while the round is open, so the header does not repeat it.
  const subline = b.stageNote;
  const said = OFFICIALS.find((o) => bubbles?.[o.key]);
  const sealedShown = Math.min(b.sealedCount, 8);
  const sealedMore = b.sealedCount - sealedShown;
  const picked = (key: string) => (selected === key ? "ring-2 ring-accent ring-offset-2 ring-offset-stone" : "");

  return (
    <div className={`terrace grid min-h-[380px] min-w-0 text-ink ${still ? "terrace-still [&_*]:!transition-none [&_*]:!animate-none" : ""}`}>
      {/* The back wall at golden hour: the request, the officials on their step, and whoever has walked out through the arch. */}
      <div className="terrace-sky relative grid gap-4 px-4 pb-4 pt-4 text-accent-ink sm:px-6">
        <div aria-hidden="true" className="terrace-arch" />
        <div className="relative flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-display text-[24px] font-bold leading-[1.05] tracking-[-0.02em] sm:text-[30px]">{b.request || "Floor"}</div>
            {subline && <p className="mt-1 max-w-[52ch] text-[13px] leading-[1.35] text-accent-ink/85">{subline}</p>}
          </div>
          <div className="flex items-center gap-2">
            {chrome?.countdown}
            {chrome?.sim && (
              <span title="Sample run, not this market" className="self-center rounded-md border border-dashed border-accent-ink/60 px-1.5 py-0.5 font-mono text-[11px] font-semibold tracking-[0.06em]">SIM</span>
            )}
          </div>
        </div>

        <div className="relative grid min-w-0 gap-3 sm:grid-cols-[auto_1fr] sm:items-end">
          <div className="grid gap-2">
            <div className="flex flex-wrap items-end gap-3">
              {OFFICIALS.map((o, i) => {
                const lit = (b.lit as string[]).includes(o.key);
                return (
                  <span key={o.key} className={`terrace-bob grid justify-items-center gap-1 ${lit ? "terrace-focus" : ""}`} style={{ animationDelay: `${i * 0.45}s` }}>
                    <Figure color={o.color} initial={o.initial} lit={lit} light />
                    <span className={`font-mono text-[10.5px] uppercase tracking-[0.08em] ${lit ? "font-semibold" : "text-accent-ink/80"}`}>{o.name}</span>
                  </span>
                );
              })}
            </div>
            {said && (
              <p className="terrace-bubble w-fit max-w-[46ch] rounded-xl bg-panel px-3 py-1.5 text-[12.5px] italic text-ink shadow-[0_6px_18px_rgba(43,42,51,0.18)]">
                <span className="not-italic font-semibold">{said.name}:</span> {bubbles?.[said.key]}
              </p>
            )}
          </div>

          {b.out.length > 0 && (
            <div className="grid min-w-0 max-w-full gap-2 rounded-xl bg-panel px-2.5 py-2 text-ink sm:justify-self-end">
              {OUT_GROUPS.map((g) => {
                const rows = b.out.filter((c) => isOutbid(c) === (g.kind === "outbid"));
                if (rows.length === 0) return null;
                return (
                  <div key={g.kind} className="grid min-w-0 gap-1">
                    <h3 className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink-2">{g.title}</h3>
                    {rows.map((card) => <OutRow key={card.key} card={card} caught={g.kind === "caught"} selected={selected === card.key} onPick={onPick} />)}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* The stone floor: the buyer at the left, the sellers still in with their envelope or price tag. */}
      <div className="terrace-floor grid gap-4 px-4 py-4 sm:px-6">
        <div className="grid min-w-0 items-start gap-3.5 sm:grid-cols-[200px_1fr]">
          <button
            type="button"
            onClick={() => onPick("buyer")}
            aria-pressed={selected === "buyer"}
            className={`grid content-start gap-2 rounded-2xl bg-teal p-3.5 text-left text-accent-ink sm:min-h-[148px] ${picked("buyer")}`}
          >
            <span className="flex items-center gap-2 text-[14px] font-semibold">
              <Figure color="var(--accent-ink)" initial="B" small lit={b.lit.includes("buyer")} />
              Buyer agent
            </span>
            <span className="text-[13.5px] leading-[1.35] opacity-95">{b.buyerLine}</span>
            {b.stillIn && <span className="text-[12.5px] opacity-80">{b.stillIn.k} of {b.stillIn.n} offers still in.</span>}
            {bubbles?.buyer && <span className="text-[12.5px] italic opacity-90">{bubbles.buyer}</span>}
          </button>

          <div className="flex min-w-0 flex-wrap items-end gap-2 sm:gap-3">
            {b.track.length === 0 && b.sealedCount === 0 ? (
              <p className="text-[13px] text-muted">No sealed offers yet.</p>
            ) : b.track.length === 0 ? (
              <>
                {Array.from({ length: sealedShown }, (_, i) => (
                  <span key={i} className="terrace-bob grid min-w-[72px] flex-1 basis-[72px] justify-items-center gap-1.5 rounded-2xl border border-line bg-panel/70 px-2 py-3 max-sm:max-w-[31%]" style={{ animationDelay: `${i * 0.3}s` }}>
                    <Envelope />
                    <span className="text-[12px] text-muted">Sealed</span>
                  </span>
                ))}
                {sealedMore > 0 && (
                  <span className="grid min-w-[72px] flex-1 basis-[72px] justify-items-center gap-1.5 rounded-2xl border border-line bg-panel/70 px-2 py-3">
                    <Envelope />
                    <span className="text-[12px] text-muted">+{sealedMore} more</span>
                  </span>
                )}
              </>
            ) : (
              b.track.map((card, i) => {
                const look = looks[card.key];
                const color = hex(card.color);
                const sealed = card.state === "sealed";
                const focus = card.state === "focus";
                const winner = card.state === "winner";
                const box = winner
                  ? "border-gold bg-gold-soft shadow-[0_10px_24px_rgba(43,42,51,0.14)]"
                  : focus
                    ? "-translate-y-1 border-accent bg-panel shadow-[0_10px_24px_rgba(43,42,51,0.16)]"
                    : "border-line bg-panel/80";
                return (
                  <button
                    key={card.key}
                    type="button"
                    onClick={() => onPick(card.key)}
                    aria-pressed={selected === card.key}
                    className={`terrace-bob grid min-w-[96px] flex-1 basis-[112px] justify-items-center gap-1 rounded-2xl border px-2 pb-2.5 pt-3 text-center transition-[transform,box-shadow,background-color,border-color] duration-300 max-sm:max-w-[48%] sm:max-w-[200px] ${box} ${picked(card.key)}`}
                    style={{ animationDelay: `${i * 0.4}s` }}
                  >
                    {sealed || card.price === null ? (
                      <Envelope />
                    ) : (
                      <span className={`terrace-tag rounded-md border px-1.5 font-mono text-[13px] font-semibold tabular-nums ${winner ? "border-gold bg-panel text-gold-ink" : "border-line-2 bg-panel text-ink"}`}>{card.price}</span>
                    )}
                    <Figure color={color} hat={look?.hat} hatColor={look ? hex(look.hatColor) : undefined} initial={sealed ? "" : card.initial} lit={focus} winner={winner} />
                    {sealed ? (
                      <span className="text-[12px] text-muted">Sealed bid</span>
                    ) : (
                      <>
                        <span className="flex max-w-full items-center justify-center gap-1.5">
                          <span className="truncate text-[13px] font-semibold">{card.name}</span>
                          <OriginChip origin={card.origin} />
                        </span>
                        <span className="flex flex-wrap items-center justify-center gap-1.5 text-[12px] text-muted">
                          {card.condition}
                          <Word card={card} />
                        </span>
                        {bubbles?.[card.key] && <span className="text-[12px] italic text-ink-2">{bubbles[card.key]}</span>}
                      </>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {chrome?.bids}
      </div>
    </div>
  );
}
