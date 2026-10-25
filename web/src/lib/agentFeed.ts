// Client side of the agent feed (scripts/agent_feed.py, :8790). Pure helpers plus one fetch; nothing here invents a row.

import { safeUrl } from "./url.ts";

export type AgentStatus = "agentverse" | "local" | "down";

export interface AgentRow {
  name: string;
  role: string;
  address: string | null;
  status: AgentStatus;
  last_message: string | null;
  at: string | null;
  origin: string;
  /** A real web address for the agent's picture, when the feed sends one (it does not yet); null shows a placeholder. */
  avatar: string | null;
}

const LOCAL_FEED = "http://127.0.0.1:8790";
const LOOPBACK = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\])$/;

/** The feed to poll, or null to skip it: unset on a deployed page, unparseable, or a loopback feed seen from a page that is not itself on loopback
 * (a judge's browser would hit its own machine and fail CORS). Null shows the Agentverse profile links instead of "offline". */
export function feedBase(url: string | undefined, pageHost: string): string | null {
  if (!url) return LOOPBACK.test(pageHost) ? LOCAL_FEED : null;
  try {
    const u = new URL(url);
    if (LOOPBACK.test(u.hostname) && !LOOPBACK.test(pageHost)) return null;
    return url.replace(/\/+$/, "");
  } catch {
    return null;
  }
}

export const FEED_ENV = process.env.NEXT_PUBLIC_AGENT_FEED_URL;
/** The memory panel still reads this operator feed directly; it falls back to the local launcher. */
export const FEED_URL = FEED_ENV ?? LOCAL_FEED;
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
      avatar: typeof o.avatar === "string" ? safeUrl(o.avatar) : null,
    });
  }
  return rows;
}

/** null means the feed could not be reached or answered something else: the tile says "agents offline". */
export async function fetchAgents(base: string, signal?: AbortSignal): Promise<AgentRow[] | null> {
  try {
    const res = await fetch(`${base}/v1/agents`, { signal, cache: "no-store" });
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

// What the launcher's run log says about each agent (scripts/agent_feed.py), not a live check from this page: a mailbox
// loop that started, a process that runs without one, or neither. An address or a published profile alone proves nothing.
export const STATUS_TEXT: Record<AgentStatus, string> = { agentverse: "Mailbox running", local: "Running locally", down: "Not running" };

export function summary(rows: readonly AgentRow[]): string {
  const up = rows.filter((r) => r.status !== "down");
  const mailboxes = rows.filter((r) => r.status === "agentverse").length;
  if (rows.length === 0) return "No agents running";
  if (up.length === 0) return `${rows.length} ${rows.length === 1 ? "agent" : "agents"}, none running`;
  return `${up.length} of ${rows.length} running, ${mailboxes === 0 ? "local only" : `${mailboxes} with an Agentverse mailbox`}`;
}

/** Milliseconds for a real ISO time ("2026-10-24T11:59:00+00:00"); null for anything else, so "1" or "garbage" never read as a date. */
function isoMs(at: string | null): number | null {
  if (!at || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(at)) return null;
  const t = Date.parse(at);
  return Number.isNaN(t) ? null : t;
}

/** The row with the newest valid recorded time that has something to show. Chosen by time, never by array position; the first row wins a tie. */
export function latestActivity(rows: readonly AgentRow[]): AgentRow | null {
  let best: AgentRow | null = null;
  let bestAt = -Infinity;
  for (const r of rows) {
    const t = isoMs(r.at);
    if (t !== null && r.last_message?.trim() && t > bestAt) {
      best = r;
      bestAt = t;
    }
  }
  return best;
}

/** Ten minutes: the launcher stamps a time only when an agent speaks, so older than this is no longer "current". */
export const STALE_MS = 10 * 60 * 1000;

/** True when the time is unreadable or older than maxAgeMs. A time a little in the future (clock skew) is not stale. */
export function isStale(at: string | null, now: number, maxAgeMs = STALE_MS): boolean {
  const t = isoMs(at);
  return t === null || now - t > maxAgeMs;
}

/** The tile's one line: undefined while the first poll is pending, null when the feed is offline. */
export function headline(rows: readonly AgentRow[] | null | undefined, now: number): string {
  if (rows === undefined) return "Checking agents";
  if (rows === null) return "Agents offline";
  const latest = latestActivity(rows);
  if (!latest) return rows.length === 0 ? summary(rows) : `${summary(rows)}. No timestamped activity.`;
  return `${latest.name}, ${ago(latest.at, now)}${isStale(latest.at, now) ? " (stale)" : ""}`;
}

const AGENT_ADDRESS = /^agent1[a-z0-9]{20,100}$/;

/** The Agentverse profile link for an agent whose mailbox is running and whose address is well formed; otherwise no link. */
export function agentLink(r: AgentRow): string | null {
  return r.status === "agentverse" && r.address && AGENT_ADDRESS.test(r.address) ? agentverseUrl(r.address) : null;
}

export function agentverseUrl(address: string): string {
  return `https://agentverse.ai/agents/details/${encodeURIComponent(address)}/profile`;
}

/** "4s ago" from the row's timestamp; empty when the feed gave none or it is not a real time. */
export function ago(at: string | null, now: number): string {
  const t = isoMs(at);
  if (t === null) return "";
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
