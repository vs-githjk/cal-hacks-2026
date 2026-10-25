// web/src/lib/bracket.ts
// The Bidding Royale bracket, drawn only from the referee's own decisions in round_result rows: refusals at the
// Gate (Shield, below floor, over_cap, off need, sold out), advocate vetoes in Heat 1, then the ranked bids
// played 1v1 by the close_round rank (landed prices shown, the referee's tiebreak already inside the rank).
// No matchup is invented: the champion is always the rank 1 row, and roundWinner cross-checks auction_closed.
import { formatMoney } from "./money.ts";
import { safeUrl } from "./url.ts";
import { asOrigin, type Origin } from "./screens.ts";

interface ResultRow {
  id: bigint; roundId: string; bidId: string; sellerId: string; persona: string; rank: number; landed: number;
  reasons: string[]; origin: string; source: string;
}
interface EventRow { kind: string; refId: string; sellerId: string }

export type ReasonCode =
  | "shield_block" | "below_floor" | "over_cap" | "off_need" | "sold_out" | "refused" // Gate
  | "advocate_veto" | "claim_false" // Heat 1
  | "outranked"; // knockout heats

export interface Entrant {
  id: string; // bid id
  rowRef: string; // round_result/<id>
  sellerId: string;
  name: string;
  origin: Origin;
  rank: number | null; // null when the referee did not rank it
  landed: number;
  sourceUrl?: string;
}
export interface Knock { id: string; reasonCode: ReasonCode; reasonText: string; label: string; ruleId?: string; sourceUrl?: string }
export interface Heat { entrants: string[]; advances: string | null; knocked: Knock[]; bye: boolean }
export interface Stage { name: string; kind: "gate" | "advocate" | "knockout" | "champion"; heats: Heat[] }
export interface Bracket { roundId: string; entrants: Record<string, Entrant>; stages: Stage[]; champion: string | null; problem?: string }

const GATE: ReasonCode[] = ["shield_block", "below_floor", "over_cap", "off_need", "sold_out", "refused"];
// Reasons that mean the listing was caught. Only these decide it; origin alone never does, and unknown text maps to "refused".
const CAUGHT: ReasonCode[] = ["shield_block", "advocate_veto", "claim_false"];
const VETO = /^Advocate veto \(([^)]*)\)(?: \[source: (.*)\])?/;

/** The code for one reason string, matching what close_round and rankBids write. */
export function reasonCode(reason: string): ReasonCode {
  if (/^below this seller floor/.test(reason)) return "below_floor";
  if (/^Bazaar Shield /.test(reason)) return "shield_block";
  if (/^over_cap/.test(reason)) return "over_cap";
  if (VETO.test(reason)) return "advocate_veto";
  if (/^claim did not match the page/.test(reason)) return "claim_false";
  if (/sold out to an earlier round/.test(reason)) return "sold_out";
  if (/^(variant|condition): |: not part of this goal$| qty_available /.test(reason)) return "off_need";
  return "refused";
}

const SHIELD_WORDS: Record<string, string> = {
  "shield.override.instruction": "Hidden instructions aimed at the buying agent",
  "shield.payee.swap": "Tried to send payment to a different payee",
  "shield.exfil.send": "Tried to send data out to someone else",
  "shield.intent.override": "Tried to override what the buyer asked for",
  "shield.agent.denylisted": "Seller agent is on the deny list",
  "shield.agent.unregistered": "Seller agent is not registered",
  "shield.agent.role_mismatch": "Seller agent is not in the role it claimed",
  "shield.unavailable": "Could not be checked by Bazaar Shield",
  "shield.invalid_message": "Message was not in a valid form",
};
const ID_LIKE = /[a-z]+[._][a-z_.]+/;
const plain = (t: string | undefined) => (t && !ID_LIKE.test(t) ? t : undefined);
const GATE_WORDS: Partial<Record<ReasonCode, string>> = {
  below_floor: "Below this seller's floor price",
  over_cap: "Over the buyer's price cap",
  off_need: "Not what the buyer asked for",
  sold_out: "Sold out to an earlier round",
};

