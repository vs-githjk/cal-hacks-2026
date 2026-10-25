// web/src/lib/arenaAgents.ts
// Which real Fetch.ai agent stands behind an actor in the arena, and what its newest agent_event row says.
// Matching is always exact: the key for the fixed characters, the sellerId for an offer, the address for a row. Never by name or timing.
import { AGENTS, type AgentInfo } from "./agents.ts";
import type { ActorKey, ArenaScene } from "./arenaScene.ts";

type Ts = { microsSinceUnixEpoch: bigint };
export interface AgentEventLike { id?: bigint; address: string; text: string; ts: Ts }

export const BUBBLE_MS = 8000;
export const BUBBLE_MAX = 90;

const SELLER_ID = /^seller_([1-9]\d*)$/;
const byKey = (key: string) => AGENTS.find((a) => a.key === key) ?? null;

/** The agent for an actor, or null: seller_N is the AGENTS key sellerN (seller_4 and seller_5 have none yet). */
export function agentFor(key: ActorKey, scene: ArenaScene): AgentInfo | null {
  if (key === "buyer" || key === "advocate" || key === "shield") return byKey(key);
  const offer = scene.offers.find((o) => o.key === key);
  const n = offer ? SELLER_ID.exec(offer.sellerId)?.[1] : undefined;
  return n ? byKey(`seller${n}`) : null;
}

const DASHES = new RegExp("\\s*[" + String.fromCharCode(0x2012) + "-" + String.fromCharCode(0x2015) + "]\\s*", "g");

/** Plain one-line text: trimmed, em and en dashes turned into commas, at most 90 characters. */
export function bubbleText(text: string): string {
  const t = text.replace(DASHES, ", ").trim();
  return t.length > BUBBLE_MAX ? `${t.slice(0, BUBBLE_MAX - 1)}…` : t;
}

/** Each actor's newest agent_event row from the last 8 seconds, by exact address. `now` is milliseconds. */
export function bubblesFrom(rows: readonly AgentEventLike[], now: number, scene: ArenaScene): Partial<Record<string, string>> {
  const actorOf = new Map<string, string>();
  for (const a of AGENTS) {
    const key = ["buyer", "advocate", "shield"].includes(a.key) ? a.key : scene.offers.find((o) => agentFor(o.key, scene)?.key === a.key)?.key;
    if (key) actorOf.set(a.address, key);
  }
  const newest = new Map<string, { at: bigint; id: bigint; text: string }>();
  for (const r of rows) {
    const actor = actorOf.get(r.address);
    const text = bubbleText(r.text);
    if (!actor || !text) continue;
    const age = now - Number(r.ts.microsSinceUnixEpoch / 1000n);
    if (age > BUBBLE_MS) continue;
    const cur = newest.get(actor);
    const id = r.id ?? 0n;
    if (!cur || r.ts.microsSinceUnixEpoch > cur.at || (r.ts.microsSinceUnixEpoch === cur.at && id > cur.id)) newest.set(actor, { at: r.ts.microsSinceUnixEpoch, id, text });
  }
  return Object.fromEntries([...newest].map(([k, v]) => [k, v.text]));
}
