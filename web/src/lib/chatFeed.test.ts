import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chatFromScript, isThinking, maskDigits, parseChat } from "./chatFeed.ts";
import { SIM_RUN, floorScript } from "../components/floor/floorPhases.ts";
import { SAMPLES } from "./arenaFixture.ts";

test("maskDigits hides phone numbers, codes and ids, keeps prices and models", () => {
  assert.equal(maskDigits("Call 4155551234"), "Call ••••");
  assert.equal(maskDigits("code 482 913"), "code ••••");
  assert.equal(maskDigits("+1 415-555-1234"), "+••••");
  assert.equal(maskDigits("$1,299.99"), "$1,299.99");
  assert.equal(maskDigits("RTX 5070"), "RTX 5070");
  assert.equal(maskDigits("RTX 5070 Ti under $1,400 by Friday"), "RTX 5070 Ti under $1,400 by Friday");
  assert.ok(!/\d{6}/.test(maskDigits("pi_3Nx0abc1234567890Zq")));
  assert.equal(maskDigits("pi_3NxABC123456"), "pi_3NxABC••••");
});

test("parseChat is tolerant and masks", () => {
  assert.deepEqual(parseChat(null, false), []);
  assert.deepEqual(parseChat({ a: 1 }, false), []);
  assert.deepEqual(parseChat("nope", true), []);
  const rows = parseChat([
    { at: "t1", who: "buyer", name: "Fish Market Buyer", text: "Call 4155551234", kind: "message" },
    { at: "t2", who: "shield", text: "ok", kind: "weird" },
    { at: "t3", who: "buyer" },
    { at: "t4", text: "no who" },
    null,
    { at: "t5", who: "advocate", name: "Advocate", text: "thinking", kind: "thinking" },
  ], false);
  assert.equal(rows.length, 3);
  assert.equal(rows[0]!.text, "Call ••••");
  assert.equal(rows[0]!.id, "t1|buyer|0");
  assert.equal(rows[1]!.kind, "message");
  assert.equal(rows[1]!.name, "shield");
  assert.equal(rows[2]!.kind, "thinking");
  assert.ok(rows.every((r) => r.sim === false));
});

test("the sample chat parses whole and carries no raw digit runs", () => {
  const json = JSON.parse(readFileSync(new URL("./fixtures/chat.sample.json", import.meta.url), "utf8"));
  const rows = parseChat(json, true);
  assert.equal(rows.length, json.length);
  assert.ok(rows.length >= 10 && rows.length <= 14);
  assert.ok(rows.every((r) => r.text === maskDigits(r.text) && !/\d{6}/.test(r.text)));
});

test("chatFromScript follows SIM_RUN", () => {
  assert.deepEqual(chatFromScript(SIM_RUN, -1), []);
  const thinkAt = SIM_RUN.phases.find((p) => p.think?.who === "buyer")!.at;
  const dots = chatFromScript(SIM_RUN, thinkAt + 0.1);
  assert.equal(isThinking(dots, "buyer"), true);
  const full = chatFromScript(SIM_RUN, SIM_RUN.duration);
  assert.equal(isThinking(full, "buyer"), false);
  assert.ok(full.every((l) => l.sim));
  assert.ok(full.some((l) => l.who === "buyer" && /^Reading your goal/.test(l.text)));
  assert.ok(full.some((l) => l.who === "shield" && /^Blocked /.test(l.text)));
  assert.ok(full.some((l) => l.who === "advocate"));
  assert.ok(full.some((l) => l.who === "referee" && /^Winner/.test(l.text)));
  assert.ok(full.some((l) => l.who === "buyer" && /^Bought /.test(l.text)));
  const texts = full.filter((l) => l.kind === "message").map((l) => l.text);
  assert.equal(new Set(texts).size, texts.length, "no repeated lines");
  const times = full.map((l) => l.at);
  assert.deepEqual(times, [...times].sort());
  assert.equal(new Set(full.map((l) => l.id)).size, full.length);
});

test("chatFromScript for a real round has thinking beats and no leaked price before reveal", () => {
  const s = floorScript(SAMPLES.gpu);
  const lines = chatFromScript(s, s.duration);
  assert.ok(lines.some((l) => l.who === "buyer" && /^Reading your goal/.test(l.text)));
  assert.ok(lines.some((l) => l.who === "shield" && /^Blocked /.test(l.text)));
  assert.ok(lines.some((l) => l.who === "advocate" && /refurbished/.test(l.text)));
  assert.ok(lines.some((l) => l.who === "buyer" && /^Bought /.test(l.text)));
});

test("isThinking looks at the agent's last line only", () => {
  const l = (who: string, kind: "message" | "thinking") => ({ id: who + kind, at: "", who, name: who, text: "x", kind, sim: true });
  assert.equal(isThinking([l("a", "thinking")], "a"), true);
  assert.equal(isThinking([l("a", "thinking"), l("a", "message")], "a"), false);
  assert.equal(isThinking([l("a", "thinking"), l("b", "message")], "a"), true);
  assert.equal(isThinking([], "a"), false);
});
