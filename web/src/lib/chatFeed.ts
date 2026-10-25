// The ASI:One chat for the /floor video call. Pure helpers: parse the agent feed, mask digits, derive SIM lines from the floor script.
// Nothing here invents a row for a live feed; SIM lines come only from the script the floor is already playing.
import type { FloorScript } from "../components/floor/floorPhases.ts";

export type ChatKind = "message" | "thinking" | "done";
export interface ChatLine { id: string; at: string; who: string; name: string; text: string; kind: ChatKind; sim: boolean }

const MASK = "••••";
// 6 or more digits in a row, allowing single spaces or dashes between digits ("482 913", "415-555-1234", "pi_3Nx...123456").
// A price ("$1,299.99", "1,329.00") has at most 4 digits per run, so a comma does not join runs.
const DIGIT_RUN = /\d(?:[ \-]?\d){5,}/g;

/** Any run of 6+ digits (single spaces or dashes allowed between them) becomes "••••". Prices and model numbers stay. */
export function maskDigits(text: string): string {
  return text.replace(DIGIT_RUN, MASK);
}

const KINDS: readonly string[] = ["message", "thinking", "done"];

/** Tolerant parse of `GET /chat`: keeps rows that have a string text and who, masks the text, gives each a stable id. */
export function parseChat(json: unknown, sim: boolean): ChatLine[] {
  if (!Array.isArray(json)) return [];
  const out: ChatLine[] = [];
  json.forEach((r, index) => {
    if (!r || typeof r !== "object") return;
    const o = r as Record<string, unknown>;
    if (typeof o.text !== "string" || !o.text.trim() || typeof o.who !== "string" || !o.who) return;
    const at = typeof o.at === "string" ? o.at : "";
    out.push({
      id: `${at}|${o.who}|${index}`,
      at,
      who: o.who,
      name: typeof o.name === "string" && o.name ? o.name : o.who,
      text: maskDigits(o.text),
      kind: typeof o.kind === "string" && KINDS.includes(o.kind) ? (o.kind as ChatKind) : "message",
      sim,
    });
  });
  return out;
}

const EPOCH = Date.UTC(2026, 0, 1);
const iso = (s: number) => new Date(EPOCH + Math.round(s * 1000)).toISOString();
const OWNER_GOAL = "RTX 5070 Ti under $1,400 by Friday";
const BUYER_NAME = "Fish Market Buyer";
const THINK_DWELL = 0.8; // seconds the dots show before the thinking agent's line lands (at most half the hold)

function pipWho(text: string): { who: string; name: string } {
  if (/^Shield\b/.test(text)) return { who: "shield", name: "Shield" };
  if (/^Winner\b/.test(text)) return { who: "referee", name: "Referee" };
  return { who: "buyer", name: BUYER_NAME };
}

/** SIM chat from the floor script up to `seconds`: each new pip message, and each think beat as a "thinking" line then its message once the dots have shown. */
export function chatFromScript(script: FloorScript, seconds: number): ChatLine[] {
  const out: ChatLine[] = [];
  const seen = new Set<string>();
  const push = (at: number, who: string, name: string, text: string, kind: ChatKind) => {
    const a = iso(at);
    out.push({ id: `${a}|${who}|${out.length}`, at: a, who, name, text: maskDigits(text), kind, sim: true });
  };
  const ps = script.phases;
  ps.forEach((p, i) => {
    if (!(p.at <= seconds)) return;
    for (const m of p.pip) {
      if (seen.has(m)) continue;
      seen.add(m);
      if (m === OWNER_GOAL) push(p.at, "owner", "You", m, "message");
      else { const w = pipWho(m); push(p.at, w.who, w.name, m, "message"); }
    }
    if (p.think) {
      const end = i + 1 < ps.length ? ps[i + 1]!.at : script.duration;
      const dwell = Math.min(THINK_DWELL, Math.max(end - p.at, 0) / 2);
      push(p.at, p.think.who, p.think.name, "Thinking", "thinking");
      if (p.at + dwell <= seconds) push(p.at + dwell, p.think.who, p.think.name, p.think.text, "message");
    }
  });
  return out;
}

/** True when the last line from `who` is a thinking line, so the dots show until that agent speaks again. */
export function isThinking(lines: ChatLine[], who: string): boolean {
  for (let i = lines.length - 1; i >= 0; i--) if (lines[i]!.who === who) return lines[i]!.kind === "thinking";
  return false;
}
