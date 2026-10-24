// web/src/lib/arenaScene.ts
// The 3D arena's story for one round, drawn only from public market rows: round, seller_needs, round_result, floor_event.
// While a round is open only its own row is round-scoped (sealed count, deadline), so offers stay anonymous envelopes.
// After close, round_result names every bid and each check event links to its bid by refId; the close plays as beats.
// Nothing here ranks: order and winner are the referee's (round_result.rank, cross-checked with auction_closed).
import { formatMoney } from "./money.ts";
import { safeUrl } from "./url.ts";
import { asOrigin, type Origin } from "./screens.ts";
import { buildBracket, roundWinner, type Bracket, type Knock } from "./bracket.ts";

type Ts = { microsSinceUnixEpoch: bigint }; // spacetimedb Timestamp, structurally, so node tests need no runtime import

export interface RoundRow { id: string; needId: string; openedAt: Ts; deadline: Ts; state: string; sealedCount: number; closedAt?: Ts; origin: string }
/** seller_needs: public for open rounds only. ceilingBand is budget-derived and is never read here. */
export interface NeedRow { roundId: string; skuSpec: string; condition: string; quantity: number; unit: string }
export interface LineRow { skuSpec: string; offeredSpec: string; offeredCondition: string; unitPrice: number; quantity: number }
export interface ResultRow { id: bigint; roundId: string; bidId: string; sellerId: string; persona: string; rank: number; landed: number; reasons: string[]; lines: LineRow[]; origin: string; source: string }
export interface EventRow { id: bigint; kind: string; refTable: string; refId: string; sellerId: string; label: string; origin: string; at: Ts }

export interface ArenaRows { rounds: readonly RoundRow[]; needs: readonly NeedRow[]; results: readonly ResultRow[]; events: readonly EventRow[] }

/** waiting: no round. open: sealed window running. closing: closed, result rows not here yet. closed: result known. inconsistent: rows disagree, nobody is crowned. */
export type Phase = "waiting" | "open" | "closing" | "closed" | "inconsistent";

/** Actor keys shared by the scene, the renderer and the page: fixed characters plus one per offer. */
export type ActorKey = "buyer" | "advocate" | "shield" | "referee" | `offer:${string}`;
export const offerKey = (bidId: string): ActorKey => `offer:${bidId}`;

export interface EventRef { id: string; kind: string; label: string; origin: Origin } // floor_event/<id>, linked by refId === bidId
export interface SceneOffer {
  key: ActorKey;
  bidId: string;
  rowRef: string; // round_result/<id>
  sellerId: string;
  name: string;
  origin: Origin;
  landed: number; // before sales tax; only exists after close because round_result only exists after close
  product: string; // humanized offeredSpec of the first line
  rank: number | null; // null when the referee did not rank it
  outcome: "winner" | "ranked" | "knocked";
  knock?: Knock; // why it left (gate refusal, advocate veto, or outranked), from bracket.ts
  sourceUrl?: string; // safeUrl-checked
  events: EventRef[];
}

export type BeatKind = "arrive" | "gate" | "advocate" | "knockout" | "crown";
export interface Beat {
  kind: BeatKind;
  name: string; // "Offers opened", "Gate", "Heat 1", "Semifinal", "Final", "Winner"
  focus: ActorKey[]; // who the key light visits, in order
  advancing: string[]; // bid ids that move up a tier in this beat
  knocked: Knock[]; // bid ids that leave in this beat, with the referee's reason
  caption: string; // one plain sentence; no em or en dashes
  ms: number;
}

export interface ArenaScene {
  roundId: string | null;
  sample: boolean; // a labelled SIM fixture, never live data
  phase: Phase;
  requestLabel: string; // public product words only; "" when unknown
  sealedCount: number;
  deadline: Date | null;
  offers: SceneOffer[]; // [] unless phase is closed or inconsistent; referee order (ranked by rank, then knocked)
  beats: Beat[]; // [] unless phase is closed; the whole close sequence totals <= MAX_SEQUENCE_MS
  winnerBidId: string | null;
  problem: string | null; // set when inconsistent
}

export const MAX_SEQUENCE_MS = 12_000;

