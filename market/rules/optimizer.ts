// Split-order optimizer: choose a supplier per line for the lowest total that meets every
// supplier minimum, delivery fees included. Sizes are small (about 30 lines, 6 suppliers), so we
// enumerate supplier subsets, assign each line to the cheapest supplier in the subset, then repair
// any supplier under its minimum by moving in the lines that cost least extra to move.
import type { Allocation, NeedItem, OrderPlan, PlanMode, SupplierTerms } from "./types";
import { money, round2 } from "./types";

export interface Offer {
  supplier_id: string;
  bid_id: string;
  sku_spec: string;
  unit_price: number;
  quantity: number;
}

export interface PlanInput {
  need: { id: string; items: NeedItem[] };
  offers: Offer[];
  terms: SupplierTerms[];
  advocate?: boolean;
  names?: { suppliers?: Record<string, string>; items?: Record<string, string> };
}

export type Plan = Omit<OrderPlan, "source"> & { uncovered: string[] };

const cents = (x: number) => Math.round(x * 100);
const byStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** Turn sealed bids into per-line offers: cheapest eligible line per supplier, full quantity only. */
export function offersFromBids(
  bids: { id: string; supplier_id: string; lines: { sku_spec: string; unit_price: number; quantity: number }[] }[],
  need: { id: string; items: NeedItem[] },
  eligible: (bidId: string, sku_spec: string) => boolean = () => true,
): Offer[] {
  const needQty = new Map(need.items.map((i) => [i.sku_spec, i.quantity]));
  const best = new Map<string, Offer>();
  for (const bid of bids) {
    for (const l of bid.lines) {
      const q = needQty.get(l.sku_spec);
      if (q === undefined || l.quantity < q || !eligible(bid.id, l.sku_spec)) continue;
      const key = `${bid.supplier_id}|${l.sku_spec}`;
      const cur = best.get(key);
      if (!cur || l.unit_price < cur.unit_price || (l.unit_price === cur.unit_price && bid.id < cur.bid_id)) {
        best.set(key, { supplier_id: bid.supplier_id, bid_id: bid.id, sku_spec: l.sku_spec, unit_price: l.unit_price, quantity: q });
      }
    }
  }
  return [...best.values()].sort((a, b) => byStr(a.supplier_id, b.supplier_id) || byStr(a.sku_spec, b.sku_spec));
}

interface Ctx {
  lines: string[]; // coverable sku_specs, sorted
  offer: Map<string, Map<string, Offer>>; // sku -> supplier -> offer
  terms: Map<string, SupplierTerms>;
}

const lineCost = (o: Offer) => cents(o.unit_price * o.quantity);
const minOf = (ctx: Ctx, s: string) => cents(ctx.terms.get(s)?.min_order_value ?? 0);
function feeOf(ctx: Ctx, s: string, subtotalC: number): number {
  const t = ctx.terms.get(s);
  if (!t || t.free_delivery_over <= 0) return 0;
  return subtotalC < cents(t.free_delivery_over) ? cents(t.delivery_fee) : 0;
}

type Assignment = Map<string, string>; // sku -> supplier

function cheapestIn(ctx: Ctx, allowed: (s: string) => boolean): Assignment | null {
  const a: Assignment = new Map();
  for (const sku of ctx.lines) {
    let pick: Offer | undefined;
    for (const o of ctx.offer.get(sku)!.values()) {
      if (!allowed(o.supplier_id)) continue;
      if (!pick || lineCost(o) < lineCost(pick) || (lineCost(o) === lineCost(pick) && o.supplier_id < pick.supplier_id)) pick = o;
    }
    if (!pick) return null;
    a.set(sku, pick.supplier_id);
  }
  return a;
}

function subtotals(ctx: Ctx, a: Assignment): Map<string, number> {
  const m = new Map<string, number>();
  for (const [sku, s] of a) m.set(s, (m.get(s) ?? 0) + lineCost(ctx.offer.get(sku)!.get(s)!));
  return m;
}

function totalOf(ctx: Ctx, a: Assignment): { sub: number; fees: number } {
  let sub = 0;
  let fees = 0;
  for (const [s, st] of subtotals(ctx, a)) {
    sub += st;
    fees += feeOf(ctx, s, st);
  }
  return { sub, fees };
}

const underMin = (ctx: Ctx, a: Assignment) =>
  [...subtotals(ctx, a)].filter(([s, st]) => st < minOf(ctx, s)).map(([s]) => s).sort(byStr);

/** Move lines into suppliers under their minimum without pushing a donor under its own. */
function repair(ctx: Ctx, start: Assignment): Assignment | null {
  const a = new Map(start);
  for (let guard = 0; guard < ctx.lines.length * ctx.lines.length + 1; guard++) {
    const short = underMin(ctx, a)[0];
    if (short === undefined) return a;
    const subs = subtotals(ctx, a);
    let best: { sku: string; ratio: number } | undefined;
    for (const sku of ctx.lines) {
      const donor = a.get(sku)!;
      const into = ctx.offer.get(sku)!.get(short);
      if (donor === short || !into) continue;
      const out = lineCost(ctx.offer.get(sku)!.get(donor)!);
      const donorLeft = subs.get(donor)! - out;
      if (donorLeft > 0 && donorLeft < minOf(ctx, donor)) continue;
      const ratio = (lineCost(into) - out) / Math.max(lineCost(into), 1);
      if (!best || ratio < best.ratio || (ratio === best.ratio && sku < best.sku)) best = { sku, ratio };
    }
    if (!best) return null;
    a.set(best.sku, short);
  }
  return null;
}

