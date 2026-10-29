import assert from "node:assert/strict";
import test from "node:test";
import { resolveModelProfile } from "../src/model-profile.mjs";

test("preserves builtin OpenCode tool compatibility while honoring operator context", () => {
  const model = resolveModelProfile({
    api: "openai-responses",
    baseUrl: "https://opencode.ai/inference/v1",
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
    baseUrl: "https://opencode.ai/inference/go/v1",
    provider: "opencode-go",
    model: "deepseek-v4.1-flash",
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
    provider: "custom-proxy",
    model: "gpt-5.6-sol",
    contextWindow: 65_536,
  }, 2_048);

  assert.equal(model.reasoning, false);
  assert.deepEqual(model.input, ["text"]);
  assert.equal(model.compat.supportsDeveloperRole, false);
  assert.equal(model.contextWindow, 65_536);
  assert.equal(model.maxTokens, 2_048);
});

test("uses the new catalog endpoint without rewriting the operator's selection", () => {
  const model = resolveModelProfile({
    api: "openai-completions",
    baseUrl: "https://opencode.ai/inference/go/v1/",
    provider: "opencode-go",
    model: "deepseek-v4.1-flash",
    contextWindow: 32_768,
  }, 1_024);
  assert.equal(model.reasoning, true);
  assert.equal(model.compat.requiresReasoningContentOnAssistantMessages, true);
  assert.equal(model.baseUrl, "https://opencode.ai/inference/go/v1/");
});

test("rejects retired OpenCode models and endpoints instead of disabling thinking", () => {
  for (const [baseUrl, model] of [
    ["https://opencode.ai/zen/go/v1", "deepseek-v4.1-flash"],
    ["https://opencode.ai/inference/go/v1", "deepseek-v4-flash"],
  ]) {
    assert.throws(() => resolveModelProfile({api:"openai-completions",baseUrl,
      provider:"opencode-go",model,contextWindow:32768},1024), /current Pi model catalog/);
  }
});
