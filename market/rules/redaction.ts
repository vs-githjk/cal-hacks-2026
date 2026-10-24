// What a supplier may see of a Need. Built field by field from an allowlist, never by deleting
// fields, so anything added to Need later stays private by default.
import type { NeedItem } from "./types";

export interface SupplierNeedView {
  need_id: string;
  items: NeedItem[];
  delivery_window: string;
  deadline: string;
}

export function supplierView<N extends { id: string; items: NeedItem[]; delivery_window: string }>(
  need: N,
  deadline: string,
): SupplierNeedView {
  return {
    need_id: need.id,
    items: need.items.map((i) => ({
      sku_spec: i.sku_spec,
      grade: i.grade,
      pack_size: i.pack_size,
      quantity: i.quantity,
      unit: i.unit,
    })),
    delivery_window: need.delivery_window,
    deadline,
  };
}
