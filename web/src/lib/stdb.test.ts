import assert from "node:assert/strict";
import { test } from "node:test";
import { stdbUri } from "./stdbUri.ts";

test("unset env connects to the loopback database only on a local page", () => {
  assert.equal(stdbUri(undefined, "localhost"), "ws://127.0.0.1:3000");
  assert.equal(stdbUri("", "127.0.0.1"), "ws://127.0.0.1:3000");
  assert.equal(stdbUri(undefined, "[::1]"), "ws://127.0.0.1:3000");
  assert.equal(stdbUri(undefined, "app.localhost"), "ws://127.0.0.1:3000");
});

test("a deployed page never gets a loopback database", () => {
  assert.equal(stdbUri(undefined, "tech-bazaar.vercel.app"), null);
  assert.equal(stdbUri("", "judge.example"), null);
  assert.equal(stdbUri("ws://127.0.0.1:3000", "tech-bazaar.vercel.app"), null);
  assert.equal(stdbUri("ws://localhost:3000", "tech-bazaar.vercel.app"), null);
  assert.equal(stdbUri("ws://[::1]:3000", "tech-bazaar.vercel.app"), null);
  assert.equal(stdbUri("http://127.0.0.1:3000", "judge.example"), null);
});

test("a remote database passes through, and a loopback one is kept on a local page", () => {
  assert.equal(stdbUri("wss://maincloud.spacetimedb.com", "tech-bazaar.vercel.app"), "wss://maincloud.spacetimedb.com");
  assert.equal(stdbUri("ws://127.0.0.1:3000", "localhost"), "ws://127.0.0.1:3000");
  assert.equal(stdbUri("ws://localhost:3000", "[::1]"), "ws://localhost:3000");
});
