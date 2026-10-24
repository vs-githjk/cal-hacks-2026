// web/src/lib/arenaLayout.ts
// Where everyone stands, and what everyone holds, after N beats of a closed round. Pure and deterministic, with no three
// import, so node tests can run it. The renderer (Floor3D.tsx) tweens from the state it shows to stageAt(scene, beat).
// The numbers are web/docs/3d-arena/DESIGN.md: world units, y up, the camera on +z, angle 0 is +z.
import type { ActorKey, ArenaScene, Beat, SceneOffer } from "./arenaScene.ts";
import type { ReasonCode } from "./bracket.ts";

export interface Pose { x: number; y: number; z: number; yaw: number; pitch: number; dim: boolean; visible: boolean; tier: 0 | 1 | 2 }
/** hidden: not drawn. stack: still in the envelope pile on the table. held: standing at chest height in front of its seller.
 * dropped: flat on the floor. lifted: floating above the ledger table. */
export type CardState = "hidden" | "stack" | "held" | "dropped" | "lifted";
/** What a nameplate says about an offer: the word for a refusal, the winner badge, or nothing. */
export type Mark = "none" | "winner" | "blocked" | "vetoed" | "refused" | "outranked";

export interface StageState {
  actors: Record<string, Pose>; // by ActorKey: buyer, advocate, shield, referee, plus one per offer
  cards: Record<string, CardState>; // by bid id
  stackCount: number; // envelopes drawn on the ledger table, at most STACK_MAX
  focus: ActorKey[]; // who the key light visits, in order
  rest: ActorKey[]; // where the light settles when it is done: the centroid of these
  crown: boolean;
  lightOn: number; // key-light level, 0 to 1
  marks: Record<string, Mark>; // by bid id
  aim: { shield: ActorKey | null; advocate: ActorKey | null }; // who the Shield's plate and the advocate's tablet face
}

export const STACK_MAX = 12;
export const ANON_MAX = 8; // anonymous sealed bidders drawn at most; the caption states the real count
export const TIER_Y = [0, 0.22, 0.44] as const;
export const TABLE = { x: 0, y: 0.5, z: 0.35 } as const; // the ledger table's center; its top is at y 0.56
export const WINNER_SEAT = { x: 0.8, y: 0.44, z: -0.2 } as const;
export const KNOCKED_RADIUS = 5.8;
export const ADVANCED_RADIUS = 2.6;
export const ENTRY_RADIUS = 6.4; // where a figure starts its walk in
export const FIXED_KEYS = ["buyer", "advocate", "shield", "referee"] as const;

const rad = (deg: number) => (deg * Math.PI) / 180;
const HEAD_DOWN = rad(12);
const LEAN = rad(8);
const FRONT_ROW = 4.6;
const BACK_ROW = 5.2;

export interface Seat { x: number; z: number; yaw: number; radius: number }
const faceCenter = (x: number, z: number) => Math.atan2(-x, -z);
const polar = (radius: number, angle: number): Seat => {
  const x = radius * Math.sin(angle);
  const z = radius * Math.cos(angle);
  return { x, z, yaw: faceCenter(x, z), radius };
};

/** Seat `index` of `count` offers: a horseshoe behind the buyer from 235 degrees (screen left) to 125 (screen right).
 * Above 7 offers every other seat moves to a second row. Order is the scene's offer order. */
export function seatOf(count: number, index: number): Seat {
  const t = count > 1 ? index / (count - 1) : 0.5;
  const radius = count > 7 && index % 2 === 1 ? BACK_ROW : FRONT_ROW;
  return polar(radius, rad(235 - 110 * t));
}
/** Slot `index` of `count` on the advanced ring (tier 1, back half, 220 to 140 degrees). */
function advancedSeat(count: number, index: number): Seat {
  const t = count > 1 ? index / (count - 1) : 0.5;
  return polar(ADVANCED_RADIUS, rad(220 - 80 * t));
}
/** The same bearing, pulled in or out to `radius`. */
function atRadius(seat: Seat, radius: number): Seat {
  const k = seat.radius > 0 ? radius / seat.radius : 1;
  return { x: seat.x * k, z: seat.z * k, yaw: seat.yaw, radius };
}

