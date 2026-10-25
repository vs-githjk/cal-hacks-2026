// Client side of the buyer memory feed (GET /v1/memory on scripts/agent_feed.py, contracts/MemoryEntry.schema.json).
// Recorded history only: every row is validated against the contract, a bad row is dropped and counted (never repaired),
// and nothing here ranks, searches semantically, or joins rows that the source did not link.

import { FEED_ENV, FEED_URL, feedBase } from "./agentFeed.ts";
import { safeUrl } from "./url.ts";

export type Origin = "LIVE" | "MIRROR" | "SIM";

interface Common {
  id: string;
  /** ISO 8601, or "" when the source has no time. Read it through entryDate. */
  at: string;
  origin: Origin;
  source: "demo_run" | "market";
  source_ref: string;
  buyer_id: string;
  seller_id: string;
  summary: string;
}

export interface GoalDetail { goal_id: string; items: { sku_spec: string; condition: string; quantity: number }[]; cap: number; deadline: string; text?: string }
export interface PurchaseDetail {
  mandate_id: string;
  deal_id: string;
  amount_before_tax: number;
  currency: string;
  payee: string;
  approval_method: string;
  payment_mode: "sim" | "stripe_test" | "none";
  payment_ref: string;
  listing_origin: Origin;
}
export interface VetoDetail { bid_id: string; rule_id: string; reason: string; source_url: string }
export interface LessonDetail { round_id: string; won: boolean; reason: string; gap_band: "within5" | "within10" | "within20" | "over20"; what_to_change: string }

export type MemoryEntry = Common &
  (
    | { kind: "goal"; detail: GoalDetail }
    | { kind: "purchase"; detail: PurchaseDetail }
    | { kind: "veto"; detail: VetoDetail }
    | { kind: "lesson"; detail: LessonDetail }
  );
export type MemoryKind = MemoryEntry["kind"];

/** The producer's per-file status. An unreadable status row becomes kind "unknown", state "error". */
export interface MemorySource { ref: string; kind: "market" | "demo_run" | "unknown"; state: "ok" | "empty" | "error"; sample: boolean; rows: number; dropped?: number }

