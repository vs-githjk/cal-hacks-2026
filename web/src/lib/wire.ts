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

// Names the AGENTS registry lacks, each mapped to the registered agent it is: demo/bridge.py AGENT_NAMES, and the names the
// agents carried before the Fish Market rename (#438, #448), which the bridge still emits.
const ALIASES: Record<string, AgentInfo["key"]> = {
  "tech bazaar buyer": "buyer",
  "bazaar advocate": "advocate",
  "quality advocate": "advocate",
  "tech bazaar quality advocate": "advocate",
  "bazaar shield": "shield",
  "shield client": "shield",
  "tech bazaar shield client": "shield",
  "smell test": "shield",
  "smell test client": "shield",
};

const KEY_BY_NAME = new Map<string, AgentInfo["key"]>([
  ...AGENTS.map((a): [string, AgentInfo["key"]] => [a.name.toLowerCase(), a.key]),
  ...Object.entries(ALIASES),
]);

const norm = (name: string) => name.trim().toLowerCase();

/** The edge for a registered agent, a demo bridge name or a pre-rename name (exact, case-insensitive). Any other name, or an empty one, lights nothing. */
export function edgeForAgent(agentName: string): EdgeId | null {
  const key = KEY_BY_NAME.get(norm(agentName));
  return key ? BY_KEY[key] : null;
}

/** The name to show for an agent_event row: the registry's current name when the row's name is one of ours (or an old one), else the raw name. */
export function displayNameFor(agentName: string): string {
  const key = KEY_BY_NAME.get(norm(agentName));
  return key ? AGENTS.find((a) => a.key === key)!.name : agentName;
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
