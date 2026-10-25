// web/src/components/floor/floorPhases.ts
// The /floor ring's script: pure data, no React. REFERENCE is the docs/design-system/floor.md run (31 s loop, 4 sellers).
// floorScript turns the latest closed round's public rows into the same shape via projectArenaScene, so no outcome is re-derived here.
// A seller's price is null in every phase before its reveal: a sealed price never leaves this file.
import { projectArenaScene, type ArenaRows, type SceneOffer } from "../../lib/arenaScene.ts";

export type Theme = "ghosts" | "fish";
export type Slot = 1 | 2 | 3 | 4; // colour slot: ghost-1..4
export type SellerState = "sealed" | "open" | "eaten" | "winner";
export type OutReason = "highest_price" | "outranked" | "failed_fit" | "shield_block" | "advocate_veto" | "refused";
export interface FloorSeller { id: string; name: string; origin: "LIVE" | "MIRROR" | "SIM"; slot: Slot }
export interface SellerView { state: SellerState; price: number | null; ledger: string; reason: OutReason | null; checkedAgo: number | null } // ledger: "Sealed" | "$1,329.00" | "Eaten · highest price" | "Blocked · Shield" | "Out · fit uncertain" | "Fit OK · 304 mm · no recall" | "Winner"; checkedAgo: Bright Data re-check age in seconds, null if unknown
export type PhaseKind = "sealed" | "reveal" | "call" | "inject" | "shield" | "check" | "eat" | "crown" | "deal" | "paid" | "think";
export interface FloorPhase {
  at: number;            // seconds from the start of the loop
  kind: PhaseKind;
  round: number; rounds: number; part: string; // HUD "Round 2 of 3 · GPU"
  sellers: Record<string, SellerView>;         // every seller, every phase
  buyerAt: string | null;   // seller id Pac-Man stands next to, null = centre
  callText: string | null;  // referee banner
  injection: string | null; // seller id showing the injected bubble
  shieldAt: string | null;  // seller id the Shield stands in front of
  checkerAt: string | null; // seller id the checker is at
  pip: string[];            // the ASI:One PiP messages visible now, oldest first
  think?: { who: string; name: string; text: string } | null; // a hold beat: this agent is shown thinking, then says `text` (the chat lines come from here)
  deal: { price: number; part: string; lines: string[]; approvedByPhone: boolean; stripeTest: boolean } | null;
}
/** Hold ceilings in seconds for the thinking beats. */
export const THINK_CEIL = { buyer: 2.5, shield: 1.2, advocate: 2.5, summary: 5 } as const;
const BUYER = { who: "buyer", name: "Fish Market Buyer" };
const SHIELD = { who: "shield", name: "Shield" };
const ADVOCATE = { who: "advocate", name: "Advocate" };
const SUMMARY = "Bought the ASUS Prime RTX 5070 Ti OC from Best Buy for $1,299.99 before tax. Two offers were out on price, one was blocked by the Shield, and one failed the fit check. Approved by your phone code.";

export interface FloorScript { sim: boolean; part: string; sellers: FloorSeller[]; phases: FloorPhase[]; duration: number }

const money = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const LEDGER: Record<OutReason, string> = {
  highest_price: "Eaten · highest price",
  outranked: "Outranked",
  failed_fit: "Out · fit uncertain",
  shield_block: "Blocked · Shield",
  advocate_veto: "Out · advocate veto",
  refused: "Out · refused",
};

type Extras = Partial<Pick<FloorPhase, "buyerAt" | "callText" | "injection" | "shieldAt" | "checkerAt" | "deal" | "think">>;

/** Accumulates seller state and snapshots it into phases, so each phase carries every seller. */
class Builder {
  views: Record<string, SellerView> = {};
  phases: FloorPhase[] = [];
  pip: string[] = [];
  round = 1;
  ids: string[]; prices: Record<string, number>; rounds: number; part: string;
  constructor(ids: string[], prices: Record<string, number>, rounds: number, part: string, checked: Record<string, number | null> = {}) {
    this.ids = ids; this.prices = prices; this.rounds = rounds; this.part = part;
    for (const id of ids) this.views[id] = { state: "sealed", price: null, ledger: "Sealed", reason: null, checkedAgo: checked[id] ?? null };
  }
  seal(ids: string[]) { for (const id of ids) this.views[id] = { ...this.views[id]!, state: "sealed", price: null, ledger: "Sealed" }; }
  reveal(ids: string[]) { for (const id of ids) this.views[id] = { ...this.views[id]!, state: "open", price: this.prices[id] ?? null, ledger: money(this.prices[id] ?? 0) }; }
  eat(id: string, reason: OutReason, ledger = LEDGER[reason]) { this.views[id] = { ...this.views[id]!, state: "eaten", price: this.prices[id] ?? null, ledger, reason }; }
  mark(id: string, ledger: string) { this.views[id] = { ...this.views[id]!, ledger }; }
  win(id: string) { this.views[id] = { ...this.views[id]!, state: "winner", price: this.prices[id] ?? null, ledger: "Winner", reason: null }; }
  push(at: number, kind: PhaseKind, x: Extras = {}) {
    const sellers: Record<string, SellerView> = {};
    for (const id of this.ids) sellers[id] = { ...this.views[id]! };
    this.phases.push({
      at, kind, round: this.round, rounds: this.rounds, part: this.part, sellers,
      buyerAt: x.buyerAt ?? null, callText: x.callText ?? null, injection: x.injection ?? null, shieldAt: x.shieldAt ?? null, checkerAt: x.checkerAt ?? null,
      pip: [...this.pip], think: x.think ?? null, deal: x.deal ?? null,
    });
  }
}

