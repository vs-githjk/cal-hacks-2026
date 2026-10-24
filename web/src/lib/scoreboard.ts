// Scoreboard tiles (contracts/Scoreboard.schema.json, data/scoreboard.json from Lane C). Every number is the file's own;
// a tile whose value is null shows its status text, never a number.
import { formatMoney } from "./money.ts";
import { asOrigin, type Origin } from "./screens.ts";

/** The four tiles the home page shows, in this order. Other ids in the file (voice_attacks, hyphenate_blind) are not tiles here. */
export const SCOREBOARD_IDS = ["verified_savings", "attacks_blocked", "fit_accuracy", "learning_lift"] as const;

const STATUS_TEXT: Record<string, string> = { measured: "Measured", not_quotable: "Not quotable", none_yet: "None yet" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export interface TileView {
  id: string;
  title: string;
  value: string | null; // formatted; null when the file has no trustworthy number
  statusText: string | null; // shown instead of the value when value is null
  display: string;
  count: number;
  range: string;
  origin: Origin;
}

interface RawTile { id: string; title: string; status: string; value: number | null; unit: string; display: string; count: number; date_range: { from: string; to: string }; origin: string }

const day = (iso: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}` : iso;
};

function formatValue(v: number, unit: string): string {
  if (unit === "ratio") return `${Math.round(v * 100)}%`;
  if (unit === "USD") return formatMoney(v);
  if (unit === "points") return `${v > 0 ? "+" : ""}${v.toFixed(2)} pts`;
  return `${v} ${unit}`;
}

export function scoreboardTiles(file: unknown): TileView[] {
  const tiles = (file as { tiles?: unknown } | null)?.tiles;
  if (!Array.isArray(tiles)) return [];
  return SCOREBOARD_IDS.flatMap((id) => {
    const t = (tiles as RawTile[]).find((x) => x?.id === id);
    if (!t) return [];
    const has = typeof t.value === "number" && Number.isFinite(t.value);
    const from = day(t.date_range?.from ?? ""), to = day(t.date_range?.to ?? "");
    return [{
      id, title: t.title, value: has ? formatValue(t.value!, t.unit) : null, statusText: has ? null : STATUS_TEXT[t.status] ?? "No number",
      display: t.display, count: t.count, range: from === to ? from : `${from} to ${to}`, origin: asOrigin(t.origin),
    }];
  });
}
