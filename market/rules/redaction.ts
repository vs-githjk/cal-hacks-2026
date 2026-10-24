// What a seller may see of a Need. Built field by field from an allowlist, never by deleting
// fields, so anything added to Need later stays private by default.
import type { NeedItem } from "./types";

export interface SellerNeedView {
  need_id: string;
  items: NeedItem[];
  delivery_window: string;
  deadline: string;
}

export function sellerView<N extends { id: string; items: NeedItem[]; delivery_window: string }>(
  need: N,
  deadline: string,
): SellerNeedView {
  return {
    need_id: need.id,
    items: need.items.map((i) => ({
      sku_spec: i.sku_spec,
      condition: i.condition,
      variant: i.variant,
      quantity: i.quantity,
      unit: i.unit,
    })),
    delivery_window: need.delivery_window,
    deadline,
  };
}
