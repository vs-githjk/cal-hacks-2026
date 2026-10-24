import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { purchaseFromRows, reviewsFromRows, stepFeedFromRows } from "./screens";
import { PurchaseCard, ReceiptCard, ShieldCard, VetoCard } from "../components/buyer";

const ts = (ms: number) => ({ microsSinceUnixEpoch: BigInt(ms) * 1000n });
const purchase = (overrides: Record<string, unknown> = {}) => ({
  mandateHash: "hash-a", mandateId: "mandate-a", dealId: "deal-a", goalId: "goal-a", needId: "need-a",
  amount: 100, payee: "seller", expiry: ts(20_000), origin: "SIM", withinAllowance: false,
  retired: false, reservationMatches: true, settled: false,
  ...overrides,
});

describe("purchaseFromRows", () => {
  it("keeps a recorded SIM payment after expiry and labels it no money moved", () => {
    expect(purchaseFromRows([purchase({
      expiry: ts(1_000), paymentRef: "sim-1", paymentAmount: 100, paymentMode: "sim", paidAt: ts(900),
    })] as never, "goal-a", 5_000)).toMatchObject({
      state: "payment_recorded", receipt: { paymentMethod: "SIM, no money moved", amount: 100 },
    });
  });

  it("distinguishes Stripe test payment and exact settled state", () => {
    expect(purchaseFromRows([purchase({
      paymentRef: "pi-test", paymentAmount: 100, paymentMode: "stripe_test", paidAt: ts(1_000), settled: true,
    })] as never, "goal-a", 5_000)).toMatchObject({ state: "settled", receipt: { paymentMethod: "Stripe test" } });
  });

  it("prefers an exact reserved mandate over historical payment on another attempt", () => {
    const rows = [
      purchase({ mandateHash: "old", mandateId: "old", reservationMatches: false, expiry: ts(50_000), paymentRef: "old-pay", paymentAmount: 100, paymentMode: "sim" }),
      purchase({ mandateHash: "new", mandateId: "new", reservationMatches: true, expiry: ts(10_000) }),
    ];
    expect(purchaseFromRows(rows as never, "goal-a", 1_000)).toMatchObject({ mandateHash: "new", state: "pending_approval", receipt: null });
  });

  it("chooses the latest actual mandate deterministically and never borrows another goal", () => {
    const rows = [purchase({ mandateHash: "older", expiry: ts(10_000) }), purchase({ goalId: "other", mandateHash: "foreign", expiry: ts(99_000) }), purchase({ mandateHash: "newer", expiry: ts(20_000) })];
    expect(purchaseFromRows(rows as never, "goal-a", 1_000)?.mandateHash).toBe("newer");
    expect(purchaseFromRows(rows as never, "missing", 1_000)).toBeNull();
  });

  it("marks malformed, mismatched, unsupported or payment-plus-retirement rows inconsistent", () => {
    for (const extra of [
      { paymentRef: "p", paymentAmount: 99, paymentMode: "sim" },
      { paymentRef: "p", paymentAmount: Number.NaN, paymentMode: "sim" },
      { paymentRef: "p", paymentAmount: 100, paymentMode: "live" },
      { paymentRef: "p", paymentAmount: 100, paymentMode: "sim", retired: true },
    ]) expect(purchaseFromRows([purchase(extra)] as never, "goal-a", 1_000)?.state).toBe("inconsistent");
  });

  it("uses recorded approval, retirement and expiry states without manufacturing a receipt", () => {
    expect(purchaseFromRows([purchase({ approvalMethod: "typed_code" })] as never, "goal-a", 1_000)?.state).toBe("approval_recorded");
    expect(purchaseFromRows([purchase({ retired: true })] as never, "goal-a", 1_000)?.state).toBe("retired");
    expect(purchaseFromRows([purchase({ reservationMatches: false })] as never, "goal-a", 30_000)?.state).toBe("expired");
  });
});

