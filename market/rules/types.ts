// Shared market types. Field names mirror contracts/*.schema.json.

export type Origin = "LIVE" | "MIRROR" | "SIM";
export type Condition = "new" | "open-box" | "refurbished" | "used" | "unknown";

export interface NeedItem {
  sku_spec: string;
  condition: Condition;
  /** Retail or OEM, cooler included, model number. */
  variant: string;
  quantity: number;
  unit: string;
}

export interface Need {
  id: string;
  buyer_id: string;
  items: NeedItem[];
  delivery_window: string;
  spend_limit: number;
  consent: boolean;
  auction_window_s: number;
  origin: Origin;
}

export interface BidLine {
  /** The Need line this bid answers. */
  sku_spec: string;
  /** What is actually offered; absent means the same as sku_spec. */
  offered_spec?: string;
  /** Condition of what is offered; absent means the condition the Need asked for. */
  offered_condition?: Condition;
  unit_price: number;
  quantity: number;
}

export interface Bid {
  id: string;
  need_id: string;
  seller_id: string;
  persona: string;
  lines: BidLine[];
  total_landed_price: number;
  perks: string[];
  claims: string[];
  floor_check_passed: boolean;
  mirror_snapshot_id: string;
  decision_trace: string;
  expires_at: string;
  origin: Origin;
  /** Listing URL, actor id or dataset id. */
  source: string;
  /** Market-internal: epoch ms when the market sealed the bid. */
  sealed_at: number;
}

/** Fit attributes the fit checker reads. A missing key means unknown. */
export interface SpecAttrs {
  socket?: string;
  chipset?: string;
  ram_type?: string;
  tdp_w?: number;
  length_mm?: number;
  height_mm?: number;
  form_factor?: string;
  connectors?: string[];
}

/** C's SpecCard (contracts/SpecCard.schema.json). */
export interface SpecCard {
  id: string;
  category: string;
  name: string;
  model_number?: string;
  condition?: Condition;
  variant?: string;
  attrs: SpecAttrs;
  price?: number;
  currency?: string;
  origin: Origin;
  source: string;
}

export interface SellerTerms {
  seller_id: string;
  min_order_value: number;
  delivery_fee: number;
  /** Delivery is free when the seller subtotal reaches this. 0 means always free. */
  free_delivery_over: number;
  cutoff_time: string;
  delivery_days: string[];
  origin: Origin;
}

export type PlanMode = "cheapest_per_line" | "optimizer";

export interface PlanLine {
  sku_spec: string;
  quantity: number;
  unit_price: number;
}

export interface Allocation {
  seller_id: string;
  bid_id: string;
  lines: PlanLine[];
}

export interface OrderPlan {
  id: string;
  need_id: string;
  mode: PlanMode;
  advocate: boolean;
  allocations: Allocation[];
  subtotal: number;
  fees: number;
  total: number;
  savings_vs_baseline: number;
  explanation: string[];
  origin: Origin;
  /** Market-internal: false when some seller minimum is not met. */
  feasible: boolean;
}

export type Result = { ok: true } | { ok: false; reasons: string[] };

export interface Outcome {
  value: number;
  how_computed: string;
  origin: Origin;
}

export const round2 = (x: number): number => Math.round(x * 100) / 100;
export const money = (x: number): string => `$${round2(x).toFixed(2)}`;
