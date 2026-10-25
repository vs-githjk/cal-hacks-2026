// The agent wire: which line of the diagram a real agent_event row lights. Pure, so "moves only when a row lands" is tested.
import { AGENTS, type AgentInfo } from "./agents.ts";

export type EdgeId = "sellers-shield" | "shield-buyer" | "buyer-advocate";

const BY_KEY: Record<AgentInfo["key"], EdgeId> = {
  shield: "shield-buyer",
  buyer: "buyer-advocate",
  advocate: "buyer-advocate",
  seller1: "sellers-shield",
  seller2: "sellers-shield",
  seller3: "sellers-shield",
};

// Names the AGENTS registry lacks: demo/bridge.py AGENT_NAMES (the buyer agent is already registered).
const ALIASES: Record<string, EdgeId> = { "bazaar advocate": "buyer-advocate", "bazaar shield": "shield-buyer", "smell test": "shield-buyer" };

const EDGE_BY_NAME = new Map<string, EdgeId>([
  ...AGENTS.map((a): [string, EdgeId] => [a.name.toLowerCase(), BY_KEY[a.key]]),
  ...Object.entries(ALIASES),
]);

/** The edge for a registered agent or demo bridge name (exact, case-insensitive). Any other name, or an empty one, lights nothing. */
export function edgeForAgent(agentName: string): EdgeId | null {
  return EDGE_BY_NAME.get(agentName.trim().toLowerCase()) ?? null;
}

interface EventLike {
  id: bigint;
  agentName: string;
}

/**
 * Rows newer than the high-water mark, oldest first. Until the table is ready nothing is recorded (a partial load is never a mark).
 * The first ready call (seen null) only records the mark, 0n for an empty table: history never replays.
 */
export function advance<R extends EventLike>(seen: bigint | null, rows: readonly R[], ready: boolean): { seen: bigint | null; fresh: R[] } {
  if (!ready) return { seen, fresh: [] };
  const top = rows.reduce<bigint>((m, r) => (r.id > m ? r.id : m), seen ?? 0n);
  if (seen === null) return { seen: top, fresh: [] };
  return { seen: top, fresh: rows.filter((r) => r.id > seen).sort((a, b) => (a.id < b.id ? -1 : 1)) };
}