describe("reviewsFromRows", () => {
  it("keeps exact owned round review rows, validates links, and preserves quarantine as a recorded verdict", () => {
    const rows = [
      { goalId: "goal-a", roundId: "r1", kind: "advocate", result: "veto", detail: "claimed\n<unsafe>", evidenceUrl: "javascript:alert(1)", origin: "SIM", sellerId: "seller-1", sellerName: "seller", landed: 90, bindingHash: "b".repeat(64), at: ts(2) },
      { goalId: "goal-a", roundId: "r1", kind: "shield", result: "quarantine", detail: "rule-1", evidenceUrl: "", origin: "SIM", sellerId: "seller-1", sellerName: "seller", landed: 90, bindingHash: "", at: ts(3) },
      { goalId: "goal-a", roundId: "r2", kind: "claim", result: "veto", detail: "other", evidenceUrl: "https://example.com", origin: "SIM", sellerId: "seller-2", sellerName: "other", landed: 80, bindingHash: "c".repeat(64), at: ts(4) },
    ];
    const result = reviewsFromRows(rows as never, "goal-a", "r1");
    expect(result.veto).toMatchObject({ seller: "seller", finding: "claimed\n<unsafe>", sourceUrl: "" });
    expect(result.shield).toMatchObject({ verdict: "quarantine", ruleIds: ["rule-1"], scope: "bid" });
  });

  it("rejects credentialed evidence URLs", () => {
    const veto = reviewsFromRows([{
      goalId: "goal-a", roundId: "r1", kind: "advocate", result: "veto", detail: "reason", evidenceUrl: "https://user:pass@example.test/path",
      origin: "SIM", sellerId: "s", sellerName: "seller", landed: 90, bindingHash: "b".repeat(64), at: ts(2),
    }] as never, "goal-a", "r1").veto;
    expect(veto?.sourceUrl).toBe("");
  });
});

describe("stepFeedFromRows", () => {
  it("filters by goal and keeps stable IDs, timestamps, text, and origin", () => {
    const feed = stepFeedFromRows([
      { stableId: "s2", goalId: "goal-a", klass: "payment_recorded", text: "SIM payment", origin: "SIM", at: ts(2_000) },
      { stableId: "s1", goalId: "goal-a", klass: "veto", text: "Rule found", origin: "LIVE", at: ts(1_000) },
      { stableId: "foreign", goalId: "goal-b", klass: "payment_recorded", text: "other", origin: "SIM", at: ts(3_000) },
    ] as never, "goal-a");
    expect(feed.map((item) => item.key)).toEqual(["s2", "s1"]);
    expect(feed[1]).toMatchObject({ kind: "veto", text: "Rule found", origin: "LIVE" });
    expect(feed[0]).toMatchObject({ kind: "deal", text: "SIM payment" });
  });
});

describe("buyer cards", () => {
  it("renders hostile recorded text as text and quarantine without claiming it blocked the advocate", () => {
    const veto = reviewsFromRows([{
      goalId: "goal-a", roundId: "r1", kind: "advocate", result: "veto", detail: "<img src=x onerror=alert(1)>",
      evidenceUrl: "javascript:alert(1)", origin: "SIM", sellerId: "s", sellerName: "<seller>", landed: 90,
      bindingHash: "b".repeat(64), at: ts(2),
    }] as never, "goal-a", "r1").veto;
    const shield = reviewsFromRows([{
      goalId: "goal-a", roundId: "r1", kind: "shield", result: "quarantine", detail: "rule.one", evidenceUrl: "",
      origin: "SIM", sellerId: "s", sellerName: "seller", landed: 90, bindingHash: "", at: ts(3),
    }] as never, "goal-a", "r1").shield;
    const html = renderToStaticMarkup(createElement("div", null, createElement(VetoCard, { veto }), createElement(ShieldCard, { shield })));
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).toContain("&lt;seller&gt;");
    expect(html).toContain("Quarantined");
    expect(html).not.toContain("Blocked before the advocate saw it");
    expect(html).not.toContain("javascript:");
  });

  it("shows read-only pending state without approval code controls", () => {
    const purchaseStatus = purchaseFromRows([purchase({})] as never, "goal-a", 1_000)!;
    const html = renderToStaticMarkup(createElement(PurchaseCard, { purchase: purchaseStatus }));
    expect(html).toContain("Complete approval in ASI:One");
    expect(html).not.toContain("<form");
    expect(html).not.toContain("Approve");
  });

  it("shows only the stored payment total and omits absent signature and shipping claims", () => {
    const html = renderToStaticMarkup(createElement(ReceiptCard, { receipt: {
      amount: 100, paymentMethod: "SIM, no money moved", chargeId: "ref-1", chargeStatus: "SIM, no money moved",
      paidAt: new Date(0), mandateId: "m1", mandateHash: "abc", mandateExpires: new Date(1000), mandateOrigin: "SIM",
    } }));
    expect(html.match(/\$100/g)).toHaveLength(1);
    expect(html).toContain("SIM, no money moved");
    expect(html).not.toContain("Signature");
    expect(html).not.toContain("Shipping");
  });
});