export interface MemoryResponse {
  entries: MemoryEntry[];
  sources: MemorySource[];
  note: string;
  /** Rows the feed sent that failed the contract and were left out. Show it, so a corrupt feed never looks like a short history. */
  rejected: number;
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string";
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const oneOf = <T extends string>(v: unknown, set: readonly T[]): v is T => typeof v === "string" && (set as readonly string[]).includes(v);

const ORIGINS = ["LIVE", "MIRROR", "SIM"] as const;
const BANDS = ["within5", "within10", "within20", "over20"] as const;

function parseDetail(kind: MemoryKind, d: unknown): MemoryEntry["detail"] | null {
  if (!isObj(d)) return null;
  switch (kind) {
    case "goal": {
      if (!str(d.goal_id) || !num(d.cap) || !str(d.deadline) || !Array.isArray(d.items)) return null;
      const items: GoalDetail["items"] = [];
      for (const i of d.items) {
        if (!isObj(i) || !str(i.sku_spec) || !str(i.condition) || !num(i.quantity)) return null;
        items.push({ sku_spec: i.sku_spec, condition: i.condition, quantity: i.quantity });
      }
      return { goal_id: d.goal_id, items, cap: d.cap, deadline: d.deadline, ...(str(d.text) ? { text: d.text } : {}) };
    }
    case "purchase":
      // A receipt-like row needs a real amount: booleans, strings, NaN, zero and negatives are not one.
      if (!str(d.mandate_id) || !str(d.deal_id) || !num(d.amount_before_tax) || d.amount_before_tax <= 0 || !str(d.currency) || !str(d.payee) || !str(d.approval_method) || !oneOf(d.payment_mode, ["sim", "stripe_test", "none"] as const) || !str(d.payment_ref) || !oneOf(d.listing_origin, ORIGINS)) return null;
      return { mandate_id: d.mandate_id, deal_id: d.deal_id, amount_before_tax: d.amount_before_tax, currency: d.currency, payee: d.payee, approval_method: d.approval_method, payment_mode: d.payment_mode, payment_ref: d.payment_ref, listing_origin: d.listing_origin };
    case "veto":
      if (!str(d.bid_id) || !str(d.rule_id) || !str(d.reason) || !str(d.source_url)) return null;
      return { bid_id: d.bid_id, rule_id: d.rule_id, reason: d.reason, source_url: d.source_url };
    case "lesson":
      // Bands only: a raw gap would leak a competitor's price.
      if (!str(d.round_id) || typeof d.won !== "boolean" || !str(d.reason) || !oneOf(d.gap_band, BANDS) || !str(d.what_to_change)) return null;
      return { round_id: d.round_id, won: d.won, reason: d.reason, gap_band: d.gap_band, what_to_change: d.what_to_change };
  }
}

function parseEntry(v: unknown): MemoryEntry | null {
  if (!isObj(v) || !str(v.id) || !v.id || !oneOf(v.kind, ["goal", "purchase", "veto", "lesson"] as const)) return null;
  if (!str(v.at) || !oneOf(v.origin, ORIGINS) || !oneOf(v.source, ["demo_run", "market"] as const)) return null;
  if (!str(v.source_ref) || !str(v.buyer_id) || !str(v.seller_id) || !str(v.summary)) return null;
  const detail = parseDetail(v.kind, v.detail);
  if (!detail) return null;
  return { id: v.id, kind: v.kind, at: v.at, origin: v.origin, source: v.source, source_ref: v.source_ref, buyer_id: v.buyer_id, seller_id: v.seller_id, summary: v.summary, detail } as MemoryEntry;
}

function parseSource(v: unknown): MemorySource {
  if (isObj(v) && str(v.ref) && oneOf(v.kind, ["market", "demo_run"] as const) && oneOf(v.state, ["ok", "empty", "error"] as const) && typeof v.sample === "boolean" && num(v.rows) && Number.isInteger(v.rows) && v.rows >= 0) {
    return { ref: v.ref, kind: v.kind, state: v.state, sample: v.sample, rows: v.rows, ...(num(v.dropped) && v.dropped >= 0 ? { dropped: v.dropped } : {}) };
  }
  return { ref: isObj(v) && str(v.ref) ? v.ref : "(unreadable source)", kind: "unknown", state: "error", sample: false, rows: 0 };
}

/** Validate the producer's {entries, sources, note}. Throws on a wrong envelope; drops and counts bad rows. */
export function parseMemoryResponse(value: unknown): MemoryResponse {
  if (!isObj(value) || !Array.isArray(value.entries) || !Array.isArray(value.sources)) {
    throw new Error("memory response is not the expected {entries, sources, note} shape");
  }
  const entries = value.entries.flatMap((e) => parseEntry(e) ?? []);
  return {
    entries,
    sources: value.sources.map(parseSource),
    note: str(value.note) ? value.note : "",
    rejected: value.entries.length - entries.length,
  };
}

/** The memory feed to read from a page on `pageHost`, or null when this page must not fetch it (a loopback feed seen from a hosted page). Never throws. */
export function memoryFeed(pageHost: string, env: string | undefined = FEED_ENV): string | null {
  return feedBase(env, pageHost);
}

/**
 * The one read path. Throws visibly (HTTP error, unreachable feed, not JSON, wrong shape); an aborted read rethrows its AbortError.
 * `buyerId` goes as ?buyer= so a feed run with AGENT_FEED_TOKEN (#449 PL-17) can return only this buyer's rows. The page never holds
 * that token, so it sends none: a feed that needs one answers 401 here and shows as an error, as an unreachable feed does.
 */
export async function fetchMemory(signal?: AbortSignal, feed: string = FEED_URL, buyerId?: string): Promise<MemoryResponse> {
  const aborted = (e: unknown) => !!signal?.aborted || (e as { name?: string } | null)?.name === "AbortError";
  let res: Response;
  try {
    res = await fetch(`${feed}/v1/memory${buyerId ? `?buyer=${encodeURIComponent(buyerId)}` : ""}`, { signal, cache: "no-store" });
  } catch (e) {
    if (aborted(e)) throw e;
    throw new Error(`memory feed unreachable at ${feed}`);
  }
  if (!res.ok) throw new Error(`memory feed answered HTTP ${res.status}`);
  let body: unknown;
  try {
    body = await res.json();
  } catch (e) {
    if (aborted(e)) throw e;
    throw new Error("memory response is not JSON");
  }
  return parseMemoryResponse(body);
}

/** A real time, or null when the source has none or it is not a date. Never guesses. */
export function entryDate(e: { at: string }): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}(T|$)/.test(e.at)) return null;
  const t = Date.parse(e.at);
  return Number.isNaN(t) ? null : new Date(t);
}

