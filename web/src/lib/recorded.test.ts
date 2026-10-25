// Run with: npm test --prefix web (node --test, no extra dependency).
// #398: the hosted /sell and /hyphenate show a recorded SIM snapshot instead of fetching 127.0.0.1.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseSnapshot } from "./hyphenate.ts";
import { parseNeeds, parseShops } from "./sellerKit.ts";
import { recordedLine } from "./recorded.ts";

const load = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));

test("the recorded Hyphenate snapshot parses, has orders and decisions, and is SIM", () => {
  const f = load("hyphenate-recorded.json");
  assert.equal(f.origin, "SIM");
  const s = parseSnapshot(f.raw);
  assert.ok(s && s.pos.length > 0 && s.decisions.length > 0);
});

test("the recorded Seller Kit snapshot parses into SIM open needs", () => {
  const f = load("sell-recorded.json");
  assert.equal(f.origin, "SIM");
  const needs = parseNeeds(f.needs);
  assert.ok(needs.length > 0 && needs.every((n) => n.origin === "SIM"));
  assert.ok(Array.isArray(parseShops(f.shops)));
});

test("no recorded snapshot links to a loopback address a visitor cannot open", () => {
  for (const name of ["hyphenate-recorded.json", "sell-recorded.json"])
    assert.doesNotMatch(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"), /127\.0\.0\.1|localhost|\[::1\]/, name);
});

test("recordedLine labels a snapshot SIM with its UTC capture time", () => {
  assert.equal(recordedLine("2026-10-25T06:03:14Z"), "Recorded snapshot (SIM), captured Oct 25, 2026, 06:03 UTC. The live version runs locally.");
});

test("recordedLine never claims a time it cannot read", () => {
  assert.equal(recordedLine("not a time"), "Recorded snapshot (SIM), capture time unknown. The live version runs locally.");
});

test("the recorded Hyphenate snapshot and its screen name no teammate: the requester is the buyer (#412)", () => {
  const fixture = readFileSync(new URL("./fixtures/hyphenate-recorded.json", import.meta.url), "utf8");
  assert.doesNotMatch(fixture, /vidyut|vedant/i);
  const screen = readFileSync(new URL("../components/hyphenate.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(screen, /vidyut|vedant/i);
  const s = parseSnapshot(load("hyphenate-recorded.json").raw)!;
  assert.ok(s.company.people.some((p) => p.name === "The buyer"));
});
