import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  loadPrivateProviderFile,
  validateBaseUrl,
  validateProviderSelection,
} from "../src/provider-config.mjs";

test("accepts OpenCode through the Pi AI Responses protocol", () => {
  const selected = validateProviderSelection({
    api: "openai-responses",
    base_url: "https://opencode.ai/zen/v1",
    provider: "opencode",
    model: "gpt-5.6-sol",
    api_key: "test-key",
  });
  assert.equal(selected.api, "openai-responses");
  assert.equal(selected.baseUrl, "https://opencode.ai/zen/v1");
  assert.equal(selected.apiKey, "test-key");
});

test("permits HTTP only for loopback providers", () => {
  assert.equal(validateBaseUrl("http://127.0.0.1:8000/v1"), "http://127.0.0.1:8000/v1");
  assert.throws(() => validateBaseUrl("http://api.example.com/v1"), /must use HTTPS/u);
  assert.throws(() => validateBaseUrl("https://key@example.com/v1"), /must not contain credentials/u);
});

test("rejects loose permissions and unknown private config fields", (context) => {
  const directory = mkdtempSync(join(tmpdir(), "sdr-provider-config-"));
  context.after(() => rmSync(directory, { recursive: true }));
  const path = join(directory, "provider.json");
  const config = {
    schema_version: 1,
    api: "openai-completions",
    base_url: "https://api.example.com/v1",
    provider: "example",
    model: "example-model",
    api_key: "test-key",
  };
  writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
  assert.equal(loadPrivateProviderFile(path).model, "example-model");
  chmodSync(path, 0o644);
  assert.throws(() => loadPrivateProviderFile(path), /must not be accessible/u);
  chmodSync(path, 0o600);
  writeFileSync(path, JSON.stringify({ ...config, shell: true }), { mode: 0o600 });
  assert.throws(() => loadPrivateProviderFile(path), /unknown field shell/u);
});
