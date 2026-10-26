import { getBuiltinModel } from "@earendil-works/pi-ai/providers/all";

// Keep saved official Zen endpoints working without redirecting operator
// traffic when Pi's catalog moves to /inference. This only affects metadata.
const legacyBaseUrls = {
  opencode: "https://opencode.ai/zen/v1",
  "opencode-go": "https://opencode.ai/zen/go/v1",
};

// Removed from Pi 1.4's Go catalog. Preserve the previously supported profile
// only for this exact provider/model/official legacy endpoint combination.
const legacyGoFlash = {
  api: "openai-completions",
  baseUrl: legacyBaseUrls["opencode-go"],
  reasoning: true,
  input: ["text"],
  cost: { input: 0.22, output: 0.66, cacheRead: 0.007, cacheWrite: 0 },
  compat: {
    supportsStore: false,
    supportsDeveloperRole: false,
    maxTokensField: "max_tokens",
    requiresReasoningContentOnAssistantMessages: true,
    thinkingFormat: "deepseek",
  },
  maxTokens: 384_000,
  thinkingLevelMap: { minimal: null, low: "low", medium: null, high: "high", max: "max" },
};

export function resolveModelProfile(providerConfig, maxTokens) {
  const builtin = getBuiltinModel(providerConfig.provider, providerConfig.model) ?? (
    providerConfig.provider === "opencode-go" && providerConfig.model === "deepseek-v4-flash"
      ? legacyGoFlash
      : undefined
  );
  const selectedUrl = normalizeBaseUrl(providerConfig.baseUrl);
  const legacyUrl = legacyBaseUrls[providerConfig.provider];
  const matchesBuiltin = builtin !== undefined &&
    builtin.api === providerConfig.api &&
    (normalizeBaseUrl(builtin.baseUrl) === selectedUrl ||
      (legacyUrl !== undefined && legacyUrl === selectedUrl));
  const fallbackCompat = providerConfig.api === "openai-completions"
    ? {
        supportsStore: false,
        supportsDeveloperRole: false,
        supportsReasoningEffort: false,
        supportsUsageInStreaming: false,
        supportsStrictMode: false,
        maxTokensField: "max_tokens",
      }
    : {
        supportsStore: false,
        supportsStrictMode: false,
      };
  const base = matchesBuiltin
    ? builtin
    : {
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        compat: fallbackCompat,
      };

  return {
    ...base,
    id: providerConfig.model,
    name: providerConfig.model,
    api: providerConfig.api,
    provider: providerConfig.provider,
    baseUrl: providerConfig.baseUrl,
    contextWindow: providerConfig.contextWindow,
    maxTokens: Math.min(maxTokens, base.maxTokens ?? maxTokens),
  };
}

function normalizeBaseUrl(value) {
  return value.replace(/\/+$/u, "");
}
