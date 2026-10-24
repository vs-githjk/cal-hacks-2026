// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { approvalLabel, entryDate, fetchMemory, memoryForBuyer, paymentModeLabel, parseMemoryResponse, selectMemory, sourceUrl } from "./memory.ts";

const base = { at: "2026-10-24T10:00:00Z", origin: "SIM", source: "demo_run", source_ref: "run-1", buyer_id: "vidyut", seller_id: "fair-price-pc" };
const purchase = (over: Record<string, unknown> = {}, detail: Record<string, unknown> = {}) => ({
  ...base, id: "run-1:purchase:m1", kind: "purchase", summary: "Bought from Fair Price PC for $1,249.99 before tax (SIM payment, no money moved)",
  detail: { mandate_id: "m1", deal_id: "d1", amount_before_tax: 1249.99, currency: "USD", payee: "best-buy@pay.example.test", approval_method: "voice_code", payment_mode: "sim", payment_ref: "sim_ch_1", listing_origin: "MIRROR", ...detail },
  ...over,
});
const veto = (over: Record<string, unknown> = {}, detail: Record<string, unknown> = {}) => ({
  ...base, id: "run-1:veto:b1", kind: "veto", summary: "Vetoed the cheaper bid", at: "2026-10-24T10:05:00Z",
  detail: { bid_id: "b1", rule_id: "recall-notice", reason: "The model has an open recall", source_url: "https://example.com/recall", ...detail },
  ...over,
});
const lesson = (over: Record<string, unknown> = {}, detail: Record<string, unknown> = {}) => ({
  ...base, id: "run-1:lesson:r1", kind: "lesson", summary: "Lost round 1 by a small gap", at: "2026-10-24T10:10:00Z",
  detail: { round_id: "r1", won: false, reason: "Price", gap_band: "within10", what_to_change: "Lower the open-box line", ...detail },
  ...over,
});
const goal = (over: Record<string, unknown> = {}) => ({
  ...base, id: "run-1:goal:g1", kind: "goal", summary: "Wanted an RTX 5070", at: "2026-10-24T09:00:00Z",
  detail: { goal_id: "g1", items: [{ sku_spec: "RTX 5070", condition: "new", quantity: 1 }], cap: 1300, deadline: "2026-10-30T23:59:00Z" },
  ...over,
});
const envelope = (entries: unknown[], sources: unknown[] = [], note = "") => ({ entries, sources, note });
const src = (over: Record<string, unknown> = {}) => ({ ref: "run-1.json", kind: "demo_run", state: "ok", sample: false, rows: 1, ...over });

test("parseMemoryResponse keeps purchase, veto, lesson and goal rows and the producer's source status", () => {
  const r = parseMemoryResponse(envelope([purchase(), veto(), lesson(), goal()], [src(), src({ ref: "market-memory-1.json", kind: "market", state: "empty", rows: 0, dropped: 2 }), src({ ref: "bad.json", state: "error", rows: 0 })], "ignored note"));
  assert.deepEqual(r.entries.map((e) => e.kind), ["purchase", "veto", "lesson", "goal"]);
  assert.deepEqual(r.sources.map((s) => s.state), ["ok", "empty", "error"]);
  assert.equal(r.sources[1]!.dropped, 2);
  assert.equal(r.rejected, 0);
  assert.equal(r.note, "ignored note");
});

test("an empty history parses to empty lists and keeps the producer's note", () => {
  const r = parseMemoryResponse(envelope([], [], "no demo runs or market snapshots recorded yet"));
  assert.deepEqual(r.entries, []);
  assert.deepEqual(r.sources, []);
  assert.equal(r.note, "no demo runs or market snapshots recorded yet");
});

test("a malformed envelope throws instead of showing an empty history", () => {
  for (const bad of [null, undefined, 5, "x", [], { entries: {}, sources: [], note: "" }, { entries: [], sources: "no", note: "" }, { sources: [] }, { entries: [] }]) {
    assert.throws(() => parseMemoryResponse(bad), /memory response/i, JSON.stringify(bad));
  }
});

test("malformed entries are dropped and counted, never repaired", () => {
  const r = parseMemoryResponse(envelope([
    purchase(),
    null, "row", 7,
    purchase({ kind: "refund" }),
    purchase({ id: "" }),
    purchase({ id: undefined }),
    purchase({ origin: "REAL" }),
    purchase({ source: "guess" }),
    purchase({ buyer_id: 3 }),
    purchase({ detail: undefined }),
    purchase({}, { payee: undefined }),
    veto({}, { rule_id: undefined }),
    goal({ detail: { goal_id: "g", items: [{ sku_spec: "x", condition: "new", quantity: "1" }], cap: 1, deadline: "d" } }),
  ]));
  assert.equal(r.entries.length, 1);
  assert.equal(r.rejected, 13);
});

