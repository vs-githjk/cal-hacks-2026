// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { cleanSignUp, gateRoute, pairCodeToSend, signUpErrorText } from "./signUp.ts";

const buyer = [{ role: "buyer", subjectId: "b-1" }];
const seller = [{ role: "seller", subjectId: "s-1" }];

test("gateRoute: not connected or roles not ready is connecting", () => {
  assert.equal(gateRoute(false, true, buyer, false), "connecting");
  assert.equal(gateRoute(true, false, [], false), "connecting");
  assert.equal(gateRoute(false, false, [], true), "connecting");
});

test("gateRoute: a buyer role goes to the buyer view, even with pair asked", () => {
  assert.equal(gateRoute(true, true, buyer, false), "buyer");
  assert.equal(gateRoute(true, true, buyer, true), "buyer");
});

test("gateRoute: a stale token (connected, ready, no roles) shows sign-up", () => {
  assert.equal(gateRoute(true, true, [], false), "signup");
});

test("gateRoute: wanting a pairing code, or holding a non-buyer role, shows pairing", () => {
  assert.equal(gateRoute(true, true, [], true), "pair");
  assert.equal(gateRoute(true, true, seller, false), "pair");
  assert.equal(gateRoute(true, true, [...buyer, { role: "buyer", subjectId: "b-2" }], false), "pair");
});

test("signUpErrorText maps throttle, already and empty, and passes other text through", () => {
  assert.match(signUpErrorText("Throttled: try later"), /Lots of people/);
  assert.match(signUpErrorText("too many sign-ups"), /Lots of people/);
  assert.match(signUpErrorText("rate limit"), /Lots of people/);
  assert.match(signUpErrorText("identity already has a role"), /already has an account/);
  assert.equal(signUpErrorText(""), "Sign-up failed. Try again.");
  assert.equal(signUpErrorText("boom"), "boom");
  // The market's own SenderError texts (sign_up_buyer), and a market that does not have the reducer yet.
  assert.match(signUpErrorText("already signed up: this identity is a seller"), /already has an account/);
  assert.match(signUpErrorText("sign-ups are busy right now, try again in a few minutes"), /Lots of people/);
  assert.equal(signUpErrorText("display name required"), "Enter a name.");
  assert.match(signUpErrorText("phone must be 7 to 20 digits, optionally starting with +"), /country code/);
  assert.equal(signUpErrorText("No such reducer sign_up_buyer"), "Sign-up is not live on this market yet.");
});

test("cleanSignUp: name is required and capped", () => {
  assert.deepEqual(cleanSignUp("  ", ""), { error: "Enter a name." });
  assert.deepEqual(cleanSignUp("x".repeat(41), ""), { error: "Keep the name under 40 characters." });
  assert.deepEqual(cleanSignUp(" Asha ", ""), { displayName: "Asha" });
  assert.deepEqual(cleanSignUp("x".repeat(40), "   "), { displayName: "x".repeat(40) });
});

test("cleanSignUp: US numbers become E.164, other countries need a plus", () => {
  assert.deepEqual(cleanSignUp("Asha", "(415) 555-0100"), { displayName: "Asha", phone: "+14155550100" });
  assert.deepEqual(cleanSignUp("Asha", "1 415 555 0100"), { displayName: "Asha", phone: "+14155550100" });
  assert.deepEqual(cleanSignUp("Asha", "+44 20 7946 0958"), { displayName: "Asha", phone: "+442079460958" });
  assert.deepEqual(cleanSignUp("Asha", "   "), { displayName: "Asha" });
  const err = { error: "Add your country code, like +44 20 7946 0958, or leave it blank." };
  assert.deepEqual(cleanSignUp("Asha", "+0123"), err);
  assert.deepEqual(cleanSignUp("Asha", "12345"), err);
});

test("signUpErrorText: the market's E.164 phone refusal reads plainly", () => {
  assert.match(signUpErrorText("phone must start with + and a country code, like +14155550100"), /country code/);
});

test("pairCodeToSend uppercases, drops inner spaces and keeps the hyphen", () => {
  assert.equal(pairCodeToSend("DJAAG-FRM3M"), "DJAAG-FRM3M");
  assert.equal(pairCodeToSend("djaag-frm3m"), "DJAAG-FRM3M");
  assert.equal(pairCodeToSend(" djaag frm3m "), "DJAAGFRM3M");
});

test("pairCodeToSend returns null when nothing is left after the market's normalization", () => {
  assert.equal(pairCodeToSend(""), null);
  assert.equal(pairCodeToSend("   "), null);
  assert.equal(pairCodeToSend("--"), null);
});
