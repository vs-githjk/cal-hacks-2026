// Shared market types. Field names mirror contracts/*.schema.json.

export type Source = "live" | "mirror" | "simulated" | "sandbox" | "recorded";

export interface NeedItem {
  sku_spec: string;
  grade: string;
  pack_size: string;
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
  source: Source;
}

export interface BidLine {
  /** The Need line this bid answers. */
  sku_spec: string;
  /** What is actually offered; absent means the same as sku_spec. */
  offered_spec?: string;
  unit_price: number;
  quantity: number;
}

export interface Bid {
  id: string;
  need_id: string;
  supplier_id: string;
  persona: string;
  lines: BidLine[];
  total_landed_price: number;
  perks: string[];
  claims: string[];
  floor_check_passed: boolean;
  mirror_snapshot_id: string;
  decision_trace: string;
  expires_at: string;
  source: Source;
  /** Market-internal: epoch ms when the market sealed the bid. */
  sealed_at: number;
}

export interface SpecCard {
  id: string;
  sku_spec: string;
  item_name: string;
  grade: string;
  pack_size: string;
  case_count: number;
  unit: string;
  allowed_substitutes: string[];
  photo_checks: string[];
  source: Source;
}

export interface SupplierTerms {
  supplier_id: string;
  min_order_value: number;
  delivery_fee: number;
  /** Delivery is free when the supplier subtotal reaches this. 0 means always free. */
  free_delivery_over: number;
  cutoff_time: string;
  delivery_days: string[];
  source: Source;
}

export type PlanMode = "cheapest_per_line" | "optimizer";

export interface PlanLine {
  sku_spec: string;
  quantity: number;
  unit_price: number;
}

export interface Allocation {
  supplier_id: string;
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
  source: Source;
  /** Market-internal: false when some supplier minimum is not met. */
  feasible: boolean;
}

export type Result = { ok: true } | { ok: false; reasons: string[] };

export interface Outcome {
  value: number;
  how_computed: string;
  source: Source;
}

export const round2 = (x: number): number => Math.round(x * 100) / 100;
export const money = (x: number): string => `$${round2(x).toFixed(2)}`;