test("a purchase needs a positive, finite, numeric amount", () => {
  for (const amount of [true, false, "12.50", null, NaN, Infinity, -Infinity, 0, -5]) {
    const r = parseMemoryResponse(envelope([purchase({}, { amount_before_tax: amount })]));
    assert.equal(r.entries.length, 0, `amount ${String(amount)}`);
    assert.equal(r.rejected, 1);
  }
  assert.equal(parseMemoryResponse(envelope([purchase({}, { amount_before_tax: 0.01 })])).entries.length, 1);
});

test("purchase payment mode, listing origin and approval method come only from the contract's values", () => {
  for (const detail of [{ payment_mode: "card" }, { payment_mode: "" }, { listing_origin: "REAL" }, { currency: 840 }]) {
    assert.equal(parseMemoryResponse(envelope([purchase({}, detail)])).entries.length, 0, JSON.stringify(detail));
  }
  assert.equal(parseMemoryResponse(envelope([purchase({}, { payment_mode: "stripe_test" })])).entries.length, 1);
});

test("a lesson carries a band, never a raw gap, and a real boolean result", () => {
  for (const detail of [{ gap_band: "37.5" }, { gap_band: 12 }, { gap_band: "under 5%" }, { won: "false" }, { won: 0 }]) {
    assert.equal(parseMemoryResponse(envelope([lesson({}, detail)])).entries.length, 0, JSON.stringify(detail));
  }
  for (const band of ["within5", "within10", "within20", "over20"]) {
    assert.equal(parseMemoryResponse(envelope([lesson({}, { gap_band: band })])).entries.length, 1, band);
  }
});

test("a source the producer reports as unreadable stays visible as an error, never as nothing", () => {
  const r = parseMemoryResponse(envelope([], [src(), null, { ref: 4 }, src({ state: "great" }), src({ rows: -1 }), src({ rows: "3" })]));
  assert.equal(r.sources.length, 6);
  assert.deepEqual(r.sources.slice(1).map((s) => s.state), ["error", "error", "error", "error", "error"]);
});

test("entryDate is a Date only for a real ISO time; empty and invalid stay unknown", () => {
  assert.equal(entryDate(purchase() as never)!.toISOString(), "2026-10-24T10:00:00.000Z");
  for (const at of ["", "not a date", "2026-13-45T00:00:00Z", "yesterday"]) {
    assert.equal(entryDate({ ...purchase(), at } as never), null, at);
  }
});

test("selectMemory sorts by real time, newest first, with unknown times last", () => {
  const entries = parseMemoryResponse(envelope([
    purchase({ id: "a", at: "" }),
    purchase({ id: "b", at: "2026-10-24T08:00:00Z" }),
    purchase({ id: "c", at: "garbage" }),
    purchase({ id: "d", at: "2026-10-24T12:00:00Z" }),
  ])).entries;
  assert.deepEqual(selectMemory(entries, "all", "").map((e) => e.id), ["d", "b", "a", "c"]);
});

test("selectMemory filters by kind and by a plain text query over recorded fields, and claims nothing semantic", () => {
  const entries = parseMemoryResponse(envelope([purchase(), veto(), lesson(), goal()])).entries;
  assert.deepEqual(selectMemory(entries, "veto", "").map((e) => e.kind), ["veto"]);
  assert.equal(selectMemory(entries, "all", "").length, 4);
  assert.deepEqual(selectMemory(entries, "all", "  RECALL ").map((e) => e.kind), ["veto"], "rule id and reason, case-insensitive, trimmed");
  assert.deepEqual(selectMemory(entries, "all", "best-buy").map((e) => e.kind), ["purchase"], "payee");
  assert.deepEqual(selectMemory(entries, "all", "open-box").map((e) => e.kind), ["lesson"], "what to change");
  assert.deepEqual(selectMemory(entries, "purchase", "recall"), [], "kind and query both apply");
  assert.deepEqual(selectMemory(entries, "all", "no such thing"), []);
});

test("sourceUrl links only a real web address", () => {
  const link = (u: string) => sourceUrl(parseMemoryResponse(envelope([veto({}, { source_url: u })])).entries[0]!);
  assert.equal(link("https://example.com/recall"), "https://example.com/recall");
  for (const bad of ["https://", "", "javascript:alert(1)", "data:text/html,x", "example.com/recall", "sim:fixture"]) assert.equal(link(bad), null, bad);
  assert.equal(sourceUrl(parseMemoryResponse(envelope([purchase()])).entries[0]!), null, "only a veto has a source");
});