const pose = (x: number, y: number, z: number, yaw: number, tier: 0 | 1 | 2, o: Partial<Pose> = {}): Pose =>
  ({ x, y, z, yaw, pitch: 0, dim: false, visible: true, tier, ...o });

const markFor = (code: ReasonCode): Mark => (code === "shield_block" ? "blocked" : code === "advocate_veto" || code === "claim_false" ? "vetoed" : code === "outranked" ? "outranked" : "refused");

export function stageAt(scene: ArenaScene, beat: number): StageState {
  const n = scene.offers.length;
  const b = Math.min(Math.max(0, Number.isFinite(beat) ? Math.trunc(beat) : 0), scene.beats.length);
  const closed = scene.phase === "closed";
  const applied: Beat[] = closed ? scene.beats.slice(0, b) : [];
  const last = applied.at(-1);
  // Offers show once the arrive beat has played. A closed round with no beats at all has nothing to wait for.
  const arrived = closed && (applied.some((x) => x.kind === "arrive") || scene.beats.length === 0);
  const sealed = Math.min(Math.max(0, scene.phase === "waiting" ? 0 : scene.sealedCount), STACK_MAX);

  // What each bid has been through so far. The first knock wins; "outranked" is a valid offer ranking lower, not a refusal.
  const knocks = new Map<string, ReasonCode>();
  for (const x of applied) for (const k of x.knocked) if (!knocks.has(k.id)) knocks.set(k.id, k.reasonCode);
  const hard = (id: string) => { const c = knocks.get(id); return c !== undefined && c !== "outranked"; };
  const advancedNow = new Set<string>();
  for (const x of applied) if (x.kind === "knockout") for (const id of x.advancing) advancedNow.add(id);
  // Seats on the advanced ring come from every knockout beat in the scene, so survivors never reshuffle between beats.
  const ring = new Set<string>();
  for (const x of scene.beats) if (x.kind === "knockout") for (const id of x.advancing) ring.add(id);
  const ringOrder = scene.offers.filter((o) => ring.has(o.bidId)).map((o) => o.bidId);

  const winner = closed && scene.winnerBidId ? scene.offers.find((o) => o.bidId === scene.winnerBidId) : undefined;
  const crown = !!winner && applied.some((x) => x.kind === "crown");
  const acting = new Set<string>(last && last.kind !== "arrive" ? last.focus : []);

  const actors: Record<string, Pose> = {};
  const cards: Record<string, CardState> = {};
  const marks: Record<string, Mark> = {};

  const dimFixed = crown;
  actors.buyer = pose(0, TIER_Y[2], -0.35, 0, 2);
  // The advocate and the Shield stand at the sides of the stage, on the floor, like officials at a ring.
  actors.advocate = pose(-4.1, TIER_Y[0], 0.4, faceCenter(-4.1, 0.4), 0, { dim: dimFixed, pitch: acting.has("advocate") ? LEAN : 0 });
  actors.shield = pose(4.1, TIER_Y[0], 0.4, faceCenter(4.1, 0.4), 0, { dim: dimFixed, pitch: acting.has("shield") ? LEAN : 0 });
  actors.referee = pose(TABLE.x, TABLE.y, TABLE.z, 0, 2);

  scene.offers.forEach((o: SceneOffer, i) => {
    const seat = seatOf(n, i);
    let p: Pose = pose(seat.x, 0, seat.z, seat.yaw, 0, { visible: arrived });
    let card: CardState = closed ? (arrived ? "held" : "stack") : "hidden";
    let mark: Mark = "none";
    if (arrived) {
      const isWinner = crown && o.bidId === winner?.bidId;
      if (isWinner) {
        p = pose(WINNER_SEAT.x, WINNER_SEAT.y, WINNER_SEAT.z, -0.3, 2, { pitch: LEAN });
        card = "lifted";
        mark = "winner";
      } else if (hard(o.bidId)) {
        const back = atRadius(seat, KNOCKED_RADIUS);
        p = pose(back.x, 0, back.z, back.yaw, 0, { dim: true, pitch: HEAD_DOWN });
        card = "dropped";
        mark = markFor(knocks.get(o.bidId)!);
      } else {
        let q = seat;
        let tier: 0 | 1 = 0;
        if (advancedNow.has(o.bidId)) {
          q = advancedSeat(ringOrder.length, ringOrder.indexOf(o.bidId));
          tier = 1;
        }
        const outranked = knocks.get(o.bidId) === "outranked";
        p = pose(q.x, TIER_Y[tier], q.z, q.yaw, tier, { dim: outranked || crown, pitch: !outranked && !crown && acting.has(o.key) ? LEAN : 0 });
        if (outranked) mark = "outranked";
      }
    }
    actors[o.key] = p;
    cards[o.bidId] = card;
    marks[o.bidId] = mark;
  });

  // Anonymous sealed bidders: one grey figure per sealed envelope until the close names them. Nobody's identity is public before
  // close, so these carry no name; at arrive the named sellers take the same seats. Keys anon:0 to anon:ANON_MAX-1, always present.
  const anonCount = arrived ? 0 : closed ? Math.min(n, ANON_MAX) : Math.min(sealed, ANON_MAX);
  for (let i = 0; i < ANON_MAX; i++) {
    const seat = seatOf(Math.max(anonCount, 1), Math.min(i, Math.max(anonCount - 1, 0)));
    actors[`anon:${i}`] = pose(seat.x, 0, seat.z, seat.yaw, 0, { visible: i < anonCount });
  }

  const taken = arrived ? Math.min(n, sealed) : 0;
  const stackCount = scene.phase === "waiting" ? 0 : sealed - taken;

  // Who the light is on.
  const offerKeys = scene.offers.map((o) => o.key);
  let focus: ActorKey[];
  let rest: ActorKey[];
  if (last) {
    focus = [...last.focus];
    if (crown && winner) rest = [winner.key, "buyer"];
    else if (last.kind === "arrive") rest = offerKeys;
    else rest = last.focus.length ? [last.focus[last.focus.length - 1]!] : ["referee"];
  } else if (scene.phase === "waiting") focus = rest = ["buyer"];
  else if (scene.phase === "inconsistent") focus = rest = ["referee"];
  else focus = rest = ["buyer", "referee"];

  // Props. The Shield turns toward the seller it just blocked; the advocate lifts its tablet toward a vetoed one.
  const aim: StageState["aim"] = { shield: null, advocate: null };
  const blocked = last?.kind === "gate" ? last.knocked.find((k) => k.reasonCode === "shield_block") : undefined;
  if (blocked) aim.shield = offerKeyOf(scene, blocked.id);
  const vetoed = last?.kind === "advocate" ? last.knocked[0] : undefined;
  if (vetoed) aim.advocate = offerKeyOf(scene, vetoed.id);

  return { actors, cards, stackCount, focus, rest, crown, lightOn: scene.phase === "closing" ? 0.7 : 1, marks, aim };
}

