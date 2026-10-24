// Client side of the agent feed (scripts/agent_feed.py, :8790). Pure helpers plus one fetch; nothing here invents a row.

export type AgentStatus = "agentverse" | "local" | "down";

export interface AgentRow {
  name: string;
  role: string;
  address: string | null;
  status: AgentStatus;
  last_message: string | null;
  at: string | null;
  origin: string;
}

export const FEED_URL = process.env.NEXT_PUBLIC_AGENT_FEED_URL ?? "http://127.0.0.1:8790";
export const ASI_ONE_URL = "https://asi1.ai/";
export const POLL_MS = 2000;

const STATUSES: readonly string[] = ["agentverse", "local", "down"];

/** Keep only well formed rows. Anything else in the payload is dropped, so a bad feed shows fewer rows, never made up ones. */
export function parseAgents(json: unknown): AgentRow[] | null {
  if (!Array.isArray(json)) return null;
  const rows: AgentRow[] = [];
  for (const r of json) {
    if (!r || typeof r !== "object") continue;
    const o = r as Record<string, unknown>;
    if (typeof o.name !== "string" || typeof o.role !== "string" || typeof o.status !== "string" || !STATUSES.includes(o.status)) continue;
    rows.push({
      name: o.name,
      role: o.role,
      address: typeof o.address === "string" ? o.address : null,
      status: o.status as AgentStatus,
      last_message: typeof o.last_message === "string" ? o.last_message : null,
      at: typeof o.at === "string" ? o.at : null,
      origin: typeof o.origin === "string" ? o.origin : "SIM",
    });
  }
  return rows;
}

/** null means the feed could not be reached or answered something else: the tile says "agents offline". */
export async function fetchAgents(signal?: AbortSignal): Promise<AgentRow[] | null> {
  try {
    const res = await fetch(`${FEED_URL}/v1/agents`, { signal, cache: "no-store" });
    if (!res.ok) return null;
    return parseAgents(await res.json());
  } catch {
    return null;
  }
}

/** Rows that say something real: the feed lists the three default roles as bare "down" rows when nothing has ever started. */
export function realRows(rows: readonly AgentRow[]): AgentRow[] {
  return rows.filter((r) => r.status !== "down" || r.address !== null || r.last_message !== null);
}

export const STATUS_TEXT: Record<AgentStatus, string> = { agentverse: "On Agentverse", local: "Local only", down: "Down" };

export function summary(rows: readonly AgentRow[]): string {
  const up = rows.filter((r) => r.status !== "down");
  const av = rows.filter((r) => r.status === "agentverse").length;
  if (rows.length === 0) return "No agents running";
  if (up.length === 0) return `${rows.length} agents, all down`;
  return `${up.length} of ${rows.length} up, ${av === 0 ? "local only" : `${av} on Agentverse`}`;
}

export function agentverseUrl(address: string): string {
  return `https://agentverse.ai/agents/details/${encodeURIComponent(address)}/profile`;
}

/** "4s ago" from the row's timestamp; empty when the feed gave none. */
export function ago(at: string | null, now: number): string {
  if (!at) return "";
  const t = Date.parse(at);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export type Corner = "br" | "bl" | "tr" | "tl";

/** The corner nearest the tile's centre after a drag. */
export function nearestCorner(cx: number, cy: number, vw: number, vh: number): Corner {
  return `${cy < vh / 2 ? "t" : "b"}${cx < vw / 2 ? "l" : "r"}` as Corner;
}

export const NEXT_CORNER: Record<Corner, Corner> = { br: "bl", bl: "tl", tl: "tr", tr: "br" };
