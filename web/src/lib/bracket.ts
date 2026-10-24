// web/src/lib/bracket.ts
// The Bidding Royale bracket, drawn only from the referee's own decisions in round_result rows: refusals at the
// Gate (Shield, below floor, over_cap, off need, sold out), advocate vetoes in Heat 1, then the ranked bids
// played 1v1 by the close_round rank (adjusted_total shown, the referee's tiebreak already inside the rank).
// No matchup is invented: the champion is always the rank 1 row, and roundWinner cross-checks auction_closed.
import { formatMoney } from "./money.ts";
import { safeUrl } from "./url.ts";
import { asOrigin, type Origin } from "./screens.ts";

interface ResultRow {
  id: bigint; roundId: string; bidId: string; sellerId: string; persona: string; rank: number; landed: number;
  reasons: string[]; origin: string; source: string; adjustedTotal: number; adjustmentReason: string;
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
  adjusted: number | null; // the score close_round ranked on; null when not ranked
  adjustmentReason: string;
  sourceUrl?: string;
}
export interface Knock { id: string; reasonCode: ReasonCode; reasonText: string; ruleId?: string; sourceUrl?: string }
export interface Heat { entrants: string[]; advances: string | null; knocked: Knock[]; bye: boolean }
export interface Stage { name: string; kind: "gate" | "advocate" | "knockout" | "champion"; heats: Heat[] }
export interface Bracket { roundId: string; entrants: Record<string, Entrant>; stages: Stage[]; champion: string | null }

const GATE: ReasonCode[] = ["shield_block", "below_floor", "over_cap", "off_need", "sold_out", "refused"];
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

function knockFor(id: string, reason: string): Knock {
  const code = reasonCode(reason);
  const v = code === "advocate_veto" ? VETO.exec(reason) : null;
  if (!v) return { id, reasonCode: code, reasonText: reason };
  const src = v[2] ? safeUrl(v[2]) : null;
  return { id, reasonCode: code, reasonText: `Advocate veto (${v[1]})`, ruleId: v[1], ...(src ? { sourceUrl: src } : {}) };
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

/** The round's winner: its rank 1 bid id. Throws when auction_closed names a different seller, so a bracket never crowns the wrong one. */
export function roundWinner(results: readonly ResultRow[], roundId: string, events: readonly EventRow[]): string | null {
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
      rank: r.rank > 0 ? r.rank : null, landed: r.landed, adjusted: r.rank > 0 ? r.adjustedTotal : null,
      adjustmentReason: r.rank > 0 ? r.adjustmentReason : "", ...(src ? { sourceUrl: src } : {}),
    };
  }

  // Gate and Heat 1: the referee's refusals first (a Shield block outranks a veto on the same bid), then the advocate.
  const out = rows.filter((r) => r.rank <= 0);
  const gate: Knock[] = [];
  const vetoed: Knock[] = [];
  for (const r of out) {
    const g = r.reasons.find((x) => GATE.includes(reasonCode(x)));
    const a = r.reasons.find((x) => !GATE.includes(reasonCode(x)));
    if (g || !a) gate.push(g ? knockFor(r.bidId, g) : { id: r.bidId, reasonCode: "refused", reasonText: "Not ranked by the referee" });
    else vetoed.push(knockFor(r.bidId, a));
  }
  const all = rows.map((r) => r.bidId);
  const afterGate = all.filter((id) => !gate.some((k) => k.id === id));
  const stages: Stage[] = [
    { name: "Gate", kind: "gate", heats: [{ entrants: all, advances: null, knocked: gate, bye: false }] },
    { name: "Heat 1", kind: "advocate", heats: [{ entrants: afterGate, advances: null, knocked: vetoed, bye: false }] },
  ];

  // Knockout: ranked rows seeded by rank, 1v1, byes for the top seeds; the better (lower) rank advances.
  const ranked = rows.filter((r) => r.rank > 0).sort(byRank);
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
        const reasonText = `Referee ranked ${win.persona || win.sellerId} #${win.rank} ahead: adjusted ${formatMoney(win.adjustedTotal)} vs ${formatMoney(lose.adjustedTotal)}`;
        heats.push({ entrants: [a.bidId, b.bidId], advances: win.bidId, knocked: [{ id: lose.bidId, reasonCode: "outranked", reasonText }], bye: false });
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
  return { roundId, entrants, stages, champion };
}
