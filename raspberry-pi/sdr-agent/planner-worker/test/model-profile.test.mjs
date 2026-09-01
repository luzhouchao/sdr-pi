import assert from "node:assert/strict";
import test from "node:test";
import { resolveModelProfile } from "../src/model-profile.mjs";

test("preserves builtin OpenCode tool compatibility while honoring operator context", () => {
  const model = resolveModelProfile({
    api: "openai-responses",
    baseUrl: "https://opencode.ai/zen/v1",
    provider: "opencode",
    model: "gpt-5.6-sol",
    contextWindow: 196_608,
  }, 1_024);

  assert.equal(model.reasoning, true);
  assert.deepEqual(model.input, ["text", "image"]);
  assert.equal(model.compat.supportsOpenAIGrammarTools, true);
  assert.equal(model.compat.sessionAffinityFormat, "openai-nosession");
  assert.equal(model.contextWindow, 196_608);
  assert.equal(model.maxTokens, 1_024);
});

test("preserves the OpenCode Go reasoning-content compatibility profile", () => {
  const model = resolveModelProfile({
    api: "openai-completions",
    baseUrl: "https://opencode.ai/zen/go/v1",
    provider: "opencode-go",
    model: "deepseek-v4-flash",
    contextWindow: 196_608,
  }, 1_024);

  assert.equal(model.reasoning, true);
  assert.equal(model.compat.requiresReasoningContentOnAssistantMessages, true);
  assert.equal(model.compat.thinkingFormat, "deepseek");
  assert.equal(model.contextWindow, 196_608);
  assert.equal(model.maxTokens, 1_024);
});

test("uses a conservative profile when endpoint or protocol does not match the catalog", () => {
  const model = resolveModelProfile({
    api: "openai-completions",
    baseUrl: "https://proxy.example/v1",
    provider: "opencode",
    model: "gpt-5.6-sol",
    contextWindow: 65_536,
  }, 2_048);

  assert.equal(model.reasoning, false);
  assert.deepEqual(model.input, ["text"]);
  assert.equal(model.compat.supportsDeveloperRole, false);
  assert.equal(model.contextWindow, 65_536);
  assert.equal(model.maxTokens, 2_048);
});