function offerKeyOf(scene: ArenaScene, bidId: string): ActorKey | null {
  return scene.offers.find((o) => o.bidId === bidId)?.key ?? null;
}

export const SELLER_COLORS = [0xf28482, 0xf6bd60, 0x7fb7be, 0xb79ced, 0x90be6d, 0xf7a072, 0x6d9dc5] as const;
export type HatKind = "party" | "cap" | "top" | "beanie";
const HATS: HatKind[] = ["party", "cap", "top", "beanie"];
export interface Look { color: number; hat: HatKind; hatColor: number }
const hash = (s: string) => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; return h; };

/** A color and hat per seller, from a hash of the seller id. Two offers on stage never share a color (up to 7). */
export function looksFor(offers: readonly { key: string; sellerId: string }[]): Record<string, Look> {
  const used = new Set<number>();
  const out: Record<string, Look> = {};
  for (const o of offers) {
    let i = hash(o.sellerId) % SELLER_COLORS.length;
    for (let n = 0; n < SELLER_COLORS.length && used.has(i); n++) i = (i + 1) % SELLER_COLORS.length;
    used.add(i);
    out[o.key] = { color: SELLER_COLORS[i]!, hat: HATS[hash(`${o.sellerId}:hat`) % HATS.length]!, hatColor: SELLER_COLORS[(i + 3) % SELLER_COLORS.length]! };
  }
  return out;
}
