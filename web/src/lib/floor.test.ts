// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { FIXED_ACTORS, MAX_SELLERS, actorFor } from "./floor.ts";

const sellers = new Set(["gadget-grove", "lowball"]);

test("services own their kinds: verdict is the Shield, advocate and claim rows are the advocate", () => {
  assert.equal(actorFor({ kind: "verdict", sellerId: "gadget-grove" }, sellers), "shield");
  assert.equal(actorFor({ kind: "advocate_card", sellerId: "gadget-grove" }, sellers), "advocate");
  assert.equal(actorFor({ kind: "claim_checked", sellerId: "" }, sellers), "advocate");
});

test("a sealed or rejected bid moves the seller it names, if that seller has a character", () => {
  assert.equal(actorFor({ kind: "bid_sealed", sellerId: "gadget-grove" }, sellers), "seller:gadget-grove");
  assert.equal(actorFor({ kind: "bid_rejected", sellerId: "lowball" }, sellers), "seller:lowball");
  assert.equal(actorFor({ kind: "bid_sealed", sellerId: "unknown-shop" }, sellers), "referee");
});

test("buyer kinds move the buyer; anything else falls to the referee", () => {
  for (const kind of ["goal_posted", "need_posted", "mandate_created", "approval_recorded", "payment_recorded", "receiving_recorded"]) {
    assert.equal(actorFor({ kind, sellerId: "" }, sellers), "buyer", kind);
  }
  assert.equal(actorFor({ kind: "round_opened", sellerId: "" }, sellers), "referee");
  assert.equal(actorFor({ kind: "persona_set", sellerId: "lowball" }, sellers), "seller:lowball");
});

test("the floor has room for the 5 demo sellers beside the 4 fixed characters, all SIM", () => {
  assert.equal(MAX_SELLERS, 5);
  assert.deepEqual(FIXED_ACTORS.map((a) => a.key), ["buyer", "advocate", "shield", "referee"]);
  assert.ok(FIXED_ACTORS.every((a) => a.origin === "SIM"));
});
