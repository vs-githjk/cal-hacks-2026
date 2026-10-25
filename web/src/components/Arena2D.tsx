"use client";
// The 2D round board: one sealed round as cards on a track, an Out rail and a winner. All state comes from boardAt (lib/arenaBoard.ts).
import { useMemo, type ReactNode } from "react";
import { OriginChip } from "@/components/ui";
import type { ArenaScene } from "@/lib/arenaScene";
import { boardAt, type BoardCard, type OfficialKey } from "@/lib/arenaBoard";

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

const OFFICIALS: { key: OfficialKey; name: string; initial: string; color: string }[] = [
  { key: "advocate", name: "Advocate", initial: "A", color: "#4B4B4E" },
  { key: "shield", name: "Shield", initial: "S", color: "#5B7FA6" },
  { key: "referee", name: "Referee", initial: "R", color: "#2B2A33" },
];

const hex = (c: number) => `#${c.toString(16).padStart(6, "0")}`;

function Disc({ card, size }: { card: BoardCard; size: 28 | 18 }) {
  return (
    <span
      aria-hidden="true"
      style={{ background: hex(card.color) }}
      className={`grid shrink-0 place-items-center rounded-full font-bold text-[#2B2A33] ${size === 28 ? "h-7 w-7 text-[12px]" : "h-[18px] w-[18px] text-[10px] saturate-50"}`}
    >
      {card.initial}
    </span>
  );
}

function SealedCard({ label }: { label?: string }) {
  return (
    <div className="grid min-h-[118px] max-w-[200px] flex-1 basis-[150px] content-center justify-items-center gap-2 rounded-2xl border border-[#E8DCCB] bg-[#FFF4E2] px-3.5 py-3 shadow-[0_4px_14px_rgba(60,40,30,0.10)] max-sm:min-h-0 max-sm:max-w-none max-sm:grid-cols-[auto_1fr] max-sm:justify-items-start">
      <div aria-hidden="true" className="relative h-9 w-[54px] overflow-hidden rounded-[4px] border border-[#D9C8AE] bg-[#FBF4E6]">
        <div className="absolute left-0 top-0 h-[55%] w-1/2" style={{ background: "linear-gradient(135deg, transparent 49%, #D9C8AE 49.5%, #D9C8AE 50.5%, transparent 51%)" }} />
        <div className="absolute right-0 top-0 h-[55%] w-1/2" style={{ background: "linear-gradient(225deg, transparent 49%, #D9C8AE 49.5%, #D9C8AE 50.5%, transparent 51%)" }} />
        <div className="absolute left-1/2 top-[52%] h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#C8553D]" />
      </div>
      <span className="text-[12.5px] text-[#8A7A66]">{label ?? "Sealed"}</span>
    </div>
  );
}

function Word({ card }: { card: BoardCard }) {
  if (card.state === "winner") return <span className="text-[12.5px] font-bold text-[#8A6A22]">Winner</span>;
  if (card.rank !== null) return <span className="rounded-full bg-[#F3E8D6] px-2 text-[12px] font-semibold text-[#2B2A33]">Ranked #{card.rank}</span>;
  return null;
}

