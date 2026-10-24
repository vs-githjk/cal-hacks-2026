// Approval before payment, and idempotent order creation.
import type { Result } from "./types";
import { money } from "./types";

export function needsApproval(amount: number, spend_limit: number): boolean {
  return amount > spend_limit;
}

export function authorizePayment(
  order: { amount: number; limit_checked: boolean; approval_id: string },
  spend_limit: number,
): Result {
  if (!Number.isFinite(order.amount) || order.amount <= 0) return { ok: false, reasons: ["amount must be a positive number"] };
  if (!order.limit_checked) return { ok: false, reasons: ["the spend limit was not checked for this order"] };
  if (needsApproval(order.amount, spend_limit) && !order.approval_id) {
    return { ok: false, reasons: [`${money(order.amount)} is over the ${money(spend_limit)} limit and has no owner approval`] };
  }
  return { ok: true };
}

/** An existing order with this idempotency key, if any. An empty key never matches. */
export function findDuplicate<O extends { idempotency_key: string }>(orders: O[], key: string): O | undefined {
  if (!key) return undefined;
  return orders.find((o) => o.idempotency_key === key);
}
