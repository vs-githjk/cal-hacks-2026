// Run with: npm test --prefix web (node --test, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { postGoalErrorText, POST_GOAL_FALLBACK } from "./composerError.ts";

// #449 PL-13: the composer never shows a reducer's own words, which carry buyer ids, goal ids and function names.
test("#449 PL-13 postGoalErrorText turns each market refusal into a plain sentence with no ids", () => {
  const raw = [
    "not allowed: post_goal for b_ab12cd34; this buyer acts only for b_zz99yy88",
    "goal g_abc123def already exists",
    "goal cap must be positive",
    "deadline must be an ISO datetime, for example 2026-10-30T23:59:00Z",
    "goal item gpu-rtx5070ti-retail: quantity must be a number above 0",
    "WebSocket connection closed",
    "No such reducer post_goal",
    "SenderError: agent1qabcdefghijklmnopqrstuvwx said no (0xdeadbeef)",
  ];
  for (const r of raw) {
    const text = postGoalErrorText(new Error(r));
    assert.match(text, /^[A-Z][^_]*\.$/, text);
    assert.doesNotMatch(text, /b_[a-z0-9]{8}|g_[a-z0-9]|agent1q|SenderError|post_goal|reducer|ISO|0x|gpu-rtx/i, `${r} -> ${text}`);
  }
});

test("#449 PL-13 postGoalErrorText maps the known refusals and falls back for everything else, never echoing the raw text", () => {
  assert.match(postGoalErrorText(new Error("not allowed: post_goal for b_x; this buyer acts only for b_y")), /Refresh the page/);
  assert.match(postGoalErrorText(new Error("goal g_1 already exists")), /already sent/);
  assert.match(postGoalErrorText(new Error("goal cap must be positive")), /top price/);
  assert.match(postGoalErrorText(new Error("WebSocket connection closed")), /not reachable/);
  assert.equal(postGoalErrorText(new Error("boom 7731")), POST_GOAL_FALLBACK);
  assert.equal(postGoalErrorText(new Error("")), POST_GOAL_FALLBACK);
  assert.equal(postGoalErrorText("string thrown"), POST_GOAL_FALLBACK);
  assert.equal(postGoalErrorText(undefined), POST_GOAL_FALLBACK);
});
