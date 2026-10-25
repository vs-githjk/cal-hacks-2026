import assert from "node:assert/strict";
import { test } from "node:test";
import { callReducer, cornerFromPoint, followBox, initialCall } from "./callState.ts";

test("default is floor big, tile top right", () => {
  assert.equal(initialCall.swapped, false);
  assert.equal(initialCall.corner, "tr");
});

test("toggle swaps and swaps back", () => {
  const a = callReducer(initialCall, { type: "toggle" });
  assert.equal(a.swapped, true);
  assert.equal(callReducer(a, { type: "toggle" }).swapped, false);
});

test("cornerFromPoint picks the nearest corner", () => {
  assert.equal(cornerFromPoint(900, 50, 1000, 600), "tr");
  assert.equal(cornerFromPoint(100, 50, 1000, 600), "tl");
  assert.equal(cornerFromPoint(900, 500, 1000, 600), "br");
  assert.equal(cornerFromPoint(100, 500, 1000, 600), "bl");
});

test("setCorner uses the drop point", () => {
  assert.equal(callReducer(initialCall, { type: "setCorner", x: 10, y: 590, w: 1000, h: 600 }).corner, "bl");
});

test("newLines: first batch is the baseline, later lines count while the chat is small", () => {
  let s = callReducer(initialCall, { type: "newLines", ids: ["a", "b"] });
  assert.equal(s.unread, 0);
  assert.equal(s.lastSeenId, "b");
  s = callReducer(s, { type: "newLines", ids: ["a", "b", "c", "d"] });
  assert.equal(s.unread, 2);
  s = callReducer(s, { type: "newLines", ids: ["a", "b", "c", "d"] });
  assert.equal(s.unread, 2);
});

test("newLines does not count while the chat is big, and opening resets", () => {
  let s = callReducer(initialCall, { type: "newLines", ids: ["a"] });
  s = callReducer(s, { type: "newLines", ids: ["a", "b"] });
  assert.equal(s.unread, 1);
  s = callReducer(s, { type: "toggle" });
  assert.equal(s.unread, 0);
  s = callReducer(s, { type: "newLines", ids: ["a", "b", "c"] });
  assert.equal(s.unread, 0);
  assert.equal(s.lastSeenId, "c");
});

test("followBox centres and clamps inside the stage", () => {
  assert.deepEqual(followBox(480, 270, 960, 540), [320, 170, 320, 200]);
  assert.deepEqual(followBox(10, 10, 960, 540), [0, 0, 320, 200]);
  assert.deepEqual(followBox(950, 530, 960, 540), [640, 340, 320, 200]);
});