function buildReference(): FloorScript {
  const sellers: FloorSeller[] = [
    { id: "s1", name: "Seller 1", origin: "SIM", slot: 1 },
    { id: "s2", name: "Seller 2 (injected)", origin: "SIM", slot: 2 },
    { id: "s3", name: "eBay listing", origin: "MIRROR", slot: 3 },
    { id: "s4", name: "Best Buy listing", origin: "MIRROR", slot: 4 },
  ];
  const prices = { s1: 1329, s2: 1189, s3: 1222.23, s4: 1299.99 };
  const ids = sellers.map((s) => s.id);
  const b = new Builder(ids, prices, 3, "GPU", { s1: null, s2: null, s3: 42, s4: 18 });
  const dealPart = "ASUS Prime RTX 5070 Ti OC · Best Buy";
  const dealLines = ["Fit confirmed 304 mm", "No recall", "CRS verified_stable", "Above the allowance: approved by phone code"];

  b.pip = ["RTX 5070 Ti under $1,400 by Friday"];
  b.push(0, "sealed");
  b.push(1.1, "think", { think: { ...BUYER, text: "Reading your goal: one RTX 5070 Ti under $1,400 by Friday." } }); // 2.5 s hold, ends at the reveal
  b.pip.push("4 sealed bids in. No seller sees the buyer's budget. Round 1 now.");
  b.reveal(ids); b.push(3.6, "reveal", { buyerAt: "s1" });
  b.push(4.6, "call", { buyerAt: "s1", callText: "Highest price is out: $1,329.00, Seller 1" });
  b.eat("s1", "highest_price"); b.push(5.3, "eat", { buyerAt: "s1", callText: "Highest price is out: $1,329.00, Seller 1" });

  b.round = 2; b.seal(["s2", "s3", "s4"]); b.push(7.2, "sealed");
  b.push(8.2, "inject", { injection: "s2" });
  b.reveal(["s2", "s3", "s4"]); b.push(8.9, "reveal", { injection: "s2" });
  b.push(9.1, "shield", { injection: "s2", shieldAt: "s2" });
  b.push(9.5, "think", { injection: "s2", shieldAt: "s2", think: { ...SHIELD, text: "Blocked Seller 2: hidden instructions aimed at the buying agent." } }); // 1.2 s hold
  b.eat("s2", "shield_block"); b.push(10.7, "eat", { injection: "s2", shieldAt: "s2", callText: "Injected listing quarantined: Seller 2 is out" });

  b.round = 3; b.push(12.6, "check", { checkerAt: "s3" });
  b.push(13, "think", { checkerAt: "s3", think: { ...ADVOCATE, text: "Is it new, open-box, refurbished or used?" } }); // 2 s, under the 2.5 s ceiling
  b.push(15, "think", { checkerAt: "s3", think: { who: "seller_3", name: "eBay listing", text: "Open-box." } }); // 2 s
  b.eat("s3", "failed_fit"); b.push(17, "eat", { checkerAt: "s3", callText: "eBay listing is out: fit uncertain" });
  b.mark("s4", "Fit OK · 304 mm · no recall"); b.push(18.7, "check", { checkerAt: "s4" });
  b.win("s4"); b.pip.push("Winner $1,299.99. Above the allowance, so the buyer gets a call with the code.");
  b.push(21.4, "crown", { buyerAt: "s4", callText: "Winner: Best Buy listing at $1,299.99 · CRS verified_stable" });
  b.push(22.8, "deal", { buyerAt: "s4", deal: { price: 1299.99, part: dealPart, lines: dealLines, approvedByPhone: true, stripeTest: false } });
  b.push(24, "think", { buyerAt: "s4", think: { ...BUYER, text: SUMMARY }, deal: { price: 1299.99, part: dealPart, lines: dealLines, approvedByPhone: true, stripeTest: false } }); // 5 s hold
  b.push(29, "paid", { buyerAt: "s4", deal: { price: 1299.99, part: dealPart, lines: [...dealLines, "Stripe test mode"], approvedByPhone: true, stripeTest: true } });
  return { sim: true, part: "GPU", sellers, phases: b.phases, duration: 31 };
}

