// Run with: npm test --prefix web. Judge fix 3: the sponsor proof lines on a locked part (Bright Data re-check, Tiger Data 7 and 30 day history).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseBuildView, toBuildResult } from "./buildView.ts";
import { brightDataLine, tigerLine, proofFor, agoText } from "./proof.ts";

const sample = JSON.parse(readFileSync(new URL("../../../contracts/samples/build-board.sample.json", import.meta.url), "utf8"));
const NOW = Date.parse("2026-10-24T23:50:30Z");

function withProof(over: Record<string, unknown>, partKey = "gpu") {
  const v = structuredClone(sample);
  const p = v.parts.find((x: { part: string }) => x.part === partKey);
  Object.assign(p, over.part ?? {});
  if (over.liveCheck !== undefined) p.champion.liveCheck = over.liveCheck;
  p.champion.origin = over.championOrigin ?? "MIRROR";
  return v;
}

test("agoText: seconds under two minutes, then minutes, then hours; a future time is 0 s, never negative", () => {
  assert.equal(agoText(0), "0 s ago");
  assert.equal(agoText(12), "12 s ago");
  assert.equal(agoText(119), "119 s ago");
  assert.equal(agoText(120), "2 min ago");
  assert.equal(agoText(3 * 3600 + 5), "3 h ago");
});

test("a LIVE read this run says Bright Data checked Ns ago, with its time from the feed", () => {
  const l = brightDataLine({ state: "ok", origin: "LIVE", source: "Bright Data", fetchedAt: "2026-10-24T23:50:00Z" }, "MIRROR", NOW);
  assert.deepEqual(l, { text: "Bright Data checked 30 s ago", origin: "LIVE", read: true });
  assert.equal(brightDataLine({ state: "ok", origin: "LIVE", source: "Bright Data", fetchedAt: "2026-10-24T23:51:00Z" }, "MIRROR", NOW).text, "Bright Data checked 0 s ago");
});

test("a LIVE label with a time nobody can read never claims a number of seconds", () => {
  const l = brightDataLine({ state: "ok", origin: "LIVE", source: "Bright Data", fetchedAt: "yesterday-ish" }, "MIRROR", NOW);
  assert.equal(l.read, true);
  assert.ok(!/\d+ s ago/.test(l.text) && l.text.includes("time unknown"));
});

test("no read says the price was not re-read, and why in plain words, labelled MIRROR and never LIVE", () => {
  const why = (state: string) => brightDataLine({ state: state as never, origin: "MIRROR", source: "Bright Data" }, "MIRROR", NOW);
  assert.deepEqual(why("empty"), { text: "price not re-read (Bright Data returned nothing)", origin: "MIRROR", read: false });
  assert.equal(why("slow").text, "price not re-read (Bright Data was too slow)");
  assert.equal(why("not_configured").text, "price not re-read (Bright Data is not set up on this run)");
  assert.equal(why("skipped").text, "price not re-read (the re-check was off)");
  assert.equal(why("stock_unknown").origin, "MIRROR");
});

test("a MIRROR claim of LIVE without a time is not trusted: no fetchedAt means not read", () => {
  const l = brightDataLine({ state: "ok", origin: "LIVE", source: "Bright Data" }, "MIRROR", NOW);
  assert.equal(l.read, false);
  assert.equal(l.origin, "MIRROR");
});

test("no liveCheck at all: a real listing says the re-check did not run, a SIM seller says there is no listing to re-read", () => {
  assert.equal(brightDataLine(undefined, "MIRROR", NOW).text, "price not re-read (the re-check did not run)");
  assert.equal(brightDataLine(undefined, "SIM", NOW).text, "SIM seller: no real listing to re-read");
  assert.equal(brightDataLine(undefined, "SIM", NOW).origin, "SIM");
});