const cmp = <T extends string | bigint>(a: T, b: T) => (a < b ? -1 : a > b ? 1 : 0);
const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;
const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Product words for people: "gpu-rtx5070ti-retail" -> "GPU RTX 5070 Ti retail". Letter and digit runs split; words of 3 letters or fewer and numbers go upper case; the rest stay lower case. */
function humanize(spec: string): string {
  return spec
    .replace(/([a-z])(\d)/gi, "$1 $2")
    .replace(/(\d)([a-z])/gi, "$1 $2")
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((w) => (w.toLowerCase() === "ti" ? "Ti" : /^[a-z]{1,3}$/i.test(w) || /\d/.test(w) ? w.toUpperCase() : w.toLowerCase()))
    .join(" ");
}

/** The latest round by openedAt; the id breaks a tie so the pick never depends on row order. */
function latestRound(rounds: readonly RoundRow[]): RoundRow | undefined {
  let best: RoundRow | undefined;
  for (const r of rounds) {
    const a = r.openedAt.microsSinceUnixEpoch;
    const b = best?.openedAt.microsSinceUnixEpoch;
    if (!best || a > b! || (a === b && r.id > best.id)) best = r;
  }
  return best;
}

/** What was asked for, in public product words. The needs rows leave with the open window, so a closed round reads its result lines. */
function requestLabelOf(needs: readonly NeedRow[], results: readonly ResultRow[]): string {
  const specs = needs.length
    ? needs.map((n) => n.skuSpec)
    : [...results].sort((a, b) => cmp(a.id, b.id)).flatMap((r) => r.lines.map((l) => l.skuSpec));
  return [...new Set(specs.map(humanize).filter(Boolean))].join(" and ");
}

const dateOf = (t: Ts) => new Date(Number(t.microsSinceUnixEpoch / BigInt(1000)));

/** The referee's order: ranked by rank, then the Gate's refusals, then the advocate's vetoes, ties by bid id. */
function offersOf(results: readonly ResultRow[], bracket: Bracket | null, winner: string | null, events: readonly EventRow[]): SceneOffer[] {
  const knockOf = new Map<string, Knock>();
  const group = new Map<string, number>(); // 0 ranked, 1 Gate refusal, 2 advocate veto
  for (const stage of bracket?.stages ?? []) {
    for (const k of stage.heats.flatMap((h) => h.knocked)) {
      knockOf.set(k.id, k);
      if (stage.kind === "gate") group.set(k.id, 1);
      if (stage.kind === "advocate") group.set(k.id, 2);
    }
  }
  const linked = new Map<string, EventRow[]>();
  const wanted = new Set(results.map((r) => r.bidId));
  for (const e of events) {
    if (!wanted.has(e.refId)) continue;
    linked.set(e.refId, [...(linked.get(e.refId) ?? []), e]);
  }
  const tier = (r: ResultRow) => (r.rank > 0 ? 0 : group.get(r.bidId) ?? 1);
  return [...results]
    .sort((a, b) => tier(a) - tier(b) || (a.rank > 0 ? a.rank - b.rank : 0) || cmp(a.bidId, b.bidId))
    .map((r): SceneOffer => {
      const knock = knockOf.get(r.bidId);
      const source = knock?.sourceUrl ?? safeUrl(r.source) ?? undefined;
      const first = r.lines[0];
      return {
        key: offerKey(r.bidId),
        bidId: r.bidId,
        rowRef: `round_result/${r.id}`,
        sellerId: r.sellerId,
        name: r.persona || r.sellerId,
        origin: asOrigin(r.origin),
        landed: r.landed,
        product: humanize(first?.offeredSpec || first?.skuSpec || ""),
        rank: r.rank > 0 ? r.rank : null,
        outcome: r.bidId === winner ? "winner" : r.rank > 0 ? "ranked" : "knocked",
        ...(knock ? { knock } : {}),
        ...(source ? { sourceUrl: source } : {}),
        events: [...(linked.get(r.bidId) ?? [])]
          .sort((a, b) => cmp(a.id, b.id))
          .map((e) => ({ id: String(e.id), kind: e.kind, label: e.label, origin: asOrigin(e.origin) })),
      };
    });
}

