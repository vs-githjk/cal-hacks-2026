// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  GOAL_COMMAND,
  GoalSubmitError,
  SPEECH_TRANSPORT,
  SpeechError,
  applyDictation,
  buildGoalRequest,
  canFindOffers,
  catalogSku,
  postGoalArgs,
  dictate,
  draftFor,
  fallbackMessage,
  parseStoredDraft,
  submitGoal,
  type GoalCommand,
  type GoalDraft,
  type GoalRequest,
} from "./goalRequest.ts";

const TODAY = new Date(2026, 9, 24, 12, 0, 0); // local noon, 24 Oct 2026
const draft = (over: Partial<GoalDraft> = {}): GoalDraft => ({ text: "RTX 5070 under $650", cap: "", deadline: "", conditions: [], ...over });
const build = (over: Partial<GoalDraft> = {}) => buildGoalRequest(draft(over), "req-1", TODAY);
const request = (over: Partial<GoalRequest> = {}): GoalRequest => ({ requestId: "req-1", requestText: "RTX 5070 Ti", cap: null, deadline: null, conditions: [], ownedPartIds: [], ...over });
const problemFields = (r: ReturnType<typeof build>) => (r.ok ? [] : r.problems.map((p) => p.field));

// ---- building the request: any product, exact words, no second parser

test("three different products build the same way and keep the buyer's exact words", () => {
  for (const text of ["RTX 5070", "Ryzen 7 9800X3D, boxed", "2 TB NVMe SSD, PCIe 4.0  (heatsink)\n"]) {
    const r = build({ text });
    assert.ok(r.ok, text);
    assert.equal(r.request.requestText, text, "not trimmed, reflowed or reworded");
    assert.equal(r.request.requestId, "req-1");
    assert.deepEqual(r.request.ownedPartIds, [], "no owned-parts source exists, so none is invented");
  }
});

test("a product the market may not stock still builds: the web cannot know inventory, the backend answers", () => {
  const r = build({ text: "a 40 foot yacht" });
  assert.ok(r.ok);
  assert.equal(r.request.requestText, "a 40 foot yacht");
});

test("the request text must say something and stay a sentence or two", () => {
  for (const text of ["", "   ", "\n\t "]) assert.deepEqual(problemFields(build({ text })), ["text"], JSON.stringify(text));
  assert.deepEqual(problemFields(build({ text: "x".repeat(501) })), ["text"]);
  assert.ok(build({ text: "x".repeat(500) }).ok);
});

test("budget cap: plain dollars only, a positive finite amount, or empty for none", () => {
  const cap = (s: string) => { const r = build({ cap: s }); return r.ok ? r.request.cap : "invalid"; };
  assert.equal(cap(""), null);
  assert.equal(cap("   "), null);
  assert.equal(cap("90"), 90);
  assert.equal(cap("1,300"), 1300);
  assert.equal(cap("$1,300"), 1300);
  assert.equal(cap("$ 90.50"), 90.5);
  assert.equal(cap("650.5"), 650.5);
  for (const bad of ["abc", "NaN", "Infinity", "-5", "0", "0.00", "1e3", "12.345", "1,3000", "$", "90 dollars", "1300 1300", "--5", "0x10"]) {
    assert.equal(cap(bad), "invalid", bad);
  }
});

test("needed-by date: a real calendar day from today on, as YYYY-MM-DD, or empty for none", () => {
  const day = (s: string) => { const r = build({ deadline: s }); return r.ok ? r.request.deadline : "invalid"; };
  assert.equal(day(""), null);
  assert.equal(day("2026-10-24"), "2026-10-24", "today is still allowed");
  assert.equal(day("2026-10-30"), "2026-10-30");
  assert.equal(day("2027-02-28"), "2027-02-28");
  for (const bad of ["garbage", "2026-13-01", "2026-02-30", "2026-10-23", "2025-12-31", "10/30/2026", "2026-10-30T23:59:00Z", "2026-1-5", "tomorrow"]) {
    assert.equal(day(bad), "invalid", bad);
  }
});

test("conditions come only from the market's vocabulary, once each, in a stable order", () => {
  const ok = build({ conditions: ["open-box", "new", "open-box"] });
  assert.ok(ok.ok);
  assert.deepEqual(ok.request.conditions, ["new", "open-box"]);
  assert.deepEqual(problemFields(build({ conditions: ["new", "mint"] })), ["conditions"]);
  assert.deepEqual(problemFields(build({ conditions: ["NEW"] })), ["conditions"]);
});

test("every problem is reported together, so one tap shows everything to fix", () => {
  assert.deepEqual(problemFields(build({ text: " ", cap: "abc", deadline: "garbage", conditions: ["mint"] })), ["text", "cap", "deadline", "conditions"]);
});

