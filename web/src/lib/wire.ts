// The agent wire: which line of the diagram a real agent_event row lights. Pure, so "moves only when a row lands" is tested.

export type EdgeId = "sellers-shield" | "shield-buyer" | "buyer-advocate";

/** The edge for an agent by the role its name states. Any other named agent is a seller; an empty name lights nothing. */
export function edgeForAgent(agentName: string): EdgeId | null {
  const n = agentName.trim().toLowerCase();
  if (!n) return null;
  if (n.includes("shield")) return "shield-buyer";
  if (n.includes("buyer") || n.includes("advocate")) return "buyer-advocate";
  return "sellers-shield";
}

interface EventLike {
  id: bigint;
  agentName: string;
}

/** Rows newer than the high-water mark, oldest first. The first call (seen null) only records the mark: history never replays. */
export function advance<R extends EventLike>(seen: bigint | null, rows: readonly R[]): { seen: bigint | null; fresh: R[] } {
  const top = rows.reduce<bigint | null>((m, r) => (m === null || r.id > m ? r.id : m), seen);
  if (seen === null) return { seen: top, fresh: [] };
  return { seen: top, fresh: rows.filter((r) => r.id > seen).sort((a, b) => (a.id < b.id ? -1 : 1)) };
}
