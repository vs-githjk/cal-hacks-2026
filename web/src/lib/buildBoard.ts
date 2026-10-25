// Client side of the full-PC build board (#343). Lane D writes contracts/samples/build-board.sample.json
// (copied here to public/build-board.json) today; the live data arrives in the same shape (see
// docs/changes/1650-D-build-board-shape.md). A bad or missing file gives no board, never made-up parts.
// This module only reads the data: it never decides a fit or a price.

export const BUILD_BOARD_URL = "/build-board.json";

export const PARTS = ["gpu", "cpu", "board", "ram", "ssd", "cooler", "psu", "case"] as const;
export type Part = (typeof PARTS)[number];

export const PART_LABELS: Record<Part, string> = {
  gpu: "GPU", cpu: "CPU", board: "Board", ram: "RAM", ssd: "SSD", cooler: "Cooler", psu: "PSU", case: "Case",
};

export type PartStatus = "owned" | "planned" | "bidding" | "locked" | "replanned" | "failed";
export type CheckRule = "socket" | "ddr" | "case_room" | "power" | "cooler_height";
export type CheckState = "ok" | "clash" | "unknown";
export type EventKind = "plan" | "round_open" | "knockout" | "locked" | "clash" | "replan" | "call" | "approved" | "denied" | "receipt";
export type ApprovalState = "waiting" | "calling" | "approved" | "denied" | "paid";

export interface Champion {
  bidId: string;
  sellerId: string;
  persona: string;
  landed: number;
  origin: string;
  sourceUrl: string;
}

export interface BuildPart {
  part: Part;
  label: string;
  status: PartStatus;
  budget: number;
  needId?: string;
  roundId?: string;
  champion?: Champion;
  reason?: string;
}

export interface BuildCheck {
  a: Part;
  b: Part;
  rule: CheckRule;
  state: CheckState;
  detail: string;
  source: string;
}

export interface BuildEvent {
  at: string;
  kind: EventKind;
  text: string;
  parts: Part[];
}

export interface BuildApproval {
  state: ApprovalState;
  total: number;
  sellers: number;
  mandates: { sellerId: string; amount: number; mandateHash: string }[];
}

export interface BuildView {
  goalId: string;
  buyerId: string;
  budget: number;
  spent: number;
  origin: string;
  parts: BuildPart[];
  checks: BuildCheck[];
  events: BuildEvent[];
  approval: BuildApproval;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isPart = (v: unknown): v is Part => isStr(v) && (PARTS as readonly string[]).includes(v);

function parseChampion(r: unknown): Champion | undefined {
  if (!r || typeof r !== "object") return undefined;
  const o = r as Record<string, unknown>;
  if (!isStr(o.bidId) || !isStr(o.sellerId) || !isStr(o.persona) || !isNum(o.landed)) return undefined;
  return { bidId: o.bidId, sellerId: o.sellerId, persona: o.persona, landed: o.landed, origin: isStr(o.origin) ? o.origin : "SIM", sourceUrl: isStr(o.sourceUrl) ? o.sourceUrl : "" };
}

function parsePart(r: unknown): BuildPart | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  if (!isPart(o.part) || !isStr(o.label) || !isStr(o.status) || !isNum(o.budget)) return null;
  const status = o.status as PartStatus;
  return {
    part: o.part, label: o.label, status, budget: o.budget,
    needId: isStr(o.needId) ? o.needId : undefined,
    roundId: isStr(o.roundId) ? o.roundId : undefined,
    champion: parseChampion(o.champion),
    reason: isStr(o.reason) ? o.reason : undefined,
  };
}

function parseCheck(r: unknown): BuildCheck | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  if (!isPart(o.a) || !isPart(o.b) || !isStr(o.rule) || !isStr(o.state) || !isStr(o.detail) || !isStr(o.source)) return null;
  return { a: o.a, b: o.b, rule: o.rule as CheckRule, state: o.state as CheckState, detail: o.detail, source: o.source };
}

function parseEvent(r: unknown): BuildEvent | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  if (!isStr(o.at) || !isStr(o.kind) || !isStr(o.text) || !Array.isArray(o.parts) || !o.parts.every(isPart)) return null;
  return { at: o.at, kind: o.kind as EventKind, text: o.text, parts: o.parts };
}

function parseApproval(r: unknown): BuildApproval {
  const fallback: BuildApproval = { state: "waiting", total: 0, sellers: 0, mandates: [] };
  if (!r || typeof r !== "object") return fallback;
  const o = r as Record<string, unknown>;
  const mandates = Array.isArray(o.mandates)
    ? o.mandates.flatMap((m) => {
        if (!m || typeof m !== "object") return [];
        const mo = m as Record<string, unknown>;
        return isStr(mo.sellerId) && isNum(mo.amount) && isStr(mo.mandateHash) ? [{ sellerId: mo.sellerId, amount: mo.amount, mandateHash: mo.mandateHash }] : [];
      })
    : [];
  return { state: isStr(o.state) ? (o.state as ApprovalState) : "waiting", total: isNum(o.total) ? o.total : 0, sellers: isNum(o.sellers) ? o.sellers : 0, mandates };
}

export function parseBuildView(r: unknown): BuildView | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  if (!isStr(o.goalId) || !isStr(o.buyerId) || !isNum(o.budget) || !isNum(o.spent) || !Array.isArray(o.parts)) return null;
  const parts = o.parts.map(parsePart).filter((p): p is BuildPart => p !== null);
  if (!parts.length) return null;
  const checks = Array.isArray(o.checks) ? o.checks.map(parseCheck).filter((c): c is BuildCheck => c !== null) : [];
  const events = Array.isArray(o.events) ? o.events.map(parseEvent).filter((e): e is BuildEvent => e !== null) : [];
  return { goalId: o.goalId, buyerId: o.buyerId, budget: o.budget, spent: o.spent, origin: isStr(o.origin) ? o.origin : "SIM", parts, checks, events, approval: parseApproval(o.approval) };
}

export async function fetchBuildView(signal?: AbortSignal): Promise<BuildView | null> {
  try {
    const res = await fetch(BUILD_BOARD_URL, { signal, cache: "no-store" });
    if (!res.ok) return null;
    return parseBuildView(await res.json());
  } catch {
    return null;
  }
}

export function checksFor(part: Part, checks: BuildCheck[]): BuildCheck[] {
  return checks.filter((c) => c.a === part || c.b === part);
}

export function otherPart(check: BuildCheck, part: Part): Part {
  return check.a === part ? check.b : check.a;
}
