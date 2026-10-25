import { test } from "node:test";
import assert from "node:assert/strict";
import { TELEMETRY_FIELDS, canSeeAdmin, parseAgentEvents, parseTelemetry } from "./admin.ts";

const good = Object.fromEntries(TELEMETRY_FIELDS.map((f, i) => [f, i + 1]));
const BAD = /amount|price|spend|cap|phone|name|card|pay|money|total/i;

test("parser drops money, phone and name fields", () => {
  const extra = { amount: 5, price: 1, unit_price: 2, spend: 3, cap: 4, phone: "+1555", phone_number: "+1555", display_name: "A", name: "B", card: "4242", payment_ref: "x" };
  const out = parseTelemetry({ ...good, ...extra })!;
  assert.deepEqual(Object.keys(out).sort(), [...TELEMETRY_FIELDS].sort());
  assert.equal(Object.keys(out).filter((k) => BAD.test(k)).length, 0);
  const ev = parseAgentEvents([{ agent: "buyer", events: 3, ...extra }]);
  assert.deepEqual(Object.keys(ev[0]!).sort(), ["agent", "events"]);
});

test("invalid or missing field gives null; bigint and camelCase accepted", () => {
  assert.equal(parseTelemetry({ ...good, bids: -1 }), null);
  assert.equal(parseTelemetry({ ...good, bids: NaN }), null);
  assert.equal(parseTelemetry({ ...good, bids: "3" }), null);
  const { errors: _e, ...missing } = good;
  assert.equal(parseTelemetry(missing), null);
  assert.equal(parseTelemetry(null), null);
  assert.equal(parseTelemetry({ ...good, bids: 7n })!.bids, 7);
  const camel = { accountsCreated: 1, goalsPosted: 2, roundsOpened: 3, roundsClosed: 4, bids: 5, shieldCatches: 6, callsPlaced: 7, approvals: 8, denials: 9, errors: 10, roundP50Ms: 11n, roundP95Ms: 12 };
  assert.equal(parseTelemetry(camel)!.round_p50_ms, 11);
});

test("parseAgentEvents sorts and drops bad rows", () => {
  const out = parseAgentEvents([{ agent: "a", events: 1 }, { agent: "b", events: 5n }, { agent: 3, events: 9 }, { agent: "c", events: -1 }, null]);
  assert.deepEqual(out, [{ agent: "b", events: 5 }, { agent: "a", events: 1 }]);
});

test("canSeeAdmin allows only owner and referee", () => {
  assert.equal(canSeeAdmin([{ role: "owner" }]), true);
  assert.equal(canSeeAdmin([{ role: "referee" }]), true);
  for (const role of ["buyer", "seller_screen", "scheduler"]) assert.equal(canSeeAdmin([{ role }]), false);
  assert.equal(canSeeAdmin([]), false);
});
