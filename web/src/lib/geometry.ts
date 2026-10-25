// Drawing math for the dashboard: pure, so what is drawn to scale is tested.

/** The allowance as a share of the goal cap (0 to 100). null when either number cannot be trusted. */
export function callLine(allowance: number, cap: number): { autoPct: number } | null {
  if (!Number.isFinite(allowance) || !Number.isFinite(cap) || allowance < 0 || cap <= 0) return null;
  return { autoPct: Math.min(100, (allowance / cap) * 100) };
}

/** How far a bid is past the allowance, where the agent calls first. */
export function overAllowance(bid: number, allowance: number): number {
  return Math.max(0, bid - allowance);
}

export interface RulerInput {
  label: string;
  mm: number;
}

export interface RulerLayout {
  min: number;
  max: number;
  /** Where the limit sits on the axis, in percent. The same number for every row. */
  limitPct: number;
  rows: { label: string; mm: number; pct: number; limitPct: number; fits: boolean; deltaMm: number }[];
}

const pct = (mm: number, min: number, max: number) => ((mm - min) / (max - min)) * 100;

/** One shared axis (rounded out to 10 mm) holding the limit and every card, so the limit is at one x for all rows. */
export function rulerLayout(cards: readonly RulerInput[], limitMm: number): RulerLayout | null {
  if (!Number.isFinite(limitMm) || limitMm <= 0) return null;
  const good = cards.filter((c) => Number.isFinite(c.mm) && c.mm > 0);
  if (!good.length) return null;
  const lengths = [limitMm, ...good.map((c) => c.mm)];
  const min = Math.floor((Math.min(...lengths) - 5) / 10) * 10;
  const max = Math.ceil((Math.max(...lengths) + 5) / 10) * 10;
  const limitPct = pct(limitMm, min, max);
  return {
    min,
    max,
    limitPct,
    rows: good.map((c) => ({ label: c.label, mm: c.mm, pct: pct(c.mm, min, max), limitPct, fits: c.mm <= limitMm, deltaMm: Math.abs(limitMm - c.mm) })),
  };
}