/** The floor.md reference scenario: 4 sellers, 3 rounds, 31 s loop. Also the fallback when there is nothing real to show. */
export const REFERENCE: FloorScript = buildReference();

const STEP = 3;
/** `strictTop`: this offer's landed price is strictly the highest among the offers still in. Only then is an outranking "highest_price". */
const reasonOf = (o: SceneOffer, fallback: OutReason, strictTop = false, knocked?: string): OutReason => {
  const code = String(knocked ?? o.knock?.reasonCode ?? "");
  if (code === "shield_block") return "shield_block";
  if (code === "advocate_veto") return "advocate_veto";
  if (code === "outranked") return strictTop ? "highest_price" : "outranked";
  return fallback;
};

/** The script for the latest round in `rows`, or REFERENCE when there is nothing usable. */
export function floorScript(rows: ArenaRows | null | undefined): FloorScript {
  if (!rows || !rows.rounds || rows.rounds.length === 0) return REFERENCE;
  const scene = projectArenaScene(rows);
  const part = scene.requestLabel || "Part";

  const sealed = (callText: string | null, pip: string[]): FloorScript => {
    const round = rows.rounds.find((r) => r.id === scene.roundId);
    const origin = round?.origin === "LIVE" || round?.origin === "MIRROR" ? round.origin : "SIM";
    const n = Math.max(scene.sealedCount, 0);
    const sellers: FloorSeller[] = Array.from({ length: n }, (_, i) => ({ id: `sealed-${i + 1}`, name: `Seller ${i + 1}`, origin, slot: ((i % 4) + 1) as Slot }));
    const b = new Builder(sellers.map((s) => s.id), {}, 1, part);
    b.pip = pip;
    b.push(0, "sealed", { callText });
    return { sim: origin === "SIM", part, sellers, phases: b.phases, duration: 24 };
  };
  const bids = `${Math.max(scene.sealedCount, 0)} sealed ${scene.sealedCount === 1 ? "bid is" : "bids are"} in.`;
  if (scene.phase === "open") return sealed(null, [`${bids} Prices stay hidden until the round closes.`]);
  if (scene.phase === "closing") return sealed("Round closed. Waiting for the referee's result.", [`${bids} Prices stay hidden until the referee's result.`]);
  if (scene.phase === "closed" && scene.offers.length === 0) return sealed("Round closed. No offer passed the checks.", []);

  if ((scene.phase !== "closed" && scene.phase !== "inconsistent") || scene.offers.length === 0) return REFERENCE;

  const offers = scene.offers;
  const sellers: FloorSeller[] = offers.map((o, i) => ({ id: o.bidId, name: o.name, origin: o.origin, slot: ((i % 4) + 1) as Slot }));
  const prices: Record<string, number> = {};
  for (const o of offers) prices[o.bidId] = o.landed;
  const byKey = new Map(offers.map((o) => [o.key, o]));
  const b = new Builder(sellers.map((s) => s.id), prices, 1, part);
  const n = offers.length;
  const bidsLine = `${n} sealed ${n === 1 ? "bid is" : "bids are"} in. No seller sees the buyer's budget.`;
  let at = 0;
  const hold = (d: number) => { const t = at; at += d; return t; };
  const next = () => hold(STEP);

  b.push(next(), "sealed");
  b.push(hold(THINK_CEIL.buyer), "think", { think: { ...BUYER, text: `Reading your goal: one ${part}.` } });
  b.pip.push(bidsLine);
  b.reveal(sellers.map((s) => s.id)); b.push(next(), "reveal", { callText: "Offers opened" });

  if (scene.phase === "inconsistent") {
    b.push(next(), "call", { callText: "Winner under review" });
  } else {
    for (const beat of scene.beats) {
      if (beat.kind === "arrive") continue;
      if (beat.kind === "crown") {
        const w = offers.find((o) => o.bidId === scene.winnerBidId);
        if (!w) continue;
        b.win(w.bidId);
        b.pip.push(`Winner ${money(w.landed)}. The deal goes to the buyer for approval.`);
        const outs = offers.filter((x) => b.views[x.bidId]!.state === "eaten");
        const blocked = outs.filter((x) => b.views[x.bidId]!.reason === "shield_block").length;
        const summary = `Bought ${w.product || part} from ${w.name} for ${money(w.landed)} before tax. ${outs.length} other ${outs.length === 1 ? "offer was" : "offers were"} out${blocked > 0 ? `, ${blocked} blocked by the Shield` : ""}. The deal goes to you for approval.`;
        b.push(next(), "crown", { buyerAt: w.bidId, callText: `Winner: ${w.name} at ${money(w.landed)}` });
        b.push(next(), "deal", { buyerAt: w.bidId, deal: { price: w.landed, part: w.product || part, lines: [w.condition ? `Condition: ${w.condition}` : "Checked by the referee", "Price before sales tax"], approvedByPhone: false, stripeTest: false } });
        b.push(hold(THINK_CEIL.summary), "think", { buyerAt: w.bidId, think: { ...BUYER, text: summary }, deal: b.phases[b.phases.length - 1]!.deal });
        continue;
      }
      const knocked = beat.knocked[0];
      const o = knocked ? offers.find((x) => x.bidId === knocked.id) : byKey.get(beat.focus[beat.focus.length - 1]!);
      if (!o) continue;
      const id = o.bidId;
      if (beat.kind === "gate") {
        if (reasonOf(o, "refused") === "shield_block") {
          b.push(next(), "inject", { buyerAt: id, injection: id });
          b.push(next(), "shield", { buyerAt: id, injection: id, shieldAt: id });
          b.push(hold(THINK_CEIL.shield), "think", { buyerAt: id, injection: id, shieldAt: id, think: { ...SHIELD, text: `Blocked ${o.name}: hidden instructions aimed at the buying agent.` } });
          b.eat(id, "shield_block");
          b.push(next(), "eat", { buyerAt: id, injection: id, shieldAt: id, callText: `Injected listing quarantined: ${o.name} is out` });
        } else {
          b.push(next(), "call", { buyerAt: id, callText: `${o.name} is out: refused at the gate` });
          b.eat(id, "refused");
          b.push(next(), "eat", { buyerAt: id, callText: `${o.name} is out: refused at the gate` });
        }
      } else if (beat.kind === "advocate") {
        const reason = reasonOf(o, "failed_fit");
        b.push(next(), "check", { buyerAt: id, checkerAt: id, callText: `Checking ${o.name}` });
        if (reason === "advocate_veto") {
          const cond = (o.condition || "as listed").replace(/^./, (c) => c.toUpperCase());
          b.push(hold(THINK_CEIL.advocate), "think", { buyerAt: id, checkerAt: id, think: { ...ADVOCATE, text: "Is it new, open-box, refurbished or used?" } });
          b.push(hold(THINK_CEIL.advocate), "think", { buyerAt: id, checkerAt: id, think: { who: id, name: o.name, text: `${cond}.` } });
        }
        b.eat(id, reason);
        b.push(next(), "eat", { buyerAt: id, checkerAt: id, callText: `${o.name} is out: advocate veto` });
      } else {
        const stillIn = offers.filter((x) => b.views[x.bidId]!.state !== "eaten");
        const strictTop = stillIn.every((x) => x.bidId === id || x.landed < o.landed);
        const reason = reasonOf(o, "refused", strictTop, knocked?.reasonCode);
        const text = reason === "highest_price" ? `Highest price is out: ${money(o.landed)}, ${o.name}` : reason === "outranked" ? (knocked?.reasonText ?? o.knock?.reasonText ?? `${o.name} is out`) : `${o.name} is out`;
        b.push(next(), "call", { buyerAt: id, callText: text });
        b.eat(id, reason, reason === "outranked" ? (o.condition ? `Outranked · ${o.condition}` : `Outranked · ranked #${o.rank ?? "?"}`) : undefined);
        b.push(next(), "eat", { buyerAt: id, callText: text });
      }
    }
    if (!offers.some((o) => o.bidId === scene.winnerBidId)) b.push(next(), "call", { callText: "No offer passed the checks" });
  }

  const last = b.phases[b.phases.length - 1]!.at;
  return { sim: offers.every((o) => o.origin === "SIM"), part, sellers, phases: b.phases, duration: last + 6 };
}

/** The phase showing `seconds` into the loop: the last with at <= seconds % duration. Negative or NaN input gives the first phase. */
export function phaseAt(script: FloorScript, seconds: number): FloorPhase {
  const first = script.phases[0]!;
  if (!Number.isFinite(seconds) || seconds < 0 || script.duration <= 0) return first;
  const t = ((seconds % script.duration) + script.duration) % script.duration;
  let hit = first;
  for (const p of script.phases) if (p.at <= t) hit = p;
  return hit;
}