function knockFor(id: string, reason: string): Knock {
  const code = reasonCode(reason);
  const v = code === "advocate_veto" ? VETO.exec(reason) : null;
  if (code === "shield_block") {
    const ids = reason.match(/shield\.[\w.]+/g) ?? [];
    const text = [...new Set(ids.map((r) => SHIELD_WORDS[r] ?? "Failed a Bazaar Shield check"))].join("; ") || "Failed a Bazaar Shield check";
    return { id, reasonCode: code, reasonText: text, label: "Blocked by Shield" };
  }
  if (code === "claim_false") {
    const detail = plain(/^claim did not match the page:\s*(.*)$/.exec(reason)?.[1]?.trim() || undefined);
    return { id, reasonCode: code, reasonText: detail ?? "The listing's claim did not check out", label: "Claim check failed" };
  }
  if (!v) {
    const text = GATE_WORDS[code] ?? plain(reason) ?? "Failed a Bazaar check";
    return { id, reasonCode: code, reasonText: text, label: "Refused" };
  }
  const src = v[2] ? safeUrl(v[2]) : null;
  // close_round writes the card detail in the parens: "fit.gpu_length" or "fit.gpu_length: The card is longer ...".
  const rule = /^[\w.]+/.exec(v[1]!)?.[0];
  const detail = plain(/^[\w.]+:\s*(.*)$/.exec(v[1]!)?.[1]?.trim() || undefined);
  const mirror = rule === "mirror_not_orderable";
  const label = mirror ? "Not orderable here" : "Vetoed by Advocate";
  const text = mirror ? "Real store listing, not orderable here" : detail ?? "Failed the appraiser's check";
  return { id, reasonCode: code, reasonText: text, label, ...(rule ? { ruleId: rule } : {}), ...(src ? { sourceUrl: src } : {}) };
}

/** Seed order for a field of `size` (a power of 2): 1 v size, then the halves, so the top seeds meet last. */
function seedOrder(size: number): number[] {
  let order = [1];
  while (order.length < size) {
    const n = order.length * 2;
    order = order.flatMap((s) => [s, n + 1 - s]);
  }
  return order;
}

function roundName(fieldSize: number): string {
  return fieldSize === 2 ? "Final" : fieldSize === 4 ? "Semifinal" : fieldSize === 8 ? "Quarterfinal" : `Round of ${fieldSize}`;
}

const byRank = (a: ResultRow, b: ResultRow) => a.rank - b.rank || (a.bidId < b.bidId ? -1 : a.bidId > b.bidId ? 1 : 0);

const caughtCode = (r: ResultRow): ReasonCode | undefined => CAUGHT.find((c) => r.reasons.some((x) => reasonCode(x) === c));

/** A message when a row the referee ranked (rank > 0) was caught by its own reasons, else null. Takes one round's rows. */
export function inconsistency(rows: readonly ResultRow[]): string | null {
  for (const r of rows) {
    const code = r.rank > 0 ? caughtCode(r) : undefined;
    if (code) return `market record inconsistent: ${r.sellerId} is ranked #${r.rank} but was ${code}`;
  }
  return null;
}

/** The round's winner: its rank 1 bid id. Throws when auction_closed names a different seller, so a bracket never crowns the wrong one. */
export function roundWinner(results: readonly ResultRow[], roundId: string, events: readonly EventRow[]): string | null {
  const bad = inconsistency(results.filter((r) => r.roundId === roundId));
  if (bad) throw new Error(bad);
  const top = results.filter((r) => r.roundId === roundId && r.rank > 0).sort(byRank)[0];
  const closed = events.find((e) => e.kind === "auction_closed" && e.refId === roundId);
  if (closed && closed.sellerId !== (top?.sellerId ?? "")) throw new Error(`round winner mismatch: auction_closed names ${closed.sellerId || "nobody"}, rank 1 is ${top?.sellerId ?? "nobody"}`);
  return top?.bidId ?? null;
}

