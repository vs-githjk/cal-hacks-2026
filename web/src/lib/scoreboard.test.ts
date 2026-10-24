// Run with: npm test --prefix web. Fixture tiles follow contracts/Scoreboard.schema.json (SIM copies of data/scoreboard.json rows).
import { test } from "node:test";
import assert from "node:assert/strict";
import { SCOREBOARD_IDS, scoreboardTiles } from "./scoreboard.ts";

const tile = (over: Record<string, unknown> = {}) => ({
  id: "attacks_blocked", title: "Attacks blocked (held-out)", status: "measured", value: 0.6, unit: "ratio",
  display: "12 of 20 held-out attacks stopped; 2 of 10 honest listings wrongly blocked", count: 20,
  date_range: { from: "2026-10-24T16:29:09+00:00", to: "2026-10-24T16:29:09+00:00" }, origin: "SIM", source_run: "python3 -m shield.bench", note: "", ...over,
});
const board = (tiles: unknown[]) => ({ generated_at: "2026-10-24T16:29:09+00:00", tiles });

test("the four tiles in contract order, each with display, count, date range and origin", () => {
  const all = SCOREBOARD_IDS.map((id) => tile({ id }));
  const t = scoreboardTiles(board([...all].reverse().concat([tile({ id: "voice_attacks" })])));
  assert.deepEqual(t.map((x) => x.id), ["verified_savings", "attacks_blocked", "fit_accuracy", "learning_lift"]);
  assert.deepEqual(t[1], {
    id: "attacks_blocked", title: "Attacks blocked (held-out)", value: "60%", statusText: null,
    display: "12 of 20 held-out attacks stopped; 2 of 10 honest listings wrongly blocked", count: 20, range: "Oct 24", origin: "SIM",
  });
});

test("a null value shows its status text, never a number", () => {
  const [t] = scoreboardTiles(board([tile({ id: "learning_lift", status: "not_quotable", value: null, unit: "points" })]));
  assert.equal(t!.value, null);
  assert.equal(t!.statusText, "Not quotable");
  assert.equal(scoreboardTiles(board([tile({ id: "verified_savings", status: "none_yet", value: null, unit: "USD" })]))[0]!.statusText, "None yet");
});

test("units format honestly; a range over two days shows both; an unknown origin is SIM", () => {
  const [usd] = scoreboardTiles(board([tile({ id: "verified_savings", value: 125.5, unit: "USD", origin: "live?" })]));
  assert.equal(usd!.value, "$125.50");
  assert.equal(usd!.origin, "SIM");
  const [pts] = scoreboardTiles(board([tile({ id: "learning_lift", value: 0.37, unit: "points", date_range: { from: "2026-10-23", to: "2026-10-24" } })]));
  assert.equal(pts!.value, "+0.37 pts");
  assert.equal(pts!.range, "Oct 23 to Oct 24");
});

test("a missing or malformed file gives no tiles rather than a crash", () => {
  assert.deepEqual(scoreboardTiles(null), []);
  assert.deepEqual(scoreboardTiles({ tiles: "x" }), []);
});
