// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { clearCorner, cornerRect } from "./agents.ts";
import { STATUS_TEXT, agentLink, agentverseUrl, ago, feedBase, fetchAgents, headline, isStale, latestActivity, parseAgents, summary, type AgentRow } from "./agentFeed.ts";

const VIEW = { w: 1280, h: 800 };
const TILE = { w: 220, h: 120 };
// The /buyer hero card sits top right at 1280.
const HERO = { left: 760, top: 140, right: 1264, bottom: 420 };

test("a corner that does not touch the hero is kept", () => {
  assert.equal(clearCorner("br", TILE, VIEW, HERO), "br");
});

test("a corner over the hero moves to one that does not overlap, never back and forth", () => {
  const hero = { left: 1000, top: 60, right: 1280, bottom: 800 }; // a tall hero down the whole right side
  const c = clearCorner("tr", TILE, VIEW, hero);
  assert.ok(c === "tl" || c === "bl", `got ${c}`);
  assert.equal(clearCorner(c, TILE, VIEW, hero), c, "stable: a second check keeps the same corner");
});

test("when every corner overlaps, the current one stays (no loop)", () => {
  const all = { left: 0, top: 0, right: 1280, bottom: 800 };
  assert.equal(clearCorner("br", TILE, VIEW, all), "br");
});

test("cornerRect places the tile 16 px from the sides, below the header and above the footer", () => {
  assert.deepEqual(cornerRect("tl", TILE, VIEW), { left: 16, top: 76, right: 236, bottom: 196 });
  assert.deepEqual(cornerRect("br", TILE, VIEW), { left: 1044, top: 632, right: 1264, bottom: 752 });
});

// ---- Task 3: the Fetch tile and the agent directory read only what the feed recorded.

const NOW = Date.parse("2026-10-24T12:00:00Z");
const ADDR = "agent1qwxhy93uzmw5prlqldm8a2mz9gsmc2563um6th2l6z0pudw63juej97nmj8";
const row = (over: Partial<AgentRow> = {}): AgentRow => ({ name: "Buyer", role: "buyer", address: ADDR, status: "agentverse", last_message: "Goal set", at: "2026-10-24T11:59:00Z", origin: "SIM", avatar: null, ...over });

test("latestActivity picks the newest valid timestamp, not the last row in the array", () => {
  const rows = [
    row({ name: "old", at: "2026-10-24T09:00:00Z" }),
    row({ name: "newest", at: "2026-10-24T11:59:30Z" }),
    row({ name: "middle", at: "2026-10-24T11:00:00Z" }),
    row({ name: "listed last", at: "2026-10-24T08:00:00Z" }),
  ];
  assert.equal(latestActivity(rows)!.name, "newest");
  assert.equal(latestActivity([...rows].reverse())!.name, "newest");
});

test("latestActivity ignores missing and invalid times, rows that said nothing, and answers null when nothing qualifies", () => {
  const rows = [
    row({ name: "no time", at: null }),
    row({ name: "empty", at: "" }),
    row({ name: "garbage", at: "garbage" }),
    row({ name: "looks numeric", at: "1" }),
    row({ name: "bad month", at: "2026-13-45T00:00:00Z" }),
    row({ name: "silent", at: "2026-10-24T11:59:00Z", last_message: null }),
    row({ name: "blank", at: "2026-10-24T11:59:00Z", last_message: "   " }),
  ];
  assert.equal(latestActivity(rows), null);
  assert.equal(latestActivity([]), null);
  assert.equal(latestActivity([...rows, row({ name: "valid", at: "2026-10-24T01:00:00Z" })])!.name, "valid");
});

test("latestActivity keeps the first row on a tie, so the tile does not flicker between equal rows", () => {
  const rows = [row({ name: "a" }), row({ name: "b" })];
  assert.equal(latestActivity(rows)!.name, "a");
});

test("ago is empty for a time that is not a real ISO time, and counts real ones", () => {
  for (const at of [null, "", "garbage", "1", "2026-13-45T00:00:00Z"]) assert.equal(ago(at, NOW), "", String(at));
  assert.equal(ago("2026-10-24T11:59:56Z", NOW), "4s ago");
  assert.equal(ago("2026-10-24T11:50:00Z", NOW), "10m ago");
  assert.equal(ago("2026-10-24T09:00:00Z", NOW), "3h ago");
});

test("isStale: old or unreadable activity is never shown as current", () => {
  assert.equal(isStale("2026-10-24T11:55:00Z", NOW), false);
  assert.equal(isStale("2026-10-24T11:49:00Z", NOW), true, "over ten minutes");
  assert.equal(isStale(null, NOW), true);
  assert.equal(isStale("garbage", NOW), true);
  assert.equal(isStale("2026-10-24T12:00:30Z", NOW), false, "a few seconds of clock skew is not stale");
});

