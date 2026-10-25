// web/src/components/floor/floorPhases.ts
// PURE: market rows in, an ordered list of phases out. No React, no DOM, no drawing, so a 3D renderer can reuse it as is.
// It follows docs/design-system/floor.md: sealed, reveal, referee call, (injection, Shield block | checker), dash, chomp per
// eliminated seller, then the winner check, the ring and the deal card. Positions are floor coordinates: u in [-1, 1] left to right,
// v in [0, 1] back to front. A price is null (shown SEALED) until the round has closed: while a round is open or closing the plan holds
// on sealed envelopes and carries no price at all.
import { formatMoney } from "../../lib/money.ts";
import { REFERENCE_RUN } from "./referenceRun.ts";
import { isEmptyMarket, projectArenaScene, type ArenaRows, type ArenaScene, type SceneOffer } from "../../lib/arenaScene.ts";
import type { ReasonCode } from "../../lib/bracket.ts";
import { T, type Tint } from "./floorTokens.ts";

export type PhaseKind =
  | "sealed" | "reveal" | "injection" | "shield" | "check" | "referee" | "dash" | "chomp"
  | "winner" | "end" | "hold";
export type Reason = "price" | "failed_fit" | "shield" | "refused";
export type SellerStatus = "sealed" | "revealed" | "blocked" | "eaten" | "checking" | "fit_ok" | "winner";
export type Tone = "neutral" | "bad" | "good" | "warn";
export interface Pt { u: number; v: number }
export type BuyerView = Pt & { face: 1 | -1; chomp: boolean };

export interface SellerView {
  key: string;
  name: string;
  slot: number;
  price: number | null; // null until the round has closed
  status: SellerStatus;
  reason: Reason | null;
  tag: string; // "SEALED", "$1,299.99", "EATEN · PRICE", "BLOCKED · SMELL TEST"
  statusLine: string | null; // "FIT OK", "WINNER", "SMELL TEST FAILED", "FIT FAILED"
  tone: Tone;
  pos: Pt;
  scale: number;
  tint: Tint; // by outcome: mint winner, coral Shield block, amber failed fit, slate otherwise
  ring: boolean; // the winner's mint ring
  injection: boolean; // the hidden-instruction bubble is up
  origin: string; // LIVE, MIRROR or SIM, per seller
}
export interface EndCard { title: "DEAL" | "NO DEAL"; part: string; price: string | null; line: string }
export interface Hud { round: number; rounds: number; part: string; sellers: number; state: "sealed" | "revealed" | "checking" | "deal"; price: string | null }
/** "Round 2 of 3 · GPU · 3 sellers · revealed", or "Deal · GPU · $1,299.99". */
export function hudText(h: Hud): string {
  if (h.state === "deal") return ["Deal", h.part, h.price].filter(Boolean).join(" · ");
  const tail = h.state === "checking" ? `${h.sellers === 1 ? "the checker verifies" : "the checker verifies"}` : h.state;
  return `Round ${h.round} of ${h.rounds} · ${h.part || "part"} · ${h.sellers} seller${h.sellers === 1 ? "" : "s"} · ${tail}`;
}
export interface FloorPhase {
  index: number;
  kind: PhaseKind;
  ms: number; // 0 with hold: the phase waits for more data
  hold: boolean;
  round: number; // 1-based
  rounds: number;
  hud: Hud;
  call: string | null; // the CRS referee's call, when the referee speaks
  pip: string | null; // a line for the ASI:One chat picture-in-picture
  refereeArms: boolean;
  buyer: BuyerView;
  sellers: SellerView[];
  shield: Pt | null;
  checker: Pt;
  wander: boolean;
  end: EndCard | null;
}
export interface FloorPlan {
  sample: boolean; // the built-in reference scenario, shown labelled SIM
  origin: string; // LIVE, MIRROR or SIM
  part: string;
  phases: FloorPhase[];
  sellerCount: number;
  winnerKey: string | null;
}

// Floor plane (docs/design-system/floor.md v2): the mat is the trapezoid (270,190) (690,190) (840,430) (120,430) in a 960 by 540 view.
export const BUYER_HOME: Pt = { u: 0, v: 0.86 };
export const CHECKER_HOME: Pt = { u: 1.26, v: 0.46 };
export const REFEREE_AT: Pt = { u: 0, v: 0.158 };

const REASON_WORD: Record<Reason, string> = { price: "PRICE", failed_fit: "FAILED FIT", shield: "SMELL TEST", refused: "NOT ORDERABLE" };
export function reasonKind(code: ReasonCode): Reason {
  if (code === "shield_block") return "shield";
  if (code === "advocate_veto" || code === "claim_false" || code === "off_need") return "failed_fit";
  if (code === "refused" || code === "sold_out") return "refused";
  return "price";
}
const PLAIN: Record<ReasonCode, string> = {
  shield_block: "The Smell Test caught an instruction hidden in the listing.",
  below_floor: "The bid sat below the seller's own floor, so it was refused.",
  over_cap: "The price was over the buyer's cap.",
  off_need: "The listing did not fit what the buyer asked for.",
  sold_out: "It sold out to an earlier round.",
  refused: "The referee refused the bid.",
  advocate_veto: "The listing failed the fit check against its source.",
  claim_false: "The listing's claim did not match its page.",
  outranked: "",
};

