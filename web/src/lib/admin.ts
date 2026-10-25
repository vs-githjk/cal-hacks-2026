// Client of the public telemetry view (#374). Whitelist parser: only the named count fields are ever copied,
// so a money, price, phone or name field added to the view later never reaches the screen.

export const TELEMETRY_FIELDS = [
  "accounts_created", "goals_posted", "rounds_opened", "rounds_closed", "bids", "shield_catches",
  "calls_placed", "approvals", "denials", "errors", "round_p50_ms", "round_p95_ms",
] as const;
export type TelemetryField = (typeof TELEMETRY_FIELDS)[number];
export type Telemetry = Record<TelemetryField, number>;
export interface AgentEvents { agent: string; events: number }

export const ADMIN_ROLES = ["owner", "referee"];
export const canSeeAdmin = (roles: readonly { role: string }[]): boolean => roles.some((r) => ADMIN_ROLES.includes(r.role));

const camel = (s: string) => s.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());

function count(v: unknown): number | null {
  if (typeof v === "bigint") return v >= 0n ? Number(v) : null;
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null;
}

export function parseTelemetry(row: unknown): Telemetry | null {
  if (!row || typeof row !== "object") return null;
  const src = row as Record<string, unknown>;
  const out = {} as Telemetry;
  for (const f of TELEMETRY_FIELDS) {
    const n = count(f in src ? src[f] : src[camel(f)]);
    if (n === null) return null;
    out[f] = n;
  }
  return out;
}

export function parseAgentEvents(rows: unknown): AgentEvents[] {
  if (!Array.isArray(rows)) return [];
  const out: AgentEvents[] = [];
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    const { agent, events } = r as Record<string, unknown>;
    const n = count(events);
    if (typeof agent === "string" && n !== null) out.push({ agent, events: n });
  }
  return out.sort((a, b) => b.events - a.events);
}

// Stub rows until the market publishes the real telemetry / telemetry_agent views.
export const SIM_TELEMETRY: Telemetry = {
  accounts_created: 6, goals_posted: 4, rounds_opened: 5, rounds_closed: 4, bids: 17, shield_catches: 3,
  calls_placed: 9, approvals: 2, denials: 1, errors: 0, round_p50_ms: 42000, round_p95_ms: 71000,
};
export const SIM_AGENT_EVENTS = [
  { agent: "buyer", events: 31 }, { agent: "hunt", events: 22 }, { agent: "shield", events: 14 },
  { agent: "seller_fair_price_pc", events: 12 }, { agent: "seller_rig_depot", events: 9 },
];
