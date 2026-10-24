import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { purchaseFromRows, reviewsFromRows, stepFeedFromRows } from "./screens";
import { PurchaseCard, ReceiptCard, ShieldCard, VetoCard } from "../components/buyer";
import { BuyerScreen } from "../components/screens";
import { buyerFeedFromRows, selectBuyerRound } from "../app/buyer/page";

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
      { paymentRef: "", paymentAmount: 100, paymentMode: "sim", paidAt: ts(900) },
      { paymentRef: "p", paymentAmount: 100, paymentMode: "sim", retired: true },
      { settled: true },
      { approvalMethod: "typed_code" },
    ]) expect(purchaseFromRows([purchase(extra)] as never, "goal-a", 1_000)?.state).toBe("inconsistent");
  });

  it("uses recorded approval, retirement and expiry states without manufacturing a receipt", () => {
    expect(purchaseFromRows([purchase({ approvalMethod: "typed_code", approvedAt: ts(900) })] as never, "goal-a", 1_000)?.state).toBe("approval_recorded");
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

  it("retains an earlier bid veto when another bid has a later non-veto advocate result", () => {
    const reviews = reviewsFromRows([
      { goalId: "goal-a", roundId: "r1", bidId: "vetoed", checkId: 1n, kind: "advocate", result: "veto", detail: "veto reason", evidenceUrl: "https://example.test/veto?x=1#source", origin: "MIRROR", sellerId: "s1", sellerName: "stored label", landed: 90, bindingHash: "a".repeat(64), at: ts(1) },
      { goalId: "goal-a", roundId: "r1", bidId: "approved", checkId: 2n, kind: "advocate", result: "buy", detail: "buy reason", evidenceUrl: "", origin: "LIVE", sellerId: "s2", sellerName: "other", landed: 80, bindingHash: "b".repeat(64), at: ts(2) },
    ] as never, "goal-a", "r1");
    expect(reviews.veto).toMatchObject({ seller: "stored label", finding: "veto reason", sourceUrl: "https://example.test/veto?x=1#source", checkOrigin: "MIRROR" });
  });

  it("rejects credentialed evidence URLs", () => {
    const veto = reviewsFromRows([{
      goalId: "goal-a", roundId: "r1", kind: "advocate", result: "veto", detail: "reason", evidenceUrl: "https://user:pass@example.test/path",
      origin: "SIM", sellerId: "s", sellerName: "seller", landed: 90, bindingHash: "b".repeat(64), at: ts(2),
    }] as never, "goal-a", "r1").veto;
    expect(veto?.sourceUrl).toBe("");
  });

  it("does not repair evidence URLs containing raw whitespace or controls", () => {
    for (const evidenceUrl of ["https://example.test/a b", "https://example.test/a\npath"]) {
      const veto = reviewsFromRows([{
        goalId: "goal-a", roundId: "r1", kind: "advocate", result: "veto", detail: "reason", evidenceUrl,
        origin: "SIM", sellerId: "s", sellerName: "seller", landed: 90, bindingHash: "b".repeat(64), at: ts(2),
      }] as never, "goal-a", "r1").veto;
      expect(veto?.sourceUrl).toBe("");
    }
  });

  it("shows no stale review when the selected round ID is not ready", () => {
    const rows = [{
      goalId: "goal-a", roundId: "old", kind: "advocate", result: "veto", detail: "old review", evidenceUrl: "https://example.test",
      origin: "SIM", sellerId: "s", sellerName: "seller", landed: 90, bindingHash: "b".repeat(64), at: ts(2),
    }];
    expect(reviewsFromRows(rows as never, "goal-a")).toEqual({ veto: null, shield: null });
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

describe("buyer page selection and feed composition", () => {
  it("selects only the latest owned round with a deterministic tie break", () => {
    const rounds = [
      { goalId: "goal-a", roundId: "older", openedAt: ts(1_000), needId: "n1", state: "closed" },
      { goalId: "goal-a", roundId: "tie-z", openedAt: ts(2_000), needId: "n2", state: "closed" },
      { goalId: "goal-b", roundId: "foreign", openedAt: ts(9_000), needId: "nf", state: "closed" },
      { goalId: "goal-a", roundId: "tie-a", openedAt: ts(2_000), needId: "n3", state: "open" },
    ];
    expect(selectBuyerRound(rounds as never, "goal-a")?.roundId).toBe("tie-a");
    expect(selectBuyerRound(rounds as never, "missing")).toBeNull();
  });

  it("composes only goal-scoped steps and notifications and deduplicates by their stable IDs", () => {
    const steps = [
      { stableId: "step-1", goalId: "goal-a", klass: "progress", text: "one", origin: "LIVE", at: ts(1_000) },
      { stableId: "step-1", goalId: "goal-a", klass: "progress", text: "duplicate", origin: "LIVE", at: ts(1_000) },
      { stableId: "step-x", goalId: "goal-b", klass: "progress", text: "foreign", origin: "SIM", at: ts(2_000) },
      { stableId: "step-2", goalId: "goal-a", klass: "payment_recorded", text: "paid", origin: "SIM", at: ts(3_000) },
    ];
    const notes = [
      { id: 7n, goalId: "goal-a", klass: "state", text: "note", push: false, at: ts(2_000) },
      { id: 7n, goalId: "goal-a", klass: "state", text: "duplicate note", push: false, at: ts(2_000) },
      { id: 8n, goalId: "goal-b", klass: "state", text: "foreign note", push: false, at: ts(4_000) },
    ];
    const feed = buyerFeedFromRows(steps as never, notes as never, "goal-a");
    expect(feed.map((item) => item.key)).toEqual(["step-step-2", "notification-7", "step-step-1"]);
    expect(feed.some((item) => item.text === "foreign" || item.text === "foreign note" || item.text === "duplicate note")).toBe(false);
    expect(feed[0]).toMatchObject({ kind: "deal", origin: "SIM", text: "paid" });
    expect(feed[2]).toMatchObject({ kind: "progress", origin: "LIVE", text: "one" });
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

  it("keeps the actual purchase path empty and read-only instead of showing sample cards or demo approval", () => {
    const html = renderToStaticMarkup(createElement(BuyerScreen, {
      goal: { text: "test goal", type: "budget_cap", state: "ACTIVE", cap: 100, reserved: 0, deadline: new Date(0), conditions: [], variant: "", origin: "SIM", skipped: [], allowance: null },
      bids: [{ rank: 1, seller: "sample seller", origin: "SIM", condition: "new", landed: 10, adjusted: 10, recommendation: "buy", why: "sample", won: true }],
      veto: { seller: "sample veto", origin: "SIM", landed: 10, finding: "sample", ruleId: "sample", sourceUrl: "", checkedAt: new Date(0), checkOrigin: "SIM" },
      shield: { verdict: "block", seller: "sample shield", pageOrigin: "SIM", chars: 1, latencyMs: 1, evidence: [], ruleIds: [], version: "sample", verdictOrigin: "SIM" },
      approval: { amount: 10, payee: "sample", allowance: 1, wordPair: "secret-code", codeExpiresAt: new Date(0), whyAnswer: "sample", attempts: [] },
      purchase: null,
      receipt: { seller: "sample receipt", item: "sample", condition: "new", amount: 10, shipping: 1, paymentMethod: "SIM", chargeId: "sample", chargeStatus: "SIM", paidAt: new Date(0), mandateId: "sample", mandateHash: "sample", mandateExpires: new Date(0), mandateOrigin: "SIM", signature: "sample" },
      feed: [], buyerName: "buyer",
      sample: { bids: true, veto: true, shield: true, approval: true, receipt: true },
    }));
    expect(html).toContain("No recorded mandate or payment is currently available");
    expect(html).not.toContain("one-time code");
    expect(html).not.toContain("calls you");
    expect(html).not.toContain("signed mandate");
    expect(html).not.toContain("sample seller");
    expect(html).not.toContain("sample veto");
    expect(html).not.toContain("sample shield");
    expect(html).not.toContain("sample receipt");
    expect(html).not.toContain("secret-code");
    expect(html).not.toContain("<form");
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

  it("labels a Stripe test receipt without a SIM payment badge", () => {
    const payment = purchaseFromRows([purchase({
      paymentRef: "pi-test", paymentAmount: 100, paymentMode: "stripe_test", paidAt: ts(1_000), origin: "SIM",
    })] as never, "goal-a", 2_000)!;
    const html = renderToStaticMarkup(createElement(ReceiptCard, { receipt: payment.receipt }));
    expect(html).toContain("Stripe test");
    expect(html).not.toContain("SIM, no money moved");
  });
});