const strings = (d: object): string[] =>
  Object.values(d).flatMap((v) => (typeof v === "string" ? [v] : Array.isArray(v) ? v.flatMap((x) => (isObj(x) ? strings(x) : [])) : []));

/** Newest first by real time, unknown times last (feed order within ties). The query is a plain case-insensitive match over recorded text, not semantic search. */
export function selectMemory(entries: readonly MemoryEntry[], kind: MemoryKind | "all", query: string): MemoryEntry[] {
  const q = query.trim().toLowerCase();
  return entries
    .filter((e) => (kind === "all" || e.kind === kind) && (!q || [e.summary, e.seller_id, ...strings(e.detail)].some((s) => s.toLowerCase().includes(q))))
    .map((e, i) => ({ e, i, t: entryDate(e)?.getTime() ?? null }))
    .sort((a, b) => (a.t === b.t ? a.i - b.i : a.t === null ? 1 : b.t === null ? -1 : b.t - a.t))
    .map((x) => x.e);
}

/**
 * Rows recorded for this buyer id. Display hygiene only: the demo feed is not buyer scoped on the server, so this is
 * not an authorization boundary. A row with no buyer id, or no paired buyer, shows nothing, except a seller lesson:
 * the producer writes those against the seller (bands only), so they carry no buyer id by design.
 */
export function memoryForBuyer(entries: readonly MemoryEntry[], buyerId: string): MemoryEntry[] {
  return buyerId ? entries.filter((e) => e.buyer_id === buyerId || ((e.kind === "lesson" || e.kind === "veto") && e.buyer_id === "")) : [];
}

/** The veto's source as a link, only when it is a real web address. */
export function sourceUrl(e: MemoryEntry): string | null {
  return e.kind === "veto" ? safeUrl(e.detail.source_url) : null;
}

export function paymentModeLabel(m: PurchaseDetail["payment_mode"]): string {
  return { sim: "SIM payment, no money moved", stripe_test: "Stripe test mode, no real money", none: "No payment recorded" }[m];
}

export function approvalLabel(method: string): string {
  return ({ voice_code: "Approved by phone code", allowance: "Within allowance", sim_script: "Scripted SIM approval", typed_code: "Typed code (retired)", none: "No approval method recorded" } as Record<string, string>)[method] ?? "Unavailable";
}

// ---- #449 PL-13: no raw ids on the customer path (/buyer/purchases and /buyer/decisions)

const RAW_ID = /^(agent1q|seller[_-]?\d|b_[a-z0-9]{4,}|mdt|ch_|pi_|deal[-_]|round[_-]|bid[-_]|va-)|^[0-9a-f]{12,}$|\d{3,}/i;

/** A seller or payee as a person would say it: a readable name stays; a slug becomes words; an id, address or hash becomes "the seller". */
export function plainName(id: string): string {
  const s = id.trim();
  if (!s || RAW_ID.test(s)) return "the seller";
  if (/\s/.test(s)) return s;
  return s.split(/[-_]+/).filter(Boolean).map((w) => w[0]!.toUpperCase() + w.slice(1)).join(" ") || "the seller";
}

/** The last 6 characters of a payment reference, the only part of it a customer sees ("" when there is none). */
export function shortReceipt(ref: string): string {
  return ref.trim().slice(-6);
}