const MS = { arrive: 1800, gate: 1400, advocate: 1400, knockout: 1200, crown: 2200 } as const;

/** The close as beats, straight from the bracket's stages: arrive, gate, advocate, one per knockout stage, crown. */
function beatsOf(bracket: Bracket, offers: readonly SceneOffer[], winner: string | null): Beat[] {
  const place = new Map(offers.map((o, i) => [o.bidId, i]));
  const byOffer = (ks: Knock[]) => [...ks].sort((a, b) => place.get(a.id)! - place.get(b.id)!);
  const nameOf = (bidId: string) => bracket.entrants[bidId]?.name ?? bidId;
  const knocksOf = (kind: "gate" | "advocate") => byOffer(bracket.stages.filter((s) => s.kind === kind).flatMap((s) => s.heats.flatMap((h) => h.knocked)));
  const stageName = (kind: "gate" | "advocate") => bracket.stages.find((s) => s.kind === kind)?.name ?? kind;
  const beats: Beat[] = [];

  const n = offers.length;
  beats.push({
    kind: "arrive", name: "Offers opened", focus: ["referee"], advancing: [], knocked: [],
    caption: `The round closed. ${n} sealed ${n === 1 ? "offer is" : "offers are"} opened.`, ms: MS.arrive,
  });

  const gate = knocksOf("gate");
  if (gate.length) {
    const shield = gate.filter((k) => k.reasonCode === "shield_block").length;
    beats.push({
      kind: "gate", name: stageName("gate"),
      focus: [...(shield ? (["shield"] as const) : []), ...(shield < gate.length ? (["referee"] as const) : []), ...gate.map((k) => offerKey(k.id))],
      advancing: [], knocked: gate,
      caption: shield === gate.length ? `Bazaar Shield blocked ${plural(gate.length, "offer")}.` : `The referee refused ${plural(gate.length, "offer")} before ranking.`,
      ms: MS.gate,
    });
  }

  const vetoed = knocksOf("advocate");
  if (vetoed.length) {
    const cited = vetoed.every((k) => k.sourceUrl);
    beats.push({
      kind: "advocate", name: stageName("advocate"), focus: ["advocate", ...vetoed.map((k) => offerKey(k.id))], advancing: [], knocked: vetoed,
      caption: !cited ? `The advocate vetoed ${plural(vetoed.length, "offer")}.`
        : vetoed.length === 1 ? "The advocate vetoed 1 offer, with a cited source." : `The advocate vetoed ${vetoed.length} offers, each with a cited source.`,
      ms: MS.advocate,
    });
  }

  for (const stage of bracket.stages.filter((s) => s.kind === "knockout")) {
    const advancing = stage.heats.flatMap((h) => (h.advances ? [h.advances] : []));
    const knocked = stage.heats.flatMap((h) => h.knocked);
    const real = stage.heats.filter((h) => !h.bye);
    const only = real.length === 1 ? real[0]! : null;
    beats.push({
      kind: "knockout", name: stage.name, focus: [...advancing, ...knocked.map((k) => k.id)].map(offerKey), advancing, knocked,
      caption: only ? `${stage.name}: the referee ranked ${nameOf(only.advances!)} ahead of ${nameOf(only.knocked[0]!.id)}.` : `${stage.name}: the referee's ranking moves ${advancing.length} offers up.`,
      ms: MS.knockout,
    });
  }

  const champion = offers.find((o) => o.bidId === winner);
  if (champion) {
    beats.push({
      kind: "crown", name: "Winner", focus: [champion.key, "buyer"], advancing: [champion.bidId], knocked: [],
      caption: `${champion.name} wins at ${formatMoney(champion.landed)} before sales tax.`, ms: MS.crown,
    });
  }

  const total = beats.reduce((sum, b) => sum + b.ms, 0);
  if (total > MAX_SEQUENCE_MS) for (const b of beats) b.ms = Math.floor((b.ms * MAX_SEQUENCE_MS) / total);
  return beats;
}

