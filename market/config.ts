// Market configuration. Fee numbers live here and nowhere else.

export interface SellerFeeConfig {
  /** Share of the delivered sale price. */
  rate: number;
  min: number;
  cap_per_item: number;
  status: "PROPOSED" | "FINAL";
  due_when: string;
}

/** PROPOSED in 00-shared (business section); assumed until the first seller quotes. */
export const SELLER_FEE: SellerFeeConfig = {
  rate: 0.03,
  min: 1,
  cap_per_item: 25,
  status: "PROPOSED",
  due_when: "only on a delivered sale that passed the receiving check",
};

/**
 * PROPOSED allowance ladder (USD): what the agent may spend without a call. Step 0 is $0, so a
 * new buyer's first buy always calls. Each clean receiving check by the buyer moves up one step.
 */
export const ALLOWANCE_LADDER: { per_purchase: number; per_period: number }[] = [
  { per_purchase: 0, per_period: 0 },
  { per_purchase: 50, per_period: 150 },
  { per_purchase: 150, per_period: 400 },
  { per_purchase: 300, per_period: 800 },
  { per_purchase: 600, per_period: 1500 },
];

/**
 * PROPOSED weights for quality-adjusted landed price (the advocate ranks on it, 00-shared Seller model).
 * Fractions of the line's price: a worse condition costs more, a bid without a 30-day-returns perk
 * costs 2 percent. Same numbers as the Lane D demo runner; Lane A's advocate owns the final weights.
 */
export interface QualityWeights {
  condition_adj: Record<string, number>;
  no_returns_adj: number;
  /** A perk like "30-day returns" counts when its day count is at least this. */
  min_returns_days: number;
}

export const QUALITY: QualityWeights & { status: "PROPOSED" | "FINAL" } = {
  condition_adj: { new: 0, "open-box": 0.04, refurbished: 0.08, used: 0.15, unknown: 0 },
  no_returns_adj: 0.02,
  min_returns_days: 30,
  status: "PROPOSED",
};

export const MARKET_CONFIG = {
  seller_fee: SELLER_FEE,
  allowance_ladder: ALLOWANCE_LADDER,
  quality: QUALITY,
};

export type MarketConfig = typeof MARKET_CONFIG;
