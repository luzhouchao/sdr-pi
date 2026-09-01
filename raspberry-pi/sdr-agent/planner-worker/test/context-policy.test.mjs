import assert from "node:assert/strict";
import test from "node:test";
import { compactPlanningContext } from "../src/context-policy.mjs";

function user(text) {
  return { role: "user", content: [{ type: "text", text }], timestamp: Date.now() };
}

test("keeps context below the default 90 percent threshold", () => {
  const messages = [user("short context")];
  assert.equal(compactPlanningContext(messages, 8_192), messages);
});

test("drops obsolete planning turns at the configured context boundary", () => {
  const newest = user("newest validated PlanningContext");
  const messages = [user("old context"), user("x".repeat(40_000)), newest];
  assert.deepEqual(compactPlanningContext(messages, 8_192, 90), [newest]);
});

test("rejects unbounded context and compression settings", () => {
  assert.throws(() => compactPlanningContext([], 8_191, 90), /outside/u);
  assert.throws(() => compactPlanningContext([], 8_192, 96), /outside/u);
});