/** The scene for the latest round (by openedAt). Pure and deterministic. */
export function projectArenaScene(rows: ArenaRows, opts: { sample?: boolean } = {}): ArenaScene {
  const sample = opts.sample === true;
  const round = latestRound(rows.rounds);
  if (!round) return { roundId: null, sample, phase: "waiting", requestLabel: "", sealedCount: 0, deadline: null, offers: [], beats: [], winnerBidId: null, problem: null };

  // Everything below is scoped to this round by exact id: never by seller name or timing.
  const results = rows.results.filter((r) => r.roundId === round.id);
  const base = {
    roundId: round.id, sample, requestLabel: requestLabelOf(rows.needs.filter((n) => n.roundId === round.id), results),
    sealedCount: round.sealedCount, deadline: dateOf(round.deadline),
  };
  const none = { offers: [], beats: [], winnerBidId: null, problem: null };

  // While open (and in the gap before the result rows arrive) no offer is shown, even if stray result rows exist.
  if (round.state === "open") return { ...base, ...none, phase: "open" };
  const auctionClosed = rows.events.some((e) => e.kind === "auction_closed" && e.refId === round.id);
  if (round.state !== "closed" || (!results.length && !auctionClosed)) return { ...base, ...none, phase: "closing" };

  let winner: string | null = null;
  let bracket: Bracket | null = null;
  let problem: string | null = null;
  try { winner = roundWinner(results, round.id, rows.events); } catch (e) { problem = errorMessage(e); }
  try { bracket = buildBracket(results, round.id); } catch (e) { problem ??= errorMessage(e); }

  if (problem !== null) {
    return { ...base, phase: "inconsistent", offers: offersOf(results, bracket, null, rows.events), beats: [], winnerBidId: null, problem };
  }
  if (!results.length || !bracket) return { ...base, ...none, phase: "closed" }; // the no-eligible-bid close: nothing to open, nobody to crown
  const offers = offersOf(results, bracket, winner, rows.events);
  return { ...base, phase: "closed", offers, beats: beatsOf(bracket, offers, winner), winnerBidId: winner, problem: null };
}

/** Presentation state. beat = how many beats are applied: 0 is the sealed table, beats.length is the final frame. */
export interface Playback { roundId: string | null; beat: number; playing: boolean; sawOpen: boolean; replay: boolean }
export const IDLE: Playback = { roundId: null, beat: 0, playing: false, sawOpen: false, replay: false };
export type PlaybackAction =
  | { type: "scene" } // a new projection arrived (same or different round)
  | { type: "tick" } // the current beat's ms elapsed
  | { type: "pause" }
  | { type: "resume" }
  | { type: "replay" }
  | { type: "skip" };

/** Display only: never touches the market. A round already closed on first sight shows its final frame (history does not animate);
 * a round seen open and then closed plays its beats once; re-delivered rows for the same round change nothing. */
export function playback(s: Playback, a: PlaybackAction, scene: ArenaScene): Playback {
  const total = scene.beats.length;
  switch (a.type) {
    case "scene": {
      if (scene.roundId !== s.roundId) {
        // History never animates on first sight: a closed round lands on its final frame.
        return { roundId: scene.roundId, beat: scene.phase === "closed" ? total : 0, playing: false, sawOpen: scene.phase === "open" || scene.phase === "closing", replay: false };
      }
      if (scene.phase === "open" || scene.phase === "closing") return s.sawOpen ? s : { ...s, sawOpen: true };
      if (scene.phase === "closed" && s.sawOpen && total > 0 && s.beat === 0 && !s.playing) return { ...s, playing: true, sawOpen: false }; // a live close plays once
      if (scene.phase === "inconsistent" && (s.beat !== 0 || s.playing)) return { ...s, beat: 0, playing: false };
      return s;
    }
    case "tick": {
      if (!s.playing) return s;
      const beat = Math.min(s.beat + 1, total);
      return { ...s, beat, playing: beat < total };
    }
    case "pause": return s.playing ? { ...s, playing: false } : s;
    case "resume": return s.beat < total && !s.playing ? { ...s, playing: true } : s;
    case "replay": return total > 0 ? { ...s, beat: 0, playing: true, replay: true } : s;
    case "skip": return { ...s, beat: total, playing: false };
  }
}