// ---- the draft survives pairing, and never reaches a different buyer

test("a draft written before pairing is adopted by the buyer who pairs, and by nobody else afterwards", () => {
  const typed = draft({ text: "2 TB NVMe SSD" });
  const before = { owner: null, draft: typed };
  assert.deepEqual(draftFor(before, null), typed, "still unpaired");
  assert.deepEqual(draftFor(before, "buyer-a"), typed, "the first buyer to pair keeps what they typed");
  const mine = { owner: "buyer-a", draft: typed };
  assert.deepEqual(draftFor(mine, "buyer-a"), typed);
  assert.equal(draftFor(mine, "buyer-b").text, "", "another buyer starts empty");
  assert.equal(draftFor(mine, null).text, "", "an unpaired screen never shows a buyer's draft");
  assert.equal(draftFor(null, "buyer-a").text, "");
});

test("a stored draft that is not exactly the saved shape is ignored", () => {
  const good = { owner: "buyer-a", draft: draft() };
  assert.deepEqual(parseStoredDraft(JSON.stringify(good)), good);
  assert.deepEqual(parseStoredDraft(JSON.stringify({ owner: null, draft: draft() })), { owner: null, draft: draft() });
  for (const raw of [null, "", "not json", "[]", "{}", JSON.stringify({ owner: 5, draft: draft() }), JSON.stringify({ owner: null, draft: { ...draft(), conditions: "new" } }), JSON.stringify({ owner: null, draft: { ...draft(), text: 3 } }), JSON.stringify({ owner: null, draft: { ...draft(), conditions: [1] } })]) {
    assert.equal(parseStoredDraft(raw), null, String(raw));
  }
});

// ---- the honest ASI:One route: plain words from the buyer's own inputs, nothing parsed or invented

test("the ASI:One message is the exact request, plus only the details the buyer filled in", () => {
  assert.equal(fallbackMessage(request({ requestText: "RTX 5070 under $650" })), "RTX 5070 under $650");
  assert.equal(
    fallbackMessage(request({ requestText: "RTX 5070", cap: 650, deadline: "2026-10-30", conditions: ["new", "open-box"] })),
    "RTX 5070\nBudget cap: $650\nNeeded by: 2026-10-30\nAcceptable conditions: new, open-box",
  );
  assert.equal(fallbackMessage(request({ requestText: "SSD", cap: 89.5 })), "SSD\nBudget cap: $89.50");
});

// ---- submitting: only a real, authenticated command counts, and only a goal id means success