test("headline says what the feed said: checking, offline, nothing timestamped, or the latest activity with its age", () => {
  assert.equal(headline(undefined, NOW), "Checking agents");
  assert.equal(headline(null, NOW), "Agents offline");
  assert.equal(headline([], NOW), "No agents running");
  assert.equal(headline([row({ at: null })], NOW), "1 of 1 running, 1 with an Agentverse mailbox. No timestamped activity.");
  assert.equal(headline([row({ name: "Advocate", at: "2026-10-24T11:59:56Z" })], NOW), "Advocate, 4s ago");
  assert.equal(headline([row({ name: "Advocate", at: "2026-10-24T08:00:00Z" })], NOW), "Advocate, 4h ago (stale)");
});

test("statuses and the summary describe the run log, never verified online liveness", () => {
  assert.doesNotMatch(Object.values(STATUS_TEXT).join(" "), /online|verified|live/i);
  assert.equal(STATUS_TEXT.agentverse, "Mailbox running");
  assert.equal(STATUS_TEXT.local, "Running locally");
  assert.equal(STATUS_TEXT.down, "Not running");
  assert.equal(summary([row(), row({ status: "local" }), row({ status: "down" })]), "2 of 3 running, 1 with an Agentverse mailbox");
  assert.equal(summary([row({ status: "local" })]), "1 of 1 running, local only");
  assert.equal(summary([row({ status: "down" }), row({ status: "down" })]), "2 agents, none running");
});

test("parseAgents keeps well formed rows and only a real web address as an avatar", () => {
  const good = { name: "Buyer", role: "buyer", address: ADDR, status: "agentverse", last_message: "hi", at: "2026-10-24T11:59:00Z", origin: "SIM" };
  const parsed = parseAgents([
    good,
    { ...good, name: "with avatar", avatar: "https://example.com/buyer.png" },
    { ...good, name: "bad avatar", avatar: "javascript:alert(1)" },
    { ...good, name: "bare scheme", avatar: "https://" },
    { ...good, name: "numeric avatar", avatar: 5 },
    { ...good, name: "bad status", status: "online" },
    "row",
    null,
  ])!;
  assert.deepEqual(parsed.map((r) => r.name), ["Buyer", "with avatar", "bad avatar", "bare scheme", "numeric avatar"]);
  assert.deepEqual(parsed.map((r) => r.avatar), [null, "https://example.com/buyer.png", null, null, null]);
  assert.equal(parseAgents({ not: "an array" }), null);
});

test("agentLink: a profile link only for a mailbox-running agent with a well formed address", () => {
  assert.equal(agentLink(row()), `https://agentverse.ai/agents/details/${ADDR}/profile`);
  assert.equal(agentLink(row({ status: "local" })), null, "no mailbox, no registered profile to claim");
  assert.equal(agentLink(row({ status: "down" })), null);
  assert.equal(agentLink(row({ address: null })), null);
  for (const bad of ["", "not-an-address", "agent1q/../../evil", "agent1q?x=1", "agent1q x", "AGENT1QWXHY93UZMW5PRLQLDM8A2MZ9GSMC2563UM6TH2L6Z0PUDW63JUEJ97NMJ8", "https://evil.example/agent1qwxhy93uzmw5prlqldm8a2mz9gsmc2563um6th2l6z0pudw63juej97nmj8"]) {
    assert.equal(agentLink(row({ address: bad })), null, bad);
  }
  assert.equal(agentverseUrl("a/b?c"), "https://agentverse.ai/agents/details/a%2Fb%3Fc/profile", "still encoded as a path segment");
});

test("fetchAgents answers null for an offline feed: unreachable, HTTP error, not JSON, or not a list", async () => {
  const real = globalThis.fetch;
  try {
    for (const impl of [
      async () => { throw new TypeError("fetch failed"); },
      async () => new Response("{}", { status: 503 }),
      async () => new Response("<html>", { status: 200 }),
      async () => new Response(JSON.stringify({ rows: [] }), { status: 200 }),
    ]) {
      globalThis.fetch = impl as typeof fetch;
      assert.equal(await fetchAgents("http://feed.test"), null);
    }
    globalThis.fetch = (async () => new Response(JSON.stringify([{ name: "Buyer", role: "buyer", address: null, status: "down", last_message: null, at: null, origin: "SIM" }]), { status: 200 })) as typeof fetch;
    assert.equal((await fetchAgents("http://feed.test"))!.length, 1);
  } finally {
    globalThis.fetch = real;
  }
});

test("feedBase skips the fetch when unset or when a loopback feed is seen from a deployed page", () => {
  assert.equal(feedBase(undefined, "localhost"), null);
  assert.equal(feedBase("", "localhost"), null);
  assert.equal(feedBase("not a url", "localhost"), null);
  assert.equal(feedBase("http://127.0.0.1:8790", "tech-bazaar.vercel.app"), null);
  assert.equal(feedBase("http://localhost:8790", "judge.example"), null);
  assert.equal(feedBase("http://127.0.0.1:8790", "localhost"), "http://127.0.0.1:8790");
  assert.equal(feedBase("http://[::1]:8790", "127.0.0.1"), "http://[::1]:8790");
  assert.equal(feedBase("https://feed.example/", "tech-bazaar.vercel.app"), "https://feed.example");
});