/** Home spot for slot i of n: spread across the mat; the outer seats stand nearer the front, as in the reference run. */
export function homeOf(i: number, n: number): Pt {
  const u = n === 1 ? 0 : -0.815 + (1.63 * i) / (n - 1);
  const v = u === 0 ? 0.66 : 0.3 + 0.24 * Math.min(1, Math.max(0, (Math.abs(u) - 0.375) / 0.44));
  return { u, v };
}

function sellerName(o: SceneOffer, i: number): string {
  return !o.name || o.name === o.sellerId ? `Seller ${i + 1}` : o.name;
}

function blank(i: number, n: number, name: string, origin: string): SellerView {
  return {
    key: `s${i}`, name, slot: i, price: null, status: "sealed", reason: null, tag: "SEALED", statusLine: null, tone: "neutral",
    pos: homeOf(i, n), scale: 1, tint: "slate", ring: false, injection: false, origin,
  };
}

/** A plan that holds on sealed envelopes: a round that is open, closing, waiting or inconsistent. It carries no price. */
function holdPlan(count: number, part: string, origin: string, sample: boolean, call: string | null): FloorPlan {
  const sellers = Array.from({ length: count }, (_, i) => blank(i, count, `Seller ${i + 1}`, origin));
  const phase: FloorPhase = {
    index: 0, kind: "hold", ms: 0, hold: true, round: 1, rounds: 1,
    hud: { round: 1, rounds: 1, part, sellers: count, state: "sealed", price: null }, call, pip: call ?? "Sealed round open. Prices stay hidden until it closes.",
    refereeArms: false, buyer: { ...BUYER_HOME, face: 1, chomp: false }, sellers, shield: null, checker: CHECKER_HOME, wander: true, end: null,
  };
  return { sample, origin, part, phases: [phase], sellerCount: count, winnerKey: null };
}

