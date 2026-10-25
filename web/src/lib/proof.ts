// Sponsor proof on a locked part of the build panel (judge fix 3): did Bright Data re-read this part's price in this run, and what do
// Tiger Data's 7 and 30 day prices say. Pure text from the feed's fields; nothing here fetches or invents a number.
// Honesty rules (decisions: LIVE only for a value fetched in this run): "checked Ns ago" needs a LIVE label AND a time; anything else
// says the price was not re-read and why. Tiger rows are stored, so they are never LIVE.

import { formatMoney } from "./money.ts";
import type { BuildResult } from "./build.ts";

export type ProofOrigin = "LIVE" | "MIRROR" | "SIM";
export const LIVE_CHECK_STATES = ["ok", "price_changed", "out_of_stock", "stock_unknown", "slow", "empty", "not_configured", "skipped"] as const;
export const HISTORY_STATES = ["ok", "no_data", "not_configured", "error"] as const;

/** What the agent feed serves of the Bright Data re-check: whether it read a price, when and from where. Never the price it read. */
export interface LiveCheck { state: (typeof LIVE_CHECK_STATES)[number]; origin: ProofOrigin; source: string; fetchedAt?: string }
export interface HistoryWindow { days: number; low: number; median: number; n: number; daysOfData: number }
/** Tiger Data's read for one part: market prices of its SKU, low and median per window. */
export interface PriceHistory { state: (typeof HISTORY_STATES)[number]; origin: ProofOrigin; windows: HistoryWindow[] }
export interface PartProof { championOrigin: ProofOrigin; liveCheck?: LiveCheck; history?: PriceHistory }
export interface ProofLine { text: string; origin: ProofOrigin; /** true only when a real read backs the line */ read: boolean }

/** "12 s ago" under two minutes, then "3 min ago", then "2 h ago". A negative age (clock skew) reads 0 s. */
export function agoText(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return s < 120 ? `${s} s ago` : s < 7200 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
}

const NOT_READ_WHY: Record<string, string> = {
  slow: "Bright Data was too slow",
  not_configured: "Bright Data is not set up on this run",
  skipped: "the re-check was off",
};

/** The Bright Data line. `championOrigin` only matters when there is no liveCheck: a SIM seller has no listing to re-read. */
export function brightDataLine(lc: LiveCheck | undefined, championOrigin: ProofOrigin, nowMs: number): ProofLine {
  if (!lc) {
    return championOrigin === "SIM"
      ? { text: "SIM seller: no real listing to re-read", origin: "SIM", read: false }
      : { text: "price not re-read (the re-check did not run)", origin: "MIRROR", read: false };
  }
  if (lc.origin === "LIVE" && lc.fetchedAt) {
    const at = Date.parse(lc.fetchedAt);
    const text = Number.isNaN(at) ? "Bright Data checked this price (time unknown)" : `Bright Data checked ${agoText((nowMs - at) / 1000)}`;
    return { text, origin: "LIVE", read: true };
  }
  return { text: `price not re-read (${NOT_READ_WHY[lc.state] ?? "Bright Data returned nothing"})`, origin: "MIRROR", read: false };
}

const windowText = (days: number, w: HistoryWindow | undefined) =>
  !w ? `${days}-day no history yet`
    : `${days}-day low ${formatMoney(w.low)} and median ${formatMoney(w.median)}` + (w.daysOfData < days ? ` (only ${w.daysOfData} day${w.daysOfData === 1 ? "" : "s"} of data)` : "");

/** The Tiger Data line: both windows when it has them, an honest "no history" otherwise. Never LIVE. */
export function tigerLine(h: PriceHistory | undefined): ProofLine {
  if (!h) return { text: "Tiger Data: no 7-day or 30-day history read yet", origin: "SIM", read: false };
  if (h.state === "ok" && h.windows.length) {
    const by = (d: number) => h.windows.find((w) => w.days === d);
    return { text: `Tiger Data: ${windowText(7, by(7))}; ${windowText(30, by(30))}`, origin: h.origin === "SIM" ? "SIM" : "MIRROR", read: true };
  }
  const text = h.state === "not_configured" ? "Tiger Data: no 7-day or 30-day history (not connected on this run)"
    : h.state === "error" ? "Tiger Data: no 7-day or 30-day history (the read failed)"
    : "Tiger Data: no 7-day or 30-day history yet for this part";   // no_data, or an "ok" with no usable window
  return { text, origin: "SIM", read: false };
}

/** Both lines for one panel part key, or null when the part has no champion (nothing to prove yet). */
export function proofFor(b: BuildResult, part: string, nowMs: number): { bright: ProofLine; tiger: ProofLine } | null {
  const p = b.proof?.[part];
  return p ? { bright: brightDataLine(p.liveCheck, p.championOrigin, nowMs), tiger: tigerLine(p.history) } : null;
}
