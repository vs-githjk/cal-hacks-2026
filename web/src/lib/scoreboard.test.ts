// Run with: npm test --prefix web. The landing's numbers come from the scoreboard copy in fixtures/; this keeps it identical to data/scoreboard.json.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { proofStats } from "./scoreboard.ts";

const here = new URL("./", import.meta.url);

test("the fixture copy of the scoreboard is byte-identical to data/scoreboard.json", () => {
  const fixture = readFileSync(new URL("fixtures/scoreboard.json", here), "utf8");
  const source = readFileSync(new URL("../../../data/scoreboard.json", here), "utf8");
  assert.equal(fixture, source, "run: cp data/scoreboard.json web/src/lib/fixtures/scoreboard.json");
});

test("the three landing numbers are computed from measured tiles, with their caveats", () => {
  const [fit, attacks, voice] = proofStats("Smell Test");
  assert.equal(fit!.value, "39 of 39");
  assert.ok(fit!.measured);
  assert.equal(attacks!.value, "13 of 20");
  assert.match(attacks!.caveat, /held-out, rules only; 2 of 10 honest pages blocked/);
  assert.equal(voice!.value, "9 of 10");
  assert.equal(voice!.caveat, "first run");
});
