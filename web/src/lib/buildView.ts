// Client side of Lane D's build board shape (docs/changes/1650-D-build-board-shape.md, contracts/samples/build-board.sample.json).
// Every row is validated against that shape; a bad row is dropped and counted, never repaired. Fit and price come from the
// rows as recorded: nothing here decides a fit, it only maps the BuildView onto the panel's BuildResult.

import type { BuildResult, BuildStep } from "./build.ts";

export type Origin = "LIVE" | "MIRROR" | "SIM";
const ORIGINS = ["LIVE", "MIRROR", "SIM"] as const;
const PART_KEYS = ["gpu", "cpu", "board", "ram", "ssd", "cooler", "psu", "case"] as const;
const STATUSES = ["owned", "planned", "bidding", "locked", "replanned", "failed"] as const;
const RULES = ["socket", "ddr", "case_room", "power", "cooler_height"] as const;
const EVENT_KINDS = ["plan", "round_open", "knockout", "locked", "clash", "replan", "call", "approved", "denied", "receipt"] as const;
const APPROVAL_STATES = ["waiting", "calling", "approved", "denied", "paid"] as const;

type PartKey = (typeof PART_KEYS)[number];
export interface Champion { bidId: string; sellerId: string; persona: string; landed: number; origin: Origin; sourceUrl: string }
export interface BuildPart { part: PartKey; label: string; status: (typeof STATUSES)[number]; budget: number; needId?: string; roundId?: string; champion?: Champion; reason?: string }
export interface BuildCheck { a: PartKey; b: PartKey; rule: (typeof RULES)[number]; state: "ok" | "clash" | "unknown"; detail: string; source: string }
export interface BuildEvent { at: string; kind: (typeof EVENT_KINDS)[number]; text: string; parts: PartKey[] }
export interface BuildView {
  goalId: string; buyerId: string; budget: number; spent: number; origin: Origin;
  parts: BuildPart[]; checks: BuildCheck[]; events: BuildEvent[];
  approval: { state: (typeof APPROVAL_STATES)[number]; total: number; sellers: number } | null;
  /** Rows that failed the shape and were left out. Show it, so a corrupt feed never looks like a short build. */
  rejected: number;
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string";
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const oneOf = <T extends string>(v: unknown, set: readonly T[]): v is T => typeof v === "string" && (set as readonly string[]).includes(v);

function parseChampion(c: unknown): Champion | null {
  if (!isObj(c) || !str(c.bidId) || !str(c.sellerId) || !str(c.persona) || !num(c.landed) || c.landed <= 0 || !oneOf(c.origin, ORIGINS) || !str(c.sourceUrl)) return null;
  return { bidId: c.bidId, sellerId: c.sellerId, persona: c.persona, landed: c.landed, origin: c.origin, sourceUrl: c.sourceUrl };
}

function parsePart(p: unknown): BuildPart | null {
  if (!isObj(p) || !oneOf(p.part, PART_KEYS) || !str(p.label) || !oneOf(p.status, STATUSES) || !num(p.budget) || p.budget < 0) return null;
  const champion = p.champion === undefined ? undefined : parseChampion(p.champion);
  if (champion === null) return null; // a champion that is present but malformed drops the row
  if ((p.status === "locked" || p.status === "replanned") && !champion) return null;
  return {
    part: p.part, label: p.label, status: p.status, budget: p.budget,
    ...(str(p.needId) ? { needId: p.needId } : {}), ...(str(p.roundId) ? { roundId: p.roundId } : {}),
    ...(champion ? { champion } : {}), ...(str(p.reason) ? { reason: p.reason } : {}),
  };
}

function parseCheck(c: unknown): BuildCheck | null {
  if (!isObj(c) || !oneOf(c.a, PART_KEYS) || !oneOf(c.b, PART_KEYS) || !oneOf(c.rule, RULES) || !oneOf(c.state, ["ok", "clash", "unknown"] as const) || !str(c.detail) || !str(c.source)) return null;
  return { a: c.a, b: c.b, rule: c.rule, state: c.state, detail: c.detail, source: c.source };
}

function parseEvent(e: unknown): BuildEvent | null {
  if (!isObj(e) || !str(e.at) || !oneOf(e.kind, EVENT_KINDS) || !str(e.text) || !e.text || !Array.isArray(e.parts) || !e.parts.every((x) => oneOf(x, PART_KEYS))) return null;
  return { at: e.at, kind: e.kind, text: e.text, parts: e.parts as PartKey[] };
}

/** Validate one BuildView. Throws on a wrong envelope; drops and counts bad parts, checks and events. */
export function parseBuildView(v: unknown): BuildView {
  if (!isObj(v) || !str(v.goalId) || !v.goalId || !str(v.buyerId) || !num(v.budget) || v.budget <= 0 || !num(v.spent) || v.spent < 0 || !oneOf(v.origin, ORIGINS)
    || !Array.isArray(v.parts) || !Array.isArray(v.checks) || !Array.isArray(v.events)) {
    throw new Error("build is not the expected BuildView shape");
  }
  const parts = v.parts.flatMap((p) => parsePart(p) ?? []);
  const checks = v.checks.flatMap((c) => parseCheck(c) ?? []);
  const events = v.events.flatMap((e) => parseEvent(e) ?? []);
  const a = v.approval;
  const approval = isObj(a) && oneOf(a.state, APPROVAL_STATES) && num(a.total) && num(a.sellers) ? { state: a.state, total: a.total, sellers: a.sellers } : null;
  return {
    goalId: v.goalId, buyerId: v.buyerId, budget: v.budget, spent: v.spent, origin: v.origin, parts, checks, events, approval,
    rejected: v.parts.length - parts.length + (v.checks.length - checks.length) + (v.events.length - events.length) + (a !== undefined && a !== null && !approval ? 1 : 0),
  };
}

// The panel's part keys (build.ts PARTS) predate Lane D's names.
const PANEL_KEY: Record<PartKey, string> = { gpu: "gpu", cpu: "cpu", board: "motherboard", ram: "memory", ssd: "storage", cooler: "cooler", psu: "psu", case: "case" };
// ponytail: round_open, call, approved, denied and receipt have no panel step yet; approval and receipts live on their own cards.
const STEP_KIND: Partial<Record<BuildEvent["kind"], BuildStep["kind"]>> = { plan: "plan", knockout: "knockout", clash: "clash", replan: "swap", locked: "locked" };
const cents = (dollars: number) => Math.round(dollars * 100);

/** The BuildView as the panel's BuildResult: picks carry their listing origin, owned parts stay out of the rounds. */
export function toBuildResult(v: BuildView): BuildResult {
  const bought = v.parts.filter((p) => p.status !== "owned");
  const replanned = new Set(v.parts.filter((p) => p.status === "replanned").map((p) => p.part));
  const steps: BuildStep[] = v.events.flatMap((e) => {
    const kind = STEP_KIND[e.kind];
    if (!kind) return [];
    // A replan names every part it touched; the swapped one is the part now marked replanned.
    const part = (e.kind === "replan" ? e.parts.find((p) => replanned.has(p)) : undefined) ?? e.parts[0];
    return [{ kind, line: e.text, ...(part ? { part: PANEL_KEY[part] } : {}), ...(e.parts.length > 1 ? { with: e.parts.slice(1).map((p) => PANEL_KEY[p]) } : {}) }];
  });
  const picks = Object.fromEntries(bought.flatMap((p) => (p.champion ? [[PANEL_KEY[p.part], { seller: p.champion.persona || p.champion.sellerId, priceCents: cents(p.champion.landed), name: p.label, origin: p.champion.origin }]] : [])));
  return {
    owned: Object.fromEntries(v.parts.filter((p) => p.status === "owned").map((p) => [PANEL_KEY[p.part], p.label])),
    status: bought.some((p) => p.status === "failed") ? "blocked" : v.rejected === 0 && bought.length > 0 && bought.every((p) => p.champion) ? "locked" : "open",
    totalCents: cents(v.spent),
    capCents: cents(v.budget),
    sellers: [...new Set(Object.values(picks).map((p) => p.seller))].sort(),
    picks,
    budgets: Object.fromEntries(bought.map((p) => [PANEL_KEY[p.part], cents(p.budget)])),
    steps,
    origin: v.origin,
    rejected: v.rejected,
    partStatus: Object.fromEntries(bought.map((p) => [PANEL_KEY[p.part], p.status as NonNullable<BuildResult["partStatus"]>[string]])),
    partReason: Object.fromEntries(bought.flatMap((p) => (p.reason ? [[PANEL_KEY[p.part], p.reason]] : []))),
    checks: v.checks.map((c) => ({ ...c, a: PANEL_KEY[c.a], b: PANEL_KEY[c.b] })),
    approval: v.approval,
  };
}

/**
 * The live build, or null when none is posted (404, or a null body). Throws visibly on an unreachable feed, HTTP error,
 * non-JSON body or wrong shape. ponytail: GET /v1/build on the agent feed is this lane's proposal; Lane D owns where the
 * BuildView is served, so change this one URL when it lands.
 */
export async function fetchBuild(feedUrl: string, signal?: AbortSignal): Promise<BuildView | null> {
  const res = await fetch(`${feedUrl}/v1/build`, { signal, cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`build feed answered HTTP ${res.status}`);
  const body: unknown = await res.json();
  return body === null ? null : parseBuildView(body);
}