test("memoryForBuyer shows only rows recorded for the paired buyer and fails closed on an unknown one", () => {
  const entries = parseMemoryResponse(envelope([
    purchase({ id: "a" }),
    purchase({ id: "b", buyer_id: "buyer-b" }),
    purchase({ id: "c", buyer_id: "" }),
    veto({ id: "v", buyer_id: "" }),
    goal({ id: "g", buyer_id: "" }),
  ])).entries;
  assert.deepEqual(memoryForBuyer(entries, "vidyut").map((e) => e.id), ["a", "v"]);
  assert.deepEqual(memoryForBuyer(entries, "buyer-b").map((e) => e.id), ["b", "v"]);
  assert.deepEqual(memoryForBuyer(entries, ""), [], "no identity, no rows");
  assert.deepEqual(memoryForBuyer(entries, "stranger").map((e) => e.id), ["v"], "only the buyer-less market veto");
});

test("a seller lesson has no buyer by design: it shows for any paired buyer, but another buyer's lesson never does", () => {
  const entries = parseMemoryResponse(envelope([
    lesson({ id: "l1", buyer_id: "" }),
    lesson({ id: "l2", buyer_id: "vidyut" }),
    lesson({ id: "l3", buyer_id: "buyer-b" }),
  ])).entries;
  assert.deepEqual(memoryForBuyer(entries, "vidyut").map((e) => e.id), ["l1", "l2"]);
  assert.deepEqual(memoryForBuyer(entries, ""), []);
});

test("labels say what was recorded: SIM money is SIM, and an unknown method stays unavailable", () => {
  assert.equal(paymentModeLabel("sim"), "SIM payment, no money moved");
  assert.equal(paymentModeLabel("stripe_test"), "Stripe test mode, no real money");
  assert.equal(paymentModeLabel("none"), "No payment recorded");
  assert.equal(approvalLabel("voice_code"), "Approved by phone code");
  assert.equal(approvalLabel("none"), "No approval method recorded");
  assert.equal(approvalLabel("telepathy"), "Unavailable");
});

// ---- fetchMemory: one read path, visible failures, cancelable.

const realFetch = globalThis.fetch;
const withFetch = async (impl: typeof fetch, run: () => Promise<void>) => {
  globalThis.fetch = impl;
  try {
    await run();
  } finally {
    globalThis.fetch = realFetch;
  }
};
const json = (body: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(body), { status: 200, ...init });

test("fetchMemory reads /v1/memory without the sample flag and parses it", async () => {
  let url = "";
  await withFetch(async (u) => { url = String(u); return json(envelope([purchase()], [src()])); }, async () => {
    const r = await fetchMemory();
    assert.equal(r.entries.length, 1);
  });
  assert.match(url, /\/v1\/memory$/);
});

test("fetchMemory fails visibly: HTTP errors, unreachable feed, non JSON and wrong shapes all throw", async () => {
  await withFetch(async () => json({ detail: "boom" }, { status: 500 }), async () => { await assert.rejects(fetchMemory(), /500/); });
  await withFetch(async () => { throw new TypeError("fetch failed"); }, async () => { await assert.rejects(fetchMemory(), /memory/i); });
  await withFetch(async () => new Response("<html>", { status: 200 }), async () => { await assert.rejects(fetchMemory(), /memory/i); });
  await withFetch(async () => json({ entries: "x" }), async () => { await assert.rejects(fetchMemory(), /memory response/i); });
});

test("an identity switch aborts the pending read: the signal is passed through and an aborted read never resolves with rows", async () => {
  const ctl = new AbortController();
  let seen: AbortSignal | null | undefined;
  await withFetch(
    (_u, init) => {
      seen = init?.signal;
      return new Promise((_res, rej) => init?.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError"))));
    },
    async () => {
      const pending = fetchMemory(ctl.signal);
      ctl.abort();
      await assert.rejects(pending, (e: unknown) => (e as Error).name === "AbortError");
    },
  );
  assert.equal(seen, ctl.signal);
});

test("a market veto has no buyer (buyer_id empty): kept for any paired buyer, another buyer's veto is dropped", () => {
  const entries = parseMemoryResponse(envelope([
    veto({ id: "mv", buyer_id: "" }),
    veto({ id: "vy", buyer_id: "buyer-y" }),
  ])).entries;
  assert.deepEqual(memoryForBuyer(entries, "buyer-x").map((e) => e.id), ["mv"]);
  assert.deepEqual(memoryForBuyer(entries, ""), []);
});