export function planOrder(input: PlanInput, mode: PlanMode): Plan {
  const offer = new Map<string, Map<string, Offer>>();
  for (const o of input.offers) {
    if (!offer.has(o.sku_spec)) offer.set(o.sku_spec, new Map());
    const cur = offer.get(o.sku_spec)!.get(o.supplier_id);
    if (!cur || lineCost(o) < lineCost(cur) || (lineCost(o) === lineCost(cur) && o.bid_id < cur.bid_id)) {
      offer.get(o.sku_spec)!.set(o.supplier_id, o);
    }
  }
  const ctx: Ctx = {
    lines: [...offer.keys()].sort(byStr),
    offer,
    terms: new Map(input.terms.map((t) => [t.supplier_id, t])),
  };
  const uncovered = input.need.items.map((i) => i.sku_spec).filter((s) => !offer.has(s));
  const naive = cheapestIn(ctx, () => true) ?? new Map();

  let chosen: Assignment = naive;
  if (mode === "optimizer" && ctx.lines.length) {
    const suppliers = [...new Set(input.offers.map((o) => o.supplier_id))].sort(byStr);
    let best: { a: Assignment; total: number; n: number } | undefined;
    for (let mask = 1; mask < 1 << suppliers.length; mask++) {
      const inSet = new Set(suppliers.filter((_, i) => mask & (1 << i)));
      const start = cheapestIn(ctx, (s) => inSet.has(s));
      if (!start || new Set(start.values()).size !== inSet.size) continue;
      const fixed = repair(ctx, start);
      if (!fixed) continue;
      const { sub, fees } = totalOf(ctx, fixed);
      const n = new Set(fixed.values()).size;
      if (!best || sub + fees < best.total || (sub + fees === best.total && n < best.n)) best = { a: fixed, total: sub + fees, n };
    }
    if (best) chosen = best.a;
  }
  return toPlan(input, ctx, mode, chosen, naive, uncovered);
}

function toPlan(input: PlanInput, ctx: Ctx, mode: PlanMode, a: Assignment, naive: Assignment, uncovered: string[]): Plan {
  const sName = (s: string) => input.names?.suppliers?.[s] ?? s;
  const iName = (k: string) => input.names?.items?.[k] ?? k;
  const bySup = new Map<string, Allocation>();
  for (const sku of ctx.lines) {
    const s = a.get(sku)!;
    const o = ctx.offer.get(sku)!.get(s)!;
    if (!bySup.has(s)) bySup.set(s, { supplier_id: s, bid_id: o.bid_id, lines: [] });
    bySup.get(s)!.lines.push({ sku_spec: sku, quantity: o.quantity, unit_price: o.unit_price });
  }
  const allocations = [...bySup.values()].sort((x, y) => byStr(x.supplier_id, y.supplier_id));
  const { sub, fees } = totalOf(ctx, a);
  const short = underMin(ctx, a);
  const naiveTotal = totalOf(ctx, naive);

  const explanation: string[] = [];
  if (mode === "optimizer") {
    for (const sku of ctx.lines) {
      const from = naive.get(sku)!;
      const to = a.get(sku)!;
      if (from === to) continue;
      const delta = lineCost(ctx.offer.get(sku)!.get(to)!) - lineCost(ctx.offer.get(sku)!.get(from)!);
      explanation.push(`Moved ${iName(sku)} from ${sName(from)} to ${sName(to)}: ${money(delta / 100)} more on that line.`);
    }
  }
  for (const s of underMin(ctx, naive)) {
    if (mode === "optimizer" && !a.size) break;
    const st = subtotals(ctx, naive).get(s)!;
    const moved = mode === "optimizer" && !short.includes(s);
    explanation.push(
      moved
        ? `Cheapest per line would send ${sName(s)} only ${money(st / 100)}, under its ${money(minOf(ctx, s) / 100)} minimum; this plan clears it.`
        : `${sName(s)} gets ${money(st / 100)}, under its ${money(minOf(ctx, s) / 100)} minimum, so the supplier may refuse this order.`,
    );
  }
  if (mode === "optimizer" && naiveTotal.fees > fees) explanation.push(`Saves ${money((naiveTotal.fees - fees) / 100)} in delivery fees.`);
  if (mode === "optimizer" && a === naive) explanation.push("Cheapest per line already meets every minimum; no changes needed.");
  for (const s of uncovered) explanation.push(`No eligible bid for ${iName(s)}; order it separately.`);
  const total = sub + fees;
  explanation.push(
    mode === "optimizer"
      ? `Total ${money(total / 100)} against ${money((naiveTotal.sub + naiveTotal.fees) / 100)} for cheapest per line.`
      : `Total ${money(total / 100)}: cheapest bid on every line, ignoring minimums.`,
  );

  return {
    id: `${input.need.id}:${mode}:${input.advocate === false ? "no-advocate" : "advocate"}`,
    need_id: input.need.id,
    mode,
    advocate: input.advocate !== false,
    allocations,
    subtotal: round2(sub / 100),
    fees: round2(fees / 100),
    total: round2(total / 100),
    savings_vs_baseline: round2((naiveTotal.sub + naiveTotal.fees - total) / 100),
    explanation,
    feasible: short.length === 0,
    uncovered,
  };
}
