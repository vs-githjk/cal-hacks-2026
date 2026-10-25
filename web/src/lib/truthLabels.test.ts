// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { featuredOrder, parseLot, STAGE_LINE } from "./lot.ts";
import { lossReports, round, sellerLines, learning } from "./sample.ts";
import { originCounts } from "./screens.ts";
import { sourceText } from "./url.ts";

const order = (id: string, label: string) => ({ id, label, origin: "SIM", name: id, cap: 1300, conditions: ["new"] });

test("Lot: the scripted demo goal is labelled SIM, never REAL, and the stage line says so", () => {
  const lot = parseLot({ orders: [order("vidyut-5070ti", "REAL"), order("b7-00", "SIM")] })!;
  assert.ok(lot.orders.every((o) => o.label === "SIM"));
  assert.equal(featuredOrder(lot).id, "vidyut-5070ti");
  assert.ok(!/\breal\b/i.test(STAGE_LINE) && STAGE_LINE.includes("SIM"));
});

test("Lot: still needs exactly one featured order", () => {
  assert.equal(parseLot({ orders: [order("a", "SIM"), order("b", "SIM")] }), null);
  assert.equal(parseLot({ orders: [order("a", "REAL"), order("b", "REAL")] }), null);
});

const SAMPLE = JSON.stringify({ lossReports, round, sellerLines, learning });

test("Market sample uses only the four current sellers and none of the retired or old-roster names", () => {
  for (const gone of ["Silicon Sally", "Bay Area PC Shop", "Shady Sam", "Gadget Grove", "Fair Price", "Lowball", "Bargain Bin", "Best Buy"]) assert.ok(!SAMPLE.includes(gone), gone);
  const names = new Set(sellerLines.map((l) => l.seller));
  assert.deepEqual([...names].sort(), ["Byte Bros Outlet", "Central Comp", "FlashDeal Frankie", "ReNew Refurb"]);
});

test("Market sample: the MIRROR store is MIRROR, scripted sellers are SIM, and the winner is $1,299.99", () => {
  const origin = (s: string) => sellerLines.find((l) => l.seller === s)!.origin;
  assert.equal(origin("Central Comp"), "MIRROR");
  for (const s of ["Byte Bros Outlet", "FlashDeal Frankie", "ReNew Refurb"]) assert.equal(origin(s), "SIM", s);
  assert.equal(lossReports.find((r) => r.seller === "Central Comp")!.origin, "MIRROR");
  assert.deepEqual(originCounts(round.arrivals), { LIVE: 0, MIRROR: 1, SIM: 3 });
  const won = sellerLines.filter((l) => l.outcome.kind === "won");
  assert.deepEqual(won.map((l) => [l.seller, l.landed]), [["Byte Bros Outlet", 1299.99]]);
});

test("Market sample shows no loopback address", () => {
  assert.ok(!/127\.0\.0\.1|localhost/.test(SAMPLE));
});

test("sourceText hides a loopback source from a hosted page and keeps it on a loopback page", () => {
  const lb = "http://127.0.0.1:8765/shady-sam.html";
  assert.ok(!sourceText(lb, "tech-bazaar.vercel.app").includes("127.0.0.1"));
  assert.ok(!sourceText(lb, "").includes("127.0.0.1"));
  assert.equal(sourceText(lb, "localhost"), "127.0.0.1:8765/shady-sam.html");
  assert.equal(sourceText("https://www.ebay.com/itm/1?x=2", "tech-bazaar.vercel.app"), "ebay.com/itm/1");
  assert.equal(sourceText("not a url", "x.app"), "not a url");
});