const ok = (...answer: unknown[]): GoalCommand => async () => ({ goalId: answer.length ? answer[0] : "goal-1" });
const never: GoalCommand = (_req, signal) => new Promise((_res, rej) => signal.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError"))));
const kindOf = async (p: Promise<unknown>) => { try { await p; return "resolved"; } catch (e) { return e instanceof GoalSubmitError ? e.kind : `other:${String(e)}`; } };

test("no confirmed backend command exists yet, so submission is blocked and says so", async () => {
  assert.equal(GOAL_COMMAND, null);
  assert.equal(await kindOf(submitGoal(request())), "blocked");
  assert.equal(await kindOf(submitGoal(request(), undefined, { command: null })), "blocked");
});

test("success is a persisted goal id and nothing less", async () => {
  assert.deepEqual(await submitGoal(request({ requestId: "ok-1" }), undefined, { command: ok("goal-77") }), { goalId: "goal-77" });
  for (const [i, bad] of [undefined, null, "", "   ", 5, {}].entries()) {
    assert.equal(await kindOf(submitGoal(request({ requestId: `bad-${i}` }), undefined, { command: ok(bad) })), "rejected", String(bad));
  }
});

test("two taps on one request send it once and share the answer; a different request is its own call", async () => {
  let calls = 0;
  const slow: GoalCommand = async () => { calls++; await new Promise((r) => setTimeout(r, 30)); return { goalId: "goal-dup" }; };
  const a = request({ requestId: "dup-1" });
  const [x, y] = await Promise.all([submitGoal(a, undefined, { command: slow }), submitGoal(a, undefined, { command: slow })]);
  assert.equal(calls, 1);
  assert.deepEqual(x, y);
  await Promise.all([submitGoal(request({ requestId: "dup-2" }), undefined, { command: slow }), submitGoal(request({ requestId: "dup-3" }), undefined, { command: slow })]);
  assert.equal(calls, 3);
  await submitGoal(a, undefined, { command: slow });
  assert.equal(calls, 4, "once settled, the same request can be sent again");
});

test("no answer in time is reported as unknown, never as failed or sent, and a retry is allowed", async () => {
  let aborted = false;
  const cmd: GoalCommand = (req, signal) => { signal.addEventListener("abort", () => { aborted = true; }); return never(req, signal); };
  const err = await submitGoal(request({ requestId: "slow-1" }), undefined, { command: cmd, timeoutMs: 25 }).catch((e) => e);
  assert.ok(err instanceof GoalSubmitError);
  assert.equal(err.kind, "timeout");
  assert.match(err.message, /may or may not/);
  assert.ok(aborted, "the pending command is cancelled");
  assert.deepEqual(await submitGoal(request({ requestId: "slow-1" }), undefined, { command: ok("goal-retry") }), { goalId: "goal-retry" });
});

test("a pairing that ended mid-send and an item the market does not stock keep their own answers", async () => {
  const fail = (e: unknown): GoalCommand => async () => { throw e; };
  assert.equal(await kindOf(submitGoal(request({ requestId: "e1" }), undefined, { command: fail(new GoalSubmitError("sign_in", "pair again")) })), "sign_in");
  assert.equal(await kindOf(submitGoal(request({ requestId: "e2" }), undefined, { command: fail(new GoalSubmitError("unsupported", "not stocked")) })), "unsupported");
  assert.equal(await kindOf(submitGoal(request({ requestId: "e3" }), undefined, { command: fail(new TypeError("fetch failed")) })), "unreachable");
});

test("an identity switch cancels the send: the caller's abort reaches the command", async () => {
  const ctl = new AbortController();
  let commandSignal: AbortSignal | undefined;
  const cmd: GoalCommand = (req, signal) => { commandSignal = signal; return never(req, signal); };
  const pending = submitGoal(request({ requestId: "abort-1" }), ctl.signal, { command: cmd, timeoutMs: 5000 });
  ctl.abort();
  assert.equal(await kindOf(pending), "aborted");
  assert.ok(commandSignal!.aborted);
  const early = new AbortController();
  early.abort();
  assert.equal(await kindOf(submitGoal(request({ requestId: "abort-2" }), early.signal, { command: ok() })), "aborted", "already cancelled: nothing is sent");
});

// ---- speech: blocked today, and when a transport exists a refusal never takes typing away

test("no approved speech service exists yet, so voice entry is unavailable", async () => {
  assert.equal(SPEECH_TRANSPORT, null);
  await assert.rejects(dictate(null, new AbortController().signal), (e: unknown) => e instanceof SpeechError && e.kind === "unavailable");
});

test("denied microphone permission is its own answer and points back to typing", async () => {
  for (const name of ["NotAllowedError", "SecurityError", "PermissionDeniedError"]) {
    const t = { listen: async () => { throw new DOMException("no", name); } };
    const err = await dictate(t, new AbortController().signal).catch((e) => e);
    assert.ok(err instanceof SpeechError, name);
    assert.equal(err.kind, "denied");
    assert.match(err.message, /type/i);
  }
  const broken = { listen: async () => { throw new Error("service down"); } };
  await assert.rejects(dictate(broken, new AbortController().signal), (e: unknown) => e instanceof SpeechError && e.kind === "unavailable");
});

test("silence and cancelled listening return no text, and heard words are trimmed", async () => {
  await assert.rejects(dictate({ listen: async () => "  \n" }, new AbortController().signal), (e: unknown) => e instanceof SpeechError && e.kind === "no_speech");
  const ctl = new AbortController();
  const hang = { listen: (s: AbortSignal) => new Promise<string>((_r, rej) => s.addEventListener("abort", () => rej(new DOMException("a", "AbortError")))) };
  const p = dictate(hang, ctl.signal);
  ctl.abort();
  await assert.rejects(p, (e: unknown) => e instanceof SpeechError && e.kind === "aborted");
  assert.equal(await dictate({ listen: async () => "  a 1 TB NVMe drive " }, new AbortController().signal), "a 1 TB NVMe drive");
});

test("dictation fills the same request box and does nothing else", () => {
  assert.equal(applyDictation("", "RTX 5070"), "RTX 5070");
  assert.equal(applyDictation("RTX 5070", "under $650"), "RTX 5070 under $650");
  assert.equal(applyDictation("RTX 5070 ", "under $650"), "RTX 5070 under $650");
  assert.equal(applyDictation("RTX 5070\n", "under $650"), "RTX 5070\nunder $650");
});

test("every message the buyer can read here is free of em and en dashes", async () => {
  const msgs: string[] = [fallbackMessage(request({ cap: 5, deadline: "2026-10-30", conditions: ["new"] }))];
  const bad = build({ text: "", cap: "x", deadline: "y", conditions: ["z"] });
  if (!bad.ok) msgs.push(...bad.problems.map((p) => p.message));
  for (const e of [await submitGoal(request({ requestId: "d1" })).catch((e) => e), await submitGoal(request({ requestId: "d2" }), undefined, { command: never, timeoutMs: 10 }).catch((e) => e), await dictate(null, new AbortController().signal).catch((e) => e), await dictate({ listen: async () => { throw new DOMException("n", "NotAllowedError"); } }, new AbortController().signal).catch((e) => e)]) msgs.push((e as Error).message);
  assert.ok(msgs.length >= 8);
  for (const m of msgs) assert.doesNotMatch(m, /[\u2013\u2014]/, m);
});

// ---- posting the goal to the market (reducers.postGoal)

test("postGoalArgs maps a request with a cap and a deadline to the exact reducer args", () => {
  const args = postGoalArgs(request({ requestText: "  RTX 5070 Ti  ", cap: 650, deadline: "2026-11-02" }), "b_ab12cd34", TODAY);
  assert.deepEqual(args, {
    id: "g_req1",
    buyerId: "b_ab12cd34",
    type: "budget_cap",
    cap: 650,
    deadline: new Date(2026, 10, 2, 23, 59).toISOString(),
    poNumber: "",
    origin: "SIM",
    items: [{ skuSpec: "rtx 5070 ti", condition: "new", variant: "retail", quantity: 1, skippedOwnedPartId: "" }],
  });
});

test("postGoalArgs defaults the deadline to 7 days after today", () => {
  const args = postGoalArgs(request({ cap: 90 }), "b_ab12cd34", TODAY);
  assert.ok(!("error" in args));
  assert.equal(args.deadline, new Date(2026, 9, 31, 23, 59).toISOString());
  assert.match(args.deadline, /^\d{4}-\d{2}-\d{2}T/);
});

test("postGoalArgs asks for a cap instead of guessing one", () => {
  assert.deepEqual(postGoalArgs(request({ cap: null }), "b_ab12cd34", TODAY), { error: "Add a top price so sellers know your cap." });
});

test("postGoalArgs passes the first chosen condition through and makes a short safe id", () => {
  const args = postGoalArgs(request({ requestId: "3f2b8c1e-9a4d-4e7f-8b21-0c5d6e7f8a9b", cap: 90, conditions: ["refurbished", "used"] }), "b_ab12cd34", TODAY);
  assert.ok(!("error" in args));
  assert.equal(args.items[0]!.condition, "refurbished");
  assert.match(args.id, /^g_[A-Za-z0-9]{1,12}$/);
});

test("canFindOffers is true for a b_ buyer that is not busy, false for no buyer or while sending", () => {
  assert.equal(canFindOffers("b_ab12cd34", false), true);
  assert.equal(canFindOffers(null, false), false);
  assert.equal(canFindOffers("b_ab12cd34", true), false);
});

test("catalogSku maps typed part names to the exact seller sku", () => {
  const cases: [string, string | null][] = [
    ["RTX 5070 Ti", "rtx 5070 ti"],
    ["rtx5070ti under $900", "rtx 5070 ti"],
    ["4070 Super", "rtx 4070 super 12gb"],
    ["RX 7800 XT", "rx 7800 xt 16gb"],
    ["850W power supply", "psu 850w"],
    ["a power supply", "psu 750w"],
    ["mid-tower case", "case"],
    ["graphics card under $600", "rtx 4070 super 12gb"],
    ["RTX 5090", null],
    ["a keyboard", null],
    ["1000W power supply", null],
    ["650W PSU", null],
    ["tower cooler", null],
    ["RTX 5090 in a mid-tower case", null],
    ["850 W PSU", "psu 850w"],
  ];
  for (const [text, sku] of cases) assert.equal(catalogSku(text), sku, text);
});

test("postGoalArgs says plainly when sellers do not carry the part", () => {
  const args = postGoalArgs(request({ requestText: "a keyboard", cap: 90 }), "b_ab12cd34", TODAY);
  assert.ok("error" in args);
  assert.match(args.error, /don't carry that part/);
});

test("catalogSku: a price is not a GPU model", () => {
  assert.equal(catalogSku("graphics card under $1000"), "rtx 4070 super 12gb");
  assert.equal(catalogSku("a 5090 graphics card"), null);
});

test("a deadline of today picked at 7:30 pm is still in the future", () => {
  const evening = new Date(2026, 9, 24, 19, 30);
  const args = postGoalArgs(request({ cap: 90, deadline: "2026-10-24" }), "b_ab12cd34", evening);
  assert.ok(!("error" in args));
  assert.ok(Date.parse(args.deadline) > evening.getTime());
  assert.match(args.deadline, /^\d{4}-\d{2}-\d{2}T/);
});