test("Tiger: both windows with data give low and median, labelled with the feed's origin", () => {
  const l = tigerLine({ state: "ok", origin: "MIRROR", windows: [{ days: 7, low: 1199, median: 1249.5, n: 4, daysOfData: 7 }, { days: 30, low: 1149, median: 1270, n: 9, daysOfData: 30 }] });
  assert.equal(l.text, "Tiger Data: 7-day low $1,199 and median $1,249.50; 30-day low $1,149 and median $1,270");
  assert.equal(l.origin, "MIRROR");
  assert.equal(l.read, true);
});

test("Tiger: a young history says how many days it really holds; a missing window says so", () => {
  const young = tigerLine({ state: "ok", origin: "SIM", windows: [{ days: 7, low: 100, median: 110, n: 2, daysOfData: 3 }, { days: 30, low: 100, median: 110, n: 2, daysOfData: 3 }] });
  assert.ok(young.text.includes("7-day low $100 and median $110 (only 3 days of data)"));
  assert.ok(young.text.includes("30-day low $100 and median $110 (only 3 days of data)"));
  const half = tigerLine({ state: "ok", origin: "MIRROR", windows: [{ days: 30, low: 100, median: 110, n: 2, daysOfData: 30 }] });
  assert.ok(half.text.startsWith("Tiger Data: 7-day no history yet; 30-day low $100"));
});

test("Tiger: no history, not connected and a failed read are each said honestly with no numbers", () => {
  assert.deepEqual(tigerLine({ state: "no_data", origin: "SIM", windows: [] }), { text: "Tiger Data: no 7-day or 30-day history yet for this part", origin: "SIM", read: false });
  assert.equal(tigerLine({ state: "not_configured", origin: "SIM", windows: [] }).text, "Tiger Data: no 7-day or 30-day history (not connected on this run)");
  assert.equal(tigerLine({ state: "error", origin: "SIM", windows: [] }).text, "Tiger Data: no 7-day or 30-day history (the read failed)");
  assert.equal(tigerLine(undefined).text, "Tiger Data: no 7-day or 30-day history read yet");
  assert.equal(tigerLine(undefined).read, false);
});

test("parse: a feed liveCheck and history reach the panel's part keys; bad ones are dropped, never repaired, and the part still parses", () => {
  const good = withProof({
    liveCheck: { state: "ok", origin: "LIVE", source: "Bright Data", fetchedAt: "2026-10-24T23:50:00Z" },
    part: { history: { state: "ok", origin: "MIRROR", windows: [{ days: 7, low: 1199, median: 1249, n: 4, daysOfData: 7 }] } },
  });
  const v = parseBuildView(good);
  assert.equal(v.rejected, 0);
  const b = toBuildResult(v);
  const gpu = proofFor(b, "gpu", NOW);
  assert.equal(gpu.bright.text, "Bright Data checked 30 s ago");
  assert.equal(gpu.bright.origin, "LIVE");
  assert.ok(gpu.tiger.text.startsWith("Tiger Data: 7-day low $1,199 and median $1,249; 30-day no history yet"));

  const bad = parseBuildView(withProof({ liveCheck: { state: "wow", origin: "LIVE" }, part: { history: { state: "ok", origin: "MIRROR", windows: [{ days: "7" }, { days: 30, low: -1, median: 1, n: 1, daysOfData: 1 }] } } }));
  assert.equal(bad.rejected, 0);
  const g2 = proofFor(toBuildResult(bad), "gpu", NOW);
  assert.equal(g2.bright.text, "price not re-read (the re-check did not run)");
  assert.equal(g2.tiger.read, false);
});

test("a live origin on a Tiger read is clamped to MIRROR in the panel too", () => {
  const v = parseBuildView(withProof({ part: { history: { state: "ok", origin: "LIVE", windows: [{ days: 7, low: 1, median: 2, n: 1, daysOfData: 7 }] } } }));
  assert.equal(proofFor(toBuildResult(v), "gpu", NOW).tiger.origin, "MIRROR");
});

test("a part without a champion has no proof lines", () => {
  const v = structuredClone(sample);
  const cpu = v.parts.find((x: { part: string }) => x.part === "cpu");
  cpu.status = "bidding";
  delete cpu.champion;
  assert.equal(proofFor(toBuildResult(parseBuildView(v)), "cpu", NOW), null);
});
