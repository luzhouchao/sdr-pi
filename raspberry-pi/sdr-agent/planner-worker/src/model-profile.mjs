import { getBuiltinModel } from "@earendil-works/pi-ai/providers/all";

export function resolveModelProfile(providerConfig, maxTokens) {
  const builtin = getBuiltinModel(providerConfig.provider, providerConfig.model);
  const matchesBuiltin = builtin !== undefined &&
    builtin.api === providerConfig.api &&
    normalizeBaseUrl(builtin.baseUrl) === normalizeBaseUrl(providerConfig.baseUrl);
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
