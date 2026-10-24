// The flat seller fee. Same for every seller; nothing in ranking or the advocate reads it.
import type { SellerFeeConfig } from "../config";
import type { Outcome } from "./types";
import { money, round2 } from "./types";

export function sellerFee(salePrice: number, cfg: SellerFeeConfig): Outcome {
  const value = round2(Math.min(cfg.cap_per_item, Math.max(cfg.min, Math.max(0, salePrice) * cfg.rate)));
  return {
    value,
    how_computed:
      `${cfg.status}: ${round2(cfg.rate * 100)} percent of ${money(salePrice)}, minimum ${money(cfg.min)}, ` +
      `capped at ${money(cfg.cap_per_item)} per item, due ${cfg.due_when}.`,
    origin: "SIM",
  };
}
