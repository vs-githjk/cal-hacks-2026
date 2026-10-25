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
  condition: string; // offeredCondition of the first line ("new", "open-box"); "" when the line names none
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

const ACRONYMS = new Map(Object.entries({ asus: "ASUS", msi: "MSI", evga: "EVGA", nvme: "NVMe", oc: "OC", ti: "Ti", ssd: "SSD", gpu: "GPU", psu: "PSU" }));

/** Product words for people: "gpu-rtx5070ti-retail" -> "GPU RTX 5070 Ti Retail". Letter and digit runs split; known acronyms get their usual spelling,
 * other words of 3 letters or fewer and anything with a digit go upper case, and the rest are title-cased. */
function humanize(spec: string): string {
  return spec
    .replace(/([a-z])(\d)/gi, "$1 $2")
    .replace(/(\d)([a-z])/gi, "$1 $2")
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((w) => {
      const lower = w.toLowerCase();
      const known = ACRONYMS.get(lower);
      if (known) return known;
      return /^[a-z]{1,3}$/i.test(w) || /\d/.test(w) ? w.toUpperCase() : lower.charAt(0).toUpperCase() + lower.slice(1);
    })
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
        condition: first?.offeredCondition ?? "",
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

const MS = { arrive: 1600, round: 1500, crown: 2200 } as const;

/** The close as elimination rounds, from the referee's sealed ranking: arrive, one round per eliminated offer (Gate refusals, then
 * advocate vetoes, then the ranked losers from the worst rank up to #2), then the crown. Presentation only: nobody bid live against anyone. */
function beatsOf(bracket: Bracket, offers: readonly SceneOffer[], winner: string | null): Beat[] {
  const beats: Beat[] = [];
  const n = offers.length;
  beats.push({
    kind: "arrive", name: "Offers opened", focus: ["referee"], advancing: [], knocked: [],
    caption: `The round closed. ${n} sealed ${n === 1 ? "offer is" : "offers are"} opened.`, ms: MS.arrive,
  });

  const stageIds = (kind: "gate" | "advocate") => new Set(bracket.stages.filter((s) => s.kind === kind).flatMap((s) => s.heats.flatMap((h) => h.knocked.map((k) => k.id))));
  const gateIds = stageIds("gate");
  const vetoIds = stageIds("advocate");
  const gate = offers.filter((o) => gateIds.has(o.bidId));
  // Shield blocks first, then the other refusals, each in offer order.
  const shielded = gate.filter((o) => o.knock?.reasonCode === "shield_block");
  const refused = gate.filter((o) => o.knock?.reasonCode !== "shield_block");
  const vetoed = offers.filter((o) => vetoIds.has(o.bidId));
  const losers = offers.filter((o) => o.rank !== null && o.bidId !== winner).sort((a, b) => b.rank! - a.rank!);
  const winnerCondition = offers.find((o) => o.bidId === winner)?.condition ?? "";

  const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);
  let i = 0;
  const round = (o: SceneOffer, kind: Beat["kind"], lead: ActorKey[], knock: Knock, caption: (r: number) => string) => {
    i += 1;
    beats.push({ kind, name: `Round ${i}`, focus: [...lead, o.key], advancing: [], knocked: [knock], caption: caption(i), ms: MS.round });
  };
  for (const o of shielded) round(o, "gate", ["shield"], o.knock!, (r) => `Round ${r}: Bazaar Shield blocks ${o.name}.`);
  for (const o of refused) round(o, "gate", ["referee"], o.knock!, (r) => `Round ${r}: ${o.name} is out, ${lower(o.knock!.reasonText)}.`);
  for (const o of vetoed) round(o, "advocate", ["advocate"], o.knock!, (r) => `Round ${r}: the advocate vetoes ${o.name}${o.knock!.sourceUrl ? ", with a cited source" : ""}.`);
  for (const o of losers) {
    const knock: Knock = o.knock ?? { id: o.bidId, reasonCode: "outranked", reasonText: `Ranked #${o.rank} by the referee`, label: "Outranked" };
    round(o, "knockout", [], knock, (r) => {
      const extra = o.condition && winnerCondition && o.condition !== winnerCondition ? ` Its ${o.condition} offer ranks below ${winnerCondition}.` : "";
      return `Round ${r}: ${o.name} is out at ${formatMoney(o.landed)}, ranked #${o.rank}.${extra}`;
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

/** True when the market has at most one row in total, so there is nothing worth watching yet. */
export function isEmptyMarket(rows: ArenaRows): boolean {
  return rows.rounds.length + rows.needs.length + rows.results.length + rows.events.length <= 1;
}

const warnedRounds = new Set<string>();

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
  problem ??= bracket?.problem ?? null;
  if (problem !== null && !warnedRounds.has(round.id)) {
    warnedRounds.add(round.id);
    console.warn("[arena] inconsistent round", round.id, problem);
  }

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
  | { type: "skip" }
  | { type: "seek"; beat: number }; // jump to a beat (clamped to 0..beats.length) and stop

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
    case "seek": {
      const beat = Number.isFinite(a.beat) ? Math.min(Math.max(Math.trunc(a.beat), 0), total) : 0;
      return beat === s.beat && !s.playing ? s : { ...s, beat, playing: false };
    }
  }
}

/** The words the page shows around the scene for one playback state. Pure: the page only places these strings. */
export interface Story {
  status: string; // "Live round", "Recorded round" or "Sample run"
  hero: string; // the request while the story runs, the winning price at the final frame of a won round
  caption: string; // one plain sentence for this state
  stage: string | null; // the current beat's name, null before the first beat
  step: string | null; // "2 of 5", null when the round has no beats
  note: string | null; // a plain-words caveat for knockout beats
}

const ROUND_NOTE = "Each round removes the weakest remaining offer by the referee's sealed ranking. Sellers did not bid against each other live.";

/** Copy for a scene at a playback position (see docs/3d-arena/DESIGN.md, Copy). Playback state that belongs to another round is read as a fresh arrival. */
export function storyFor(scene: ArenaScene, pb: Playback): Story {
  const p = pb.roundId === scene.roundId ? pb : playback(pb, { type: "scene" }, scene);
  const total = scene.beats.length;
  const beat = Math.min(Math.max(p.beat, 0), total);
  const current = beat > 0 ? scene.beats[beat - 1] : undefined;
  const closed = scene.phase === "closed";
  const finalFrame = closed && beat >= total;
  const winner = scene.offers.find((o) => o.bidId === scene.winnerBidId);

  const live = scene.phase === "open" || scene.phase === "closing" || scene.phase === "waiting" || (p.playing && !p.replay);
  const status = scene.sample ? "Sample run" : live ? "Live round" : "Recorded round";

  let caption: string;
  if (scene.phase === "waiting") caption = "No round yet. When a buyer posts a request, it appears here.";
  else if (scene.phase === "open") {
    caption = scene.sealedCount > 0
      ? `${plural(scene.sealedCount, "sealed offer")} ${scene.sealedCount === 1 ? "is" : "are"} in. Prices stay hidden until the round closes.`
      : `Sealed round open. Sellers can bid until ${scene.deadline ? scene.deadline.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" }) : "the deadline"}.`;
  } else if (scene.phase === "closing") caption = "Round closed. Waiting for the referee's result.";
  else if (scene.phase === "inconsistent") caption = "The result rows disagree, so no winner is shown.";
  else if (finalFrame && !winner) caption = "No offer passed the checks, so nobody won this round.";
  else caption = current ? current.caption : "The round closed. The referee is opening the sealed offers.";

  return {
    status,
    hero: finalFrame && winner && total > 0 ? formatMoney(winner.landed) : scene.requestLabel,
    caption,
    stage: current?.name ?? null,
    step: total > 0 ? `${beat} of ${total}` : null,
    note: current && current.kind !== "arrive" && current.kind !== "crown" ? ROUND_NOTE : null,
  };
}
