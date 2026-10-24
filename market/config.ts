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

export const MARKET_CONFIG = {
  seller_fee: SELLER_FEE,
  allowance_ladder: ALLOWANCE_LADDER,
};

export type MarketConfig = typeof MARKET_CONFIG;
