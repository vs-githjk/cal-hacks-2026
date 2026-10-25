// web/src/lib/arenaBoard.ts
// The 2D round board as pure state: cards on a track, an Out rail, a winner. Drawn only from the arena scene and a beat count,
// so nothing gets ahead of the story (prices, outs and the winner appear only as the beats apply them).
import type { ActorKey, ArenaScene, Phase, SceneOffer } from "./arenaScene.ts";
import { storyFor } from "./arenaScene.ts";
import { looksFor } from "./arenaLayout.ts";
import { formatMoney } from "./money.ts";
import type { Origin } from "./screens.ts";

export type CardState = "sealed" | "open" | "focus" | "out" | "winner";
export interface BoardCard {
  key: ActorKey;
  bidId: string;
  sellerId: string;
  name: string;
  origin: Origin;
  initial: string; // first letter of name, upper-cased; "?" when the name is empty
  color: number; // looksFor(scene.offers)[key].color, so discs match the 3D figures
  price: string | null; // formatMoney(landed) once opened (beat >= 1 after close), else null
  condition: string; // SceneOffer.condition
  state: CardState;
  rank: number | null; // final frame only, survivors that are not the winner and have outcome "ranked": SceneOffer.rank; else null
  reason: string | null; // out cards only: "Blocked by Shield" | "Vetoed by Advocate" | "Claim check failed" | "Refused by referee"
  reasonText: string | null; // out cards only: the Knock's reasonText (the referee's sentence)
  sourceUrl: string | null; // the advocate's cited source for a veto, or the offer's listing URL; safeUrl-checked upstream
}
export type OfficialKey = "advocate" | "shield" | "referee";
export interface BoardState {
  phase: Phase;
  request: string; // scene.requestLabel
  stageName: string | null; // beats[beat-1].name, null before the first beat
  stageNote: string | null; // beats[beat-1].caption, null before the first beat
  sealedCount: number; // envelopes to draw: scene.sealedCount while not closed; offers.length at beat 0 after close; 0 once opened
  buyerLine: string; // the buyer card's sentence for this state (rules below)
  stillIn: { k: number; n: number } | null; // after close and beat >= 1: survivors k of n offers; else null
  lit: ("buyer" | OfficialKey)[]; // who is lit this beat: beats[beat-1].focus without offer keys; [] before the first beat or when not closed
  track: BoardCard[]; // scene.offers order, out cards removed; at the final frame the winner comes first
  out: BoardCard[]; // in knock order: by beat, then by the beat's knocked order
  winner: BoardCard | null; // final frame of a closed round with winnerBidId, else null
}

const REASONS: Record<string, string> = {
  shield_block: "Blocked by Shield",
  advocate_veto: "Vetoed by Advocate",
  claim_false: "Claim check failed",
};
const reasonOf = (code: string, rank: number | null | undefined) =>
  code === "outranked" ? (rank ? `Ranked #${rank}` : "Outranked") : (REASONS[code] ?? "Refused by referee");
const OFFICIALS = new Set<string>(["buyer", "advocate", "shield", "referee"]);

export function boardAt(scene: ArenaScene, beat: number): BoardState {
  const total = scene.beats.length;
  const b = Number.isFinite(beat) ? Math.min(Math.max(Math.trunc(beat), 0), total) : 0;
  const done = scene.phase === "closed" || scene.phase === "inconsistent";
  const final = done && b >= total;
  const request = scene.requestLabel;

  if (!done) {
    const p = { roundId: scene.roundId, beat: 0, playing: false, sawOpen: false, replay: false };
    return {
      phase: scene.phase, request, stageName: null, stageNote: null, sealedCount: scene.sealedCount,
      buyerLine: storyFor(scene, p).caption, stillIn: null, lit: [], track: [], out: [], winner: null,
    };
  }

  const looks = looksFor(scene.offers);
  const wantsLine = request ? `Wants ${request}.` : "Reviewing sealed offers.";
  const card = (o: SceneOffer, state: CardState, opened: boolean): BoardCard => ({
    key: o.key, bidId: o.bidId, sellerId: o.sellerId, name: o.name, origin: o.origin,
    initial: o.name ? o.name.charAt(0).toUpperCase() : "?",
    color: looks[o.key]?.color ?? 0,
    price: opened ? formatMoney(o.landed) : null,
    condition: o.condition, state, rank: null, reason: null, reasonText: null,
    sourceUrl: o.knock?.sourceUrl ?? o.sourceUrl ?? null,
  });

  if (b === 0 && !final) {
    return {
      phase: scene.phase, request, stageName: null, stageNote: null, sealedCount: scene.offers.length,
      buyerLine: wantsLine, stillIn: null, lit: [], track: scene.offers.map((o) => card(o, "sealed", false)), out: [], winner: null,
    };
  }

  // Opened frames: beat >= 1, or the final frame of a round with no beats (inconsistent, or nothing to open).
  const current = b > 0 ? scene.beats[b - 1] : undefined;
  const knocks = scene.beats.slice(0, b).flatMap((x) => x.knocked);
  const byBid = new Map(scene.offers.map((o) => [o.bidId, o]));
  const out: BoardCard[] = [];
  for (const k of knocks) {
    const o = byBid.get(k.id);
    if (!o) continue;
    out.push({ ...card(o, "out", true), reason: reasonOf(k.reasonCode, o.rank), reasonText: k.reasonText });
  }
  const outIds = new Set(out.map((c) => c.bidId));
  const focus = new Set<ActorKey>(final ? [] : current?.focus ?? []);
  let track = scene.offers.filter((o) => !outIds.has(o.bidId)).map((o) => card(o, focus.has(o.key) ? "focus" : "open", true));

  let winner: BoardCard | null = null;
  let buyerLine = wantsLine;
  if (final) {
    if (scene.phase === "closed" && scene.winnerBidId) {
      const rest = scene.offers.filter((o) => !outIds.has(o.bidId));
      const w = rest.find((o) => o.bidId === scene.winnerBidId);
      if (w) {
        winner = card(w, "winner", true);
        track = [winner, ...rest.filter((o) => o !== w).map((o) => ({ ...card(o, "open", true), rank: o.outcome === "ranked" ? o.rank : null }))];
        buyerLine = `Pays ${winner.price} to ${winner.name}, before sales tax.`;
      }
    } else if (scene.phase === "inconsistent") {
      buyerLine = scene.problem ?? "The rows disagree. Nobody is crowned.";
    } else {
      buyerLine = "No offer passed the checks, so nobody won this round.";
    }
  }

  return {
    phase: scene.phase, request,
    stageName: current?.name ?? null, stageNote: current?.caption ?? null,
    sealedCount: 0, buyerLine,
    stillIn: b >= 1 ? { k: track.length, n: scene.offers.length } : null,
    lit: (current?.focus ?? []).filter((k): k is "buyer" | OfficialKey => OFFICIALS.has(k)),
    track, out, winner,
  };
}
