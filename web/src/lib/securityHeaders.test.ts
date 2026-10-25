// Run with: npm test --prefix web (node --test, no extra dependency).
// #449 PL-23: a conservative Content-Security-Policy and related headers, built from the same env the app reads.
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildCsp, securityHeaders } from "./securityHeaders.ts";

const MAINCLOUD = { NEXT_PUBLIC_SPACETIMEDB_URI: "wss://maincloud.spacetimedb.com" };
const directive = (csp: string, name: string) => csp.split(";").map((d) => d.trim()).find((d) => d === name || d.startsWith(`${name} `)) ?? "";
const sources = (csp: string, name: string) => directive(csp, name).split(/\s+/).slice(1);

test("the policy locks the page down to itself and allows only what the app uses", () => {
  const csp = buildCsp(MAINCLOUD, false);
  assert.deepEqual(sources(csp, "default-src"), ["'self'"]);
  assert.deepEqual(sources(csp, "object-src"), ["'none'"]);
  assert.deepEqual(sources(csp, "base-uri"), ["'self'"]);
  assert.deepEqual(sources(csp, "form-action"), ["'self'"]);
  assert.deepEqual(sources(csp, "frame-ancestors"), ["'none'"]);
  assert.deepEqual(sources(csp, "manifest-src"), ["'self'"]);
  assert.deepEqual(sources(csp, "worker-src"), ["'self'"]);
  assert.deepEqual(sources(csp, "font-src"), ["'self'", "data:"]);
});

test("scripts: self, the inline scripts Next writes, and eval (the SpacetimeDB SDK builds its deserializers with new Function)", () => {
  // Found by loading the production build in a browser: without 'unsafe-eval' the SDK throws EvalError and every page shows
  // "This page couldn't load". It is the price of the SDK, so it stays out of every other directive.
  for (const dev of [false, true]) assert.deepEqual(sources(buildCsp(MAINCLOUD, dev), "script-src"), ["'self'", "'unsafe-inline'", "'unsafe-eval'"]);
  assert.ok(!sources(buildCsp(MAINCLOUD, false), "default-src").includes("'unsafe-eval'"));
  assert.ok(!sources(buildCsp(MAINCLOUD, false), "style-src").includes("'unsafe-eval'"));
});

test("styles keep inline (React style props, Next); images allow https avatars, data and blob", () => {
  assert.deepEqual(sources(buildCsp(MAINCLOUD, false), "style-src"), ["'self'", "'unsafe-inline'"]);
  assert.deepEqual(sources(buildCsp(MAINCLOUD, false), "img-src"), ["'self'", "data:", "blob:", "https:"]);
});

test("connect-src: self, the SpacetimeDB Maincloud wss and https origins, and the local services", () => {
  const c = sources(buildCsp(MAINCLOUD, false), "connect-src");
  assert.ok(c.includes("'self'") && c.includes("wss://maincloud.spacetimedb.com") && c.includes("https://maincloud.spacetimedb.com"));
  for (const local of ["http://127.0.0.1:8790", "http://127.0.0.1:8791", "http://127.0.0.1:8789"]) assert.ok(c.includes(local), local);
  assert.ok(!c.includes("*") && !c.includes("wss:") && !c.includes("https:") && !c.includes("ws:"));
});

test("with no env the default local SpacetimeDB (ws://127.0.0.1:3000) is allowed over ws and http", () => {
  const c = sources(buildCsp({}, false), "connect-src");
  assert.ok(c.includes("ws://127.0.0.1:3000") && c.includes("http://127.0.0.1:3000"));
});

test("a plain-http SpacetimeDB or feed URI maps to its own origin (path and credentials dropped)", () => {
  const env = { NEXT_PUBLIC_SPACETIMEDB_URI: "ws://db.example.test:3001/v1/x", NEXT_PUBLIC_AGENT_FEED_URL: "https://feed.example.test/base?q=1" };
  const c = sources(buildCsp(env, false), "connect-src");
  assert.ok(c.includes("ws://db.example.test:3001") && c.includes("http://db.example.test:3001"));
  assert.ok(c.includes("https://feed.example.test") && !c.some((s) => s.includes("/base")));
});

test("a bad or hostile env value adds nothing and cannot add a directive", () => {
  for (const bad of ["", "not a url", "wss://a.test;script-src *", "javascript:alert(1)", "data:text/html,x", "ftp://x.test"]) {
    const csp = buildCsp({ NEXT_PUBLIC_SPACETIMEDB_URI: bad, NEXT_PUBLIC_AGENT_FEED_URL: bad, NEXT_PUBLIC_SELLER_KIT_URL: bad }, false);
    assert.ok(!csp.includes("script-src *") && !csp.includes("javascript:") && !csp.includes("ftp:"), bad);
    assert.deepEqual(sources(csp, "script-src"), ["'self'", "'unsafe-inline'", "'unsafe-eval'"], bad);
  }
});

test("the CSP has no dashes of the em or en kind and no wildcard source", () => {
  const csp = buildCsp(MAINCLOUD, false);
  assert.ok(!/[\u2014\u2013]/.test(csp));
  assert.ok(!/(^|\s)\*(\s|;|$)/.test(csp));
});

test("the other headers: nosniff, frame denial, referrer, permissions; HSTS only in production", () => {
  const prod = Object.fromEntries(securityHeaders(MAINCLOUD, false).map((h) => [h.key, h.value]));
  assert.equal(prod["X-Content-Type-Options"], "nosniff");
  assert.equal(prod["X-Frame-Options"], "DENY");
  assert.equal(prod["Referrer-Policy"], "strict-origin-when-cross-origin");
  assert.match(prod["Permissions-Policy"]!, /camera=\(\)/);
  assert.match(prod["Permissions-Policy"]!, /microphone=\(\)/);
  assert.match(prod["Permissions-Policy"]!, /geolocation=\(\)/);
  assert.match(prod["Strict-Transport-Security"]!, /^max-age=\d+$/);
  assert.equal(prod["Content-Security-Policy"], buildCsp(MAINCLOUD, false));
  const dev = Object.fromEntries(securityHeaders(MAINCLOUD, true).map((h) => [h.key, h.value]));
  assert.ok(!("Strict-Transport-Security" in dev));
});
