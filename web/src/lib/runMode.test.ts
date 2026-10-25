// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { connectionState } from "./runMode.ts";

test("connectionState: neutral connecting before the first connect, never a red flash", () => {
  assert.equal(connectionState(false, false), "connecting");
});

test("connectionState: live once the connection is active", () => {
  assert.equal(connectionState(true, false), "live");
  assert.equal(connectionState(true, true), "live");
});

test("connectionState: disconnected (red) only after a live connection has actually dropped", () => {
  assert.equal(connectionState(false, true), "disconnected");
});
