// The six Fetch.ai agents, from agents/README.md. Names and Agentverse addresses are public (no seeds, no keys).
import type { Origin } from "./screens";

export interface AgentInfo {
  key: "buyer" | "advocate" | "shield" | "seller1" | "seller2" | "seller3";
  name: string;
  handle: string;
  address: string;
}

export const AGENTS: AgentInfo[] = [
  { key: "buyer", name: "Fish Market Buyer", handle: "@techbazaarbuyer", address: "agent1qwxhy93uzmw5prlqldm8a2mz9gsmc2563um6th2l6z0pudw63juej97nmj8" },
  { key: "advocate", name: "Fish Market Quality Advocate", handle: "@techbazaaradvocate", address: "agent1qvxvlletez0ywdcq7da76ufzz4lvh5xvtd4fxam22g6phqzr07kvjcmhv05" },
  { key: "shield", name: "Shield Client", handle: "@techbazaarshield", address: "agent1q0m2z43cf3hg4cfy87hatf69ulyqkvuylm6mjv53e6y05weqmhjj6k4lknp" },
  { key: "seller1", name: "Byte Bros Outlet", handle: "@techbazaarseller1", address: "agent1qd3gvg54tsaezed0wzpgg34rza4y6kvvfd778nj6h27j20k99d38zd3et9m" },
  { key: "seller2", name: "Silicon Sally's Surplus", handle: "@techbazaarseller2", address: "agent1qw9dvuwgnh570wyk8uukp0w48a03tdpmtuv8csm3qxy6t3udl3ahs2264np" },
  { key: "seller3", name: "FlashDeal Frankie", handle: "@techbazaarseller3", address: "agent1qdcrmqy2ra2tvshq2qhc8q5rvqzpr7du77st32qynwazy48gtuvyspdm26l" },
];

export const ASI_ONE_URL = "https://asi1.ai/";
export const AGENTVERSE_URL = (address: string) => `https://agentverse.ai/agents/details/${address}/profile`;

/** agent1qwxhy93…nmj8: first 7 characters, an ellipsis, last 4. */
export const shortAddress = (a: string) => (a.length > 11 ? `${a.slice(0, 7)}…${a.slice(-4)}` : a);

export interface AgentRow {
  agent: AgentInfo;
  text: string;
  at: Date | null;
  origin: Origin;
}

/** Shown only while the agent_event table is empty. Every row is SIM; the text describes the role, it is not a message an agent sent. */
export function sampleRows(now: Date): AgentRow[] {
  const ago = (s: number) => new Date(now.getTime() - s * 1000);
  const text: Record<AgentInfo["key"], string> = {
    buyer: "Goal set: RTX 5070 Ti under $1,300 by Friday. Round open.",
    advocate: "Veto: listed new, page says open box. Source attached.",
    shield: "Blocked a hidden instruction in one listing.",
    seller1: "Sealed bid sent.",
    seller2: "Sealed bid sent, two condition lines.",
    seller3: "Sealed bid sent.",
  };
  const secs: Record<AgentInfo["key"], number> = { buyer: 42, advocate: 30, shield: 31, seller1: 38, seller2: 36, seller3: 35 };
  return AGENTS.map((agent) => ({ agent, text: text[agent.key], at: ago(secs[agent.key]), origin: "SIM" }));
}

/** "12 s ago", "3 min ago", "2 h ago". */
export function timeAgo(at: Date | null, now: Date): string {
  if (!at) return "";
  const s = Math.max(0, Math.round((now.getTime() - at.getTime()) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  return `${Math.floor(s / 3600)} h ago`;
}

export type Corner = "tl" | "tr" | "bl" | "br";
/** The corner nearest a point in a viewport of w x h. */
export const nearestCorner = (x: number, y: number, w: number, h: number): Corner => `${y < h / 2 ? "t" : "b"}${x < w / 2 ? "l" : "r"}` as Corner;

export interface Box { left: number; top: number; right: number; bottom: number }

// Where a corner puts the tile: 16 px from the sides, below the 60 px header (76), above the footer (48).
const SIDE = 16, TOP = 76, BOTTOM = 48;

export function cornerRect(c: Corner, tile: { w: number; h: number }, view: { w: number; h: number }): Box {
  const left = c[1] === "l" ? SIDE : view.w - SIDE - tile.w;
  const top = c[0] === "t" ? TOP : view.h - BOTTOM - tile.h;
  return { left, top, right: left + tile.w, bottom: top + tile.h };
}

const hits = (a: Box, b: Box) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

/**
 * The corner to use so the tile never covers the hero number: the current one if it is clear, else the first clear one
 * (same side first). If none is clear, keep the current one. Pure, so a second call returns the same answer: no flip loop.
 */
export function clearCorner(current: Corner, tile: { w: number; h: number }, view: { w: number; h: number }, hero: Box | null): Corner {
  if (!hero || !hits(cornerRect(current, tile, view), hero)) return current;
  const flipRow = ((current[0] === "t" ? "b" : "t") + current[1]) as Corner;
  const flipCol = (current[0] + (current[1] === "l" ? "r" : "l")) as Corner;
  const opposite = ((current[0] === "t" ? "b" : "t") + (current[1] === "l" ? "r" : "l")) as Corner;
  return [flipRow, flipCol, opposite].find((c) => !hits(cornerRect(c, tile, view), hero)) ?? current;
}