/** The phases for a scene. Pure and deterministic. */
export function planFromScene(scene: ArenaScene): FloorPlan {
  const part = scene.requestLabel || scene.offers.find((o) => o.product)?.product || "";
  const origin = scene.sample ? "SIM" : scene.offers[0]?.origin ?? "LIVE";
  if (scene.phase === "inconsistent") return holdPlan(Math.max(scene.sealedCount, 1), part, origin, scene.sample, "The result rows disagree, so no winner is shown.");
  if (scene.phase !== "closed") return holdPlan(Math.max(scene.sealedCount, scene.phase === "waiting" ? 0 : 1), part, origin, scene.sample, null);
  const offers = scene.offers;
  if (!offers.length) return holdPlan(Math.max(scene.sealedCount, 1), part, origin, scene.sample, "No offer passed the checks, so nobody won this round.");

  const n = offers.length;
  const names = offers.map((o, i) => sellerName(o, i));
  const idx = new Map(offers.map((o, i) => [o.bidId, i]));
  const sellers = offers.map((o, i) => blank(i, n, names[i]!, o.origin));
  // Tint by outcome, as the reference run does: mint the winner, coral the Shield block, amber a failed fit, slate the rest.
  offers.forEach((o, i) => {
    const code = o.knock?.reasonCode;
    sellers[i]!.tint = o.bidId === scene.winnerBidId ? "mint" : code && reasonKind(code) === "shield" ? "coral" : code && reasonKind(code) === "failed_fit" ? "amber" : o.rank === 2 ? "sky" : "slate";
  });
  const knocks = scene.beats.flatMap((b) => b.knocked);
  const rounds = Math.max(knocks.length, 1);
  const winnerIdx = scene.winnerBidId !== null ? idx.get(scene.winnerBidId) ?? null : null;

  const phases: FloorPhase[] = [];
  let buyer: BuyerView = { ...BUYER_HOME, face: 1, chomp: false };
  let shield: Pt | null = null;
  let checker: Pt = CHECKER_HOME;
  let round = 1;
  let revealed = false;
  let winPrice: string | null = null;
  const alive = () => sellers.filter((s) => s.status !== "eaten").length;

  const push = (kind: PhaseKind, ms: number, extra: { call?: string | null; pip?: string | null; arms?: boolean; wander?: boolean; end?: EndCard | null } = {}) => {
    phases.push({
      index: phases.length, kind, ms, hold: false, round, rounds,
      hud: {
        round, rounds, part, sellers: alive(), price: winPrice,
        state: kind === "end" || kind === "winner" ? "deal" : kind === "check" ? "checking" : revealed ? "revealed" : "sealed",
      },
      call: extra.call ?? null, pip: extra.pip ?? null, refereeArms: extra.arms ?? false,
      buyer: { ...buyer }, sellers: sellers.map((s) => ({ ...s, pos: { ...s.pos } })), shield: shield && { ...shield }, checker: { ...checker },
      wander: extra.wander ?? false, end: extra.end ?? null,
    });
  };

  push("sealed", 3600, { wander: true, pip: `${n} sealed offers are in. Prices stay hidden until the round closes.` });
  revealed = true;
  sellers.forEach((s, i) => { s.price = offers[i]!.landed; s.status = "revealed"; s.tag = formatMoney(offers[i]!.landed); });
  push("reveal", 1000 + 120 * n, { pip: "The round closed. The referee opens the sealed offers." });

  // one elimination per knock: the worst seller is eaten, with its reason
  knocks.forEach((k, r) => {
    round = r + 1;
    const i = idx.get(k.id);
    if (i === undefined) return;
    const s = sellers[i]!;
    const o = offers[i]!;
    const reason = reasonKind(k.reasonCode);
    const plain = k.reasonCode === "outranked" ? `Ranked #${o.rank ?? "?"} by the referee.` : k.reasonCode === "refused" ? `${k.reasonText.replace(/\.$/, "")}.` : PLAIN[k.reasonCode];
    const call = `${s.name} is out at ${formatMoney(o.landed)}. ${plain}`;
    buyer = { ...BUYER_HOME, face: 1, chomp: false };

    if (reason === "shield") {
      s.injection = true;
      push("injection", 1400, { pip: `${s.name}'s listing hides an instruction aimed at shopping agents.` });
      shield = { u: (BUYER_HOME.u + s.pos.u) / 2, v: (BUYER_HOME.v + s.pos.v) / 2 };
      s.status = "blocked"; s.statusLine = "SMELL TEST FAILED"; s.tag = "BLOCKED · SMELL TEST"; s.tone = "bad"; s.reason = "shield";
      push("shield", 1400, { pip: `The Smell Test caught ${s.name}: override attempt in the listing.` });
      s.injection = false;
    } else if (reason === "failed_fit") {
      checker = { u: s.pos.u + 0.14, v: s.pos.v + 0.08 };
      s.status = "checking"; s.statusLine = "FIT FAILED"; s.tone = "warn";
      push("check", 1100, { pip: `The checker compared ${s.name}'s listing with its source.` });
    }
    push("referee", 1300, { call, arms: true, pip: call });
    const side = s.pos.u >= 0 ? -1 : 1;
    buyer = { u: s.pos.u + side * 0.16, v: Math.min(s.pos.v + 0.08, 0.97), face: side === -1 ? 1 : -1, chomp: false };
    push("dash", T.dash);
    buyer = { ...buyer, chomp: true };
    s.status = "eaten"; s.reason = reason; s.tone = "bad"; s.tag = reason === "shield" ? "BLOCKED · SMELL TEST" : `EATEN · ${REASON_WORD[reason]}`;
    push("chomp", T.chomp);
    buyer = { ...buyer, chomp: false };
    shield = null;
    checker = CHECKER_HOME;
  });

  // the winner: the checker ticks it, it grows a little and takes a mint ring, the buyer steps up beside it, the deal card shows
  if (winnerIdx !== null) {
    const w = sellers[winnerIdx]!;
    const o = offers[winnerIdx]!;
    buyer = { ...BUYER_HOME, face: 1, chomp: false };
    checker = { u: w.pos.u + 0.14, v: w.pos.v + 0.08 };
    w.status = "fit_ok"; w.statusLine = "FIT OK"; w.tone = "good";
    push("check", 1100, { pip: `The checker confirmed ${w.name}.` });
    checker = CHECKER_HOME;
    winPrice = formatMoney(o.landed);
    w.status = "winner"; w.statusLine = "WINNER"; w.scale = 1.12; w.ring = true;
    const side = w.pos.u >= 0 ? -1 : 1;
    buyer = { u: w.pos.u + side * 0.2, v: Math.min(w.pos.v + 0.1, 0.97), face: side === -1 ? 1 : -1, chomp: false };
    const call = `Winner: ${w.name} at ${winPrice}, before sales tax.`;
    push("winner", 1500, { call, arms: true, pip: call });
    push("end", 4000, {
      end: { title: "DEAL", part: part || o.product, price: winPrice, line: `${w.name} · ranked 1 of ${n} by the referee · passed the Smell Test · fit checked` },
      pip: "Deal. The buyer has its part.",
    });
  } else {
    push("end", 4000, { end: { title: "NO DEAL", part, price: null, line: "No offer passed the checks, so nobody won this round." }, call: "No offer passed the checks.", pip: "No deal this round." });
  }

  return { sample: scene.sample, origin, part, phases, sellerCount: n, winnerKey: winnerIdx !== null ? sellers[winnerIdx]!.key : null };
}

/** Market rows in, phases out. An empty market plays the built-in reference scenario, labelled SIM. */
export function planFromRows(rows: ArenaRows, opts: { sample?: boolean } = {}): FloorPlan {
  const scene = projectArenaScene(rows, { sample: opts.sample });
  if (!opts.sample && (isEmptyMarket(rows) || scene.phase === "waiting")) return planFromScene(projectArenaScene(REFERENCE_RUN, { sample: true }));
  return planFromScene(scene);
}

/** Total ms of a plan's timed phases. */
export const planMs = (p: FloorPlan) => p.phases.reduce((a, ph) => a + ph.ms, 0);
