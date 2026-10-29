import assert from "node:assert/strict";
import test from "node:test";
import { compactPlanningContext } from "../src/context-policy.mjs";
import { getCurrentSystemPrompt, getCurrentTools } from "@earendil-works/pi-ai";

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

test("compaction preserves replayed Pi system rules and current tool declarations", () => {
  const tool = { name: "submit_plan", description: "plan", parameters: { type: "object" } };
  const newest = user("current validated snapshot");
  const messages = [
    { role: "system", content: "hardware rules", toolsAdded: [tool], timestamp: 0 },
    user("x".repeat(40_000)),
    { role: "system", content: "latest rules", toolsRemoved: [{ name: "submit_plan" }],
      toolsAdded: [{ ...tool, description: "current plan" }], timestamp: 1 },
    newest,
  ];
  const compacted = compactPlanningContext(messages, 8_192);
  assert.equal(compacted.length, 2);
  assert.equal(compacted[1], newest);
  assert.equal(getCurrentSystemPrompt(compacted), "hardware rules\n\nlatest rules");
  assert.deepEqual(getCurrentTools(compacted), [{ ...tool, description: "current plan" }]);
});