export function Arena2D({ scene, beat, frozen, reducedMotion, selected, onPick, bubbles, chrome }: Arena2DProps) {
  const b = useMemo(() => boardAt(scene, beat), [scene, beat]);
  const still = reducedMotion || frozen;
  const subline = b.stageNote ?? (b.phase !== "closed" ? b.buyerLine : null);
  const said = OFFICIALS.find((o) => bubbles?.[o.key]);
  const sealedShown = Math.min(b.sealedCount, 8);
  const sealedMore = b.sealedCount - sealedShown;

  return (
    <div className={`grid min-h-[380px] gap-4 bg-[linear-gradient(180deg,#FFF6EA,#F6E2CC)] px-5 py-5 text-[#2B2A33] sm:px-6 ${still ? "[&_*]:!transition-none [&_*]:!animate-none" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[22px] font-bold leading-[1.1] tracking-[-0.02em]">{b.request || "Floor"}</div>
          {subline && <p className="mt-0.5 text-[13px] text-[#6E675F]">{subline}</p>}
        </div>
        <div className="flex items-center gap-2">
          {chrome?.countdown}
          {chrome?.sim && (
            <span title="Sample run, not this market" className="self-center rounded-md border border-dashed border-[#2B2A33]/50 px-1.5 py-0.5 font-mono text-[11px] font-semibold tracking-[0.06em]">SIM</span>
          )}
        </div>
      </div>

      <div className="grid gap-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {OFFICIALS.map((o) => (
            <span
              key={o.key}
              className={`inline-flex h-[30px] items-center gap-[7px] rounded-full border bg-white pl-[5px] pr-2.5 text-[13px] ${(b.lit as string[]).includes(o.key) ? "border-[#2F3E66] font-semibold shadow-[0_0_0_3px_rgba(47,62,102,0.18)]" : "border-[#E8DCCB] font-medium"}`}
            >
              <span aria-hidden="true" style={{ background: o.color }} className="grid h-5 w-5 place-items-center rounded-full text-[11px] font-bold text-white">{o.initial}</span>
              {o.name}
            </span>
          ))}
        </div>
        {said && <p className="text-[12.5px] italic text-[#6E675F]">{said.name}: {bubbles?.[said.key]}</p>}
      </div>

      <div className="grid items-start gap-3.5 sm:grid-cols-[200px_1fr]">
        <button
          type="button"
          onClick={() => onPick("buyer")}
          aria-pressed={selected === "buyer"}
          className={`grid content-start gap-2 rounded-2xl bg-[#2F6F6A] p-3.5 text-left text-white sm:min-h-[148px] ${selected === "buyer" ? "ring-2 ring-[#2F3E66] ring-offset-2 ring-offset-[#F6E2CC]" : ""}`}
        >
          <span className="flex items-center gap-2 text-[14px] font-semibold">
            <span aria-hidden="true" className={`grid h-5 w-5 place-items-center rounded-full bg-white text-[11px] font-bold text-[#2F6F6A] ${b.lit.includes("buyer") ? "ring-2 ring-white/70" : ""}`}>B</span>
            Buyer agent
          </span>
          <span className="text-[13.5px] leading-[1.35] opacity-95">{b.buyerLine}</span>
          {b.stillIn && <span className="text-[12.5px] opacity-80">{b.stillIn.k} of {b.stillIn.n} offers still in.</span>}
          {bubbles?.buyer && <span className="text-[12.5px] italic opacity-90">{bubbles.buyer}</span>}
        </button>

        <div className="flex flex-wrap gap-3 max-sm:flex-col">
          {b.track.length === 0 && b.sealedCount === 0 ? (
            <p className="text-[13px] text-[#6E675F]">No sealed offers yet.</p>
          ) : b.track.length === 0 ? (
            <>
              {Array.from({ length: sealedShown }, (_, i) => <SealedCard key={i} />)}
              {sealedMore > 0 && <SealedCard label={`+${sealedMore} more`} />}
            </>
          ) : (
            b.track.map((card) => {
              if (card.state === "sealed") return <SealedCard key={card.key} />;
              const stateCls =
                card.state === "focus"
                  ? "-translate-y-1 border-[#2F3E66] bg-white shadow-[0_10px_24px_rgba(60,40,30,0.18),0_0_0_3px_rgba(47,62,102,0.22)]"
                  : card.state === "winner"
                    ? "border-[#D4A548] bg-[#FFF6DD] shadow-[0_10px_24px_rgba(60,40,30,0.18),0_0_0_3px_rgba(212,165,72,0.35)]"
                    : "border-[#E8DCCB] bg-white shadow-[0_4px_14px_rgba(60,40,30,0.10)]";
              return (
                <button
                  key={card.key}
                  type="button"
                  onClick={() => onPick(card.key)}
                  aria-pressed={selected === card.key}
                  className={`grid max-w-[250px] flex-1 basis-[190px] grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1.5 rounded-2xl border px-3.5 py-3 text-left transition-[transform,box-shadow,background-color] duration-300 max-sm:max-w-none max-sm:basis-auto max-sm:grid-cols-[auto_minmax(0,1fr)_auto] max-sm:gap-x-2.5 max-sm:gap-y-0.5 max-sm:px-3 max-sm:py-2.5 ${stateCls} ${selected === card.key ? "ring-2 ring-[#2F6F6A] ring-offset-2 ring-offset-[#F6E2CC]" : ""}`}
                >
                  <span className="col-start-1 row-start-1 max-sm:row-span-2"><Disc card={card} size={28} /></span>
                  <span className="col-start-2 row-start-1 flex min-w-0 items-center gap-2">
                    <span className="truncate text-[14px] font-semibold">{card.name}</span>
                    <OriginChip origin={card.origin} />
                  </span>
                  <span className="col-span-2 row-start-2 font-mono text-[22px] font-semibold tabular-nums tracking-[-0.01em] max-sm:col-span-1 max-sm:col-start-3 max-sm:row-span-2 max-sm:row-start-1 max-sm:text-[18px]">{card.price}</span>
                  <span className="col-span-2 row-start-3 flex flex-wrap items-center gap-2 text-[12.5px] text-[#6E675F] max-sm:col-span-1 max-sm:col-start-2 max-sm:row-start-2">
                    {card.condition}
                    <Word card={card} />
                  </span>
                  {bubbles?.[card.key] && <span className="col-span-full row-start-4 text-[12.5px] italic text-[#6E675F] max-sm:row-start-3">{bubbles[card.key]}</span>}
                </button>
              );
            })
          )}
        </div>
      </div>

      {b.out.length > 0 && (
        <div className="grid gap-1.5 border-t border-[#E2D3BE] pt-2.5">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#6E675F]">Out</h3>
          {b.out.map((card) => (
            <button
              key={card.key}
              type="button"
              onClick={() => onPick(card.key)}
              aria-pressed={selected === card.key}
              className="flex animate-[board-in_300ms_ease-out] flex-wrap items-center gap-2.5 text-left text-[13.5px] opacity-80"
            >
              <Disc card={card} size={18} />
              <span className="text-[#6E675F] line-through">{card.name}</span>
              <OriginChip origin={card.origin} />
              <span className="font-mono tabular-nums text-[#6E675F]">{card.price}</span>
              <span className="rounded-full bg-[#FBE9E4] px-2 text-[12px] font-semibold text-[#A8432F]">{card.reason}</span>
              {card.reasonText && <span className="text-[12.5px] text-[#6E675F]">{card.reasonText}</span>}
            </button>
          ))}
        </div>
      )}

      {chrome?.bids}
    </div>
  );
}
