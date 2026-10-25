// Run with: npm test --prefix web (node --test, no extra dependency).
// #449 RT-32: a vendor's test mode (Stripe test charge) is SANDBOX: shown as SANDBOX, never LIVE and never hidden as SIM.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { Timestamp } from "spacetimedb";
import { asChipOrigin } from "./origin.ts";
import { asOrigin, eventsFromRows, feedFromRows } from "./screens.ts";
import { serviceStatuses } from "./runMode.ts";

const ts = (ms: number) => ({ microsSinceUnixEpoch: BigInt(ms) * 1000n }) as unknown as Timestamp;
const payment = (origin: string) => ({
  id: 7n, kind: "payment_recorded", refTable: "payment", refId: "h1", sellerId: "byte-bros",
  label: "Payment recorded (SANDBOX: Stripe test mode, no real money)", origin, at: ts(Date.UTC(2026, 9, 24, 9, 0, 0)),
});

test("asChipOrigin keeps LIVE, MIRROR and SANDBOX and turns anything else into SIM", () => {
  for (const o of ["LIVE", "MIRROR", "SANDBOX"] as const) assert.equal(asChipOrigin(o), o);
  for (const o of ["SIM", "", "sandbox", "Sandbox", "TEST", "REAL", "live"]) assert.equal(asChipOrigin(o), "SIM", o);
});

test("a bid's origin never becomes SANDBOX: asOrigin is for bids and stays LIVE, MIRROR or SIM", () => {
  assert.equal(asOrigin("SANDBOX"), "SIM");
});

test("the floor feed and the event list show a Stripe test payment as SANDBOX", () => {
  const [item] = feedFromRows([payment("SANDBOX")], []);
  assert.equal(item!.origin, "SANDBOX");
  const [view] = eventsFromRows([payment("SANDBOX")]);
  assert.equal(view!.origin, "SANDBOX");
  assert.equal(eventsFromRows([payment("SIM")])[0]!.origin, "SIM");
  assert.equal(eventsFromRows([payment("nonsense")])[0]!.origin, "SIM");
});

test("the Payments service says SANDBOX, with its own tone, and ranks it below LIVE and MIRROR", () => {
  const only = serviceStatuses([{ kind: "payment_recorded", origin: "SANDBOX" }], true).find((s) => s.name === "Payments")!;
  assert.equal(only.text, "SANDBOX (1)");
  assert.equal(only.tone, "sandbox");
  const mixed = serviceStatuses([
    { kind: "payment_recorded", origin: "SANDBOX" }, { kind: "payment_recorded", origin: "SIM" }, { kind: "payment_recorded", origin: "LIVE" },
  ], true).find((s) => s.name === "Payments")!;
  assert.equal(mixed.text, "LIVE + SANDBOX + SIM (3)");
  assert.equal(mixed.tone, "live");
  const simOnly = serviceStatuses([{ kind: "payment_recorded", origin: "SIM" }], true).find((s) => s.name === "Payments")!;
  assert.equal(simOnly.text, "SIM (1)");
});
