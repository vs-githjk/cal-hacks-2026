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

export const MARKET_CONFIG = {
  seller_fee: SELLER_FEE,
};

export type MarketConfig = typeof MARKET_CONFIG;
