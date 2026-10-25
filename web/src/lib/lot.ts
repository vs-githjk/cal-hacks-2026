// Client side of the Lot Wall (sim/lot_wall.py writes web/public/lot.json). Pure parsers and helpers plus one fetch.
// A bad file gives no wall, never made up bricks. Every order here is SIM: the featured one is Vidyut's scripted demo goal
// (demo/out/sample-run.json, need source "simulated"), not a live buyer's request. sim/lot_wall.py still writes label "REAL" for it
// (and origin "SIM"); the page never shows that word, it shows the order's origin.

export type Origin = "LIVE" | "MIRROR" | "SIM";

export const LOT_URL = "/lot.json";
export const STAGE_LINE = "This is one scripted demo request, Vidyut's (SIM). When many requests pool, this is what a seller sees.";

export interface LotOrder {
  id: string;
  /** What the page shows: the order's own origin, never "REAL". Scripted orders are SIM. */
  label: Origin;
  /** The one order the file singles out (Vidyut's demo goal); it still carries label SIM. */
  featured: boolean;
  name: string;
  cap: number;
  conditions: string[];
  archetype: string;
  caseMaxGpuMm: number | null;
  psuWatts: number | null;
  deadline: string;
}

export interface Lot {
  skuSpec: string;
  orders: LotOrder[];
  demandAt: { price: number; count: number }[];
  capMedian: number;
  capMin: number;
  capMax: number;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function parseOrder(r: unknown): LotOrder | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  if (typeof o.id !== "string" || typeof o.name !== "string" || !isNum(o.cap) || o.cap <= 0) return null;
  if (o.label !== "REAL" && o.label !== "SIM") return null;
  // The shown label is the order's origin. A file origin of LIVE or MIRROR is not believed for a scripted lot; only SIM is shown.
  const label: Origin = "SIM";
  if (!Array.isArray(o.conditions) || !o.conditions.every((c) => typeof c === "string")) return null;
  return {
    id: o.id,
    label,
    featured: o.label === "REAL",
    name: o.name,
    cap: o.cap,
    conditions: o.conditions as string[],
    archetype: typeof o.archetype === "string" ? o.archetype : "",
    caseMaxGpuMm: isNum(o.case_max_gpu_mm) ? o.case_max_gpu_mm : null,
    psuWatts: isNum(o.psu_watts) ? o.psu_watts : null,
    deadline: typeof o.deadline === "string" ? o.deadline : "",
  };
}

/** Whole-file check: every order must parse, ids must be unique and exactly one order may be featured (label REAL in the file). Otherwise null. */
export function parseLot(json: unknown): Lot | null {
  if (!json || typeof json !== "object") return null;
  const j = json as Record<string, unknown>;
  if (!Array.isArray(j.orders) || j.orders.length === 0) return null;
  const orders = j.orders.map(parseOrder);
  if (orders.some((o) => o === null)) return null;
  const good = orders as LotOrder[];
  if (new Set(good.map((o) => o.id)).size !== good.length) return null;
  if (good.filter((o) => o.featured).length !== 1) return null;
  const caps = good.map((o) => o.cap).sort((a, b) => a - b);
  const mid = Math.floor(caps.length / 2);
  const demand = (j.summary as { demand_at?: unknown } | undefined)?.demand_at;
  const demandAt = Array.isArray(demand)
    ? demand.filter((d): d is [number, number] => Array.isArray(d) && isNum(d[0]) && isNum(d[1])).map(([price, count]) => ({ price, count }))
    : [];
  return {
    skuSpec: typeof j.sku_spec === "string" ? j.sku_spec : "rtx 5070 ti",
    orders: good,
    demandAt,
    capMedian: caps.length % 2 ? caps[mid] : (caps[mid - 1] + caps[mid]) / 2,
    capMin: caps[0],
    capMax: caps[caps.length - 1],
  };
}

/** null when the file is missing or not a lot: the page says so and shows no bricks. */
export async function fetchLot(signal?: AbortSignal): Promise<Lot | null> {
  try {
    const res = await fetch(LOT_URL, { signal, cache: "no-store" });
    if (!res.ok) return null;
    return parseLot(await res.json());
  } catch {
    return null;
  }
}

export function conditionsText(conditions: readonly string[]): string {
  return conditions.length === 0 ? "any condition" : conditions.map((c) => c.replace(/-/g, " ")).join(" or ");
}

export function featuredOrder(lot: Lot): LotOrder {
  return lot.orders.find((o) => o.featured) as LotOrder;
}

/** "17 of 38 orders can pay $1,300 or more", for the demand strip. */
export function demandText(count: number, total: number): string {
  return `${count} of ${total}`;
}

/** "by 2026-10-30T23:59:00Z" becomes "2026-10-30"; "by Friday" becomes "Friday". */
export function deadlineText(d: string): string {
  const t = d.replace(/^by /, "").replace(/T\d\d:\d\d.*$/, "");
  return t || "any time";
}