export function buildBracket(results: readonly ResultRow[], roundId: string): Bracket {
  const rows = results.filter((r) => r.roundId === roundId);
  const entrants: Record<string, Entrant> = {};
  for (const r of rows) {
    const src = safeUrl(r.source);
    entrants[r.bidId] = {
      id: r.bidId, rowRef: `round_result/${r.id}`, sellerId: r.sellerId, name: r.persona || r.sellerId, origin: asOrigin(r.origin),
      rank: r.rank > 0 ? r.rank : null, landed: r.landed, ...(src ? { sourceUrl: src } : {}),
    };
  }

  // Gate and Heat 1: the referee's refusals first (a Shield block outranks a veto on the same bid), then the advocate.
  const problem = inconsistency(rows);
  const out = rows.filter((r) => r.rank <= 0 || caughtCode(r));
  const gate: Knock[] = [];
  const vetoed: Knock[] = [];
  for (const r of out) {
    const g = r.reasons.find((x) => GATE.includes(reasonCode(x)));
    const a = r.reasons.find((x) => !GATE.includes(reasonCode(x)));
    if (g || !a) gate.push(g ? knockFor(r.bidId, g) : { id: r.bidId, reasonCode: "refused", reasonText: "Not ranked by the referee", label: "Refused" });
    else vetoed.push(knockFor(r.bidId, a));
  }
  const all = rows.map((r) => r.bidId);
  const afterGate = all.filter((id) => !gate.some((k) => k.id === id));
  const stages: Stage[] = [
    { name: "Gate", kind: "gate", heats: [{ entrants: all, advances: null, knocked: gate, bye: false }] },
    { name: "Heat 1", kind: "advocate", heats: [{ entrants: afterGate, advances: null, knocked: vetoed, bye: false }] },
  ];

  // Knockout: ranked rows seeded by rank, 1v1, byes for the top seeds; the better (lower) rank advances.
  const ranked = problem ? [] : rows.filter((r) => r.rank > 0 && !caughtCode(r)).sort(byRank);
  if (ranked.length > 1) {
    const size = 2 ** Math.ceil(Math.log2(ranked.length));
    let field: (ResultRow | null)[] = seedOrder(size).map((s) => ranked[s - 1] ?? null);
    while (field.length > 1) {
      const heats: Heat[] = [];
      const next: (ResultRow | null)[] = [];
      for (let i = 0; i < field.length; i += 2) {
        const [a, b] = [field[i]!, field[i + 1]!].filter(Boolean) as ResultRow[];
        if (!a) { next.push(null); continue; }
        if (!b) {
          heats.push({ entrants: [a.bidId], advances: a.bidId, knocked: [], bye: true });
          next.push(a);
          continue;
        }
        const [win, lose] = byRank(a, b) <= 0 ? [a, b] : [b, a];
        const reasonText = `Referee ranked ${win.persona || win.sellerId} #${win.rank} ahead: ${formatMoney(win.landed)} vs ${formatMoney(lose.landed)}`;
        heats.push({ entrants: [a.bidId, b.bidId], advances: win.bidId, knocked: [{ id: lose.bidId, reasonCode: "outranked", reasonText, label: "Outranked" }], bye: false });
        next.push(win);
      }
      stages.push({ name: roundName(field.length), kind: "knockout", heats });
      field = next;
    }
  }

  const champion = ranked[0]?.bidId ?? null;
  stages.push({ name: champion ? "Champion" : "No champion", kind: "champion", heats: champion ? [{ entrants: [champion], advances: champion, knocked: [], bye: false }] : [] });
  const last = stages.filter((s) => s.kind === "knockout").at(-1)?.heats[0]?.advances ?? champion;
  if (last !== champion) throw new Error(`bracket champion ${last} is not the rank 1 bid ${champion}`);
  return { roundId, entrants, stages, champion, ...(problem ? { problem } : {}) };
}
