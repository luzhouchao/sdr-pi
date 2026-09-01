import { existsSync, lstatSync, readFileSync } from "node:fs";

export const PROVIDER_CONFIG_SCHEMA_VERSION = 1;
export const PROVIDER_CONFIG_MAX_BYTES = 8 * 1024;
export const SUPPORTED_PROVIDER_APIS = new Set(["openai-completions", "openai-responses"]);
export const DEFAULT_CONTEXT_WINDOW = 196_608;
export const DEFAULT_COMPRESSION_THRESHOLD_PERCENT = 90;

export function loadProviderSelection(config) {
  if (config.providerConfigPath && existsSync(config.providerConfigPath)) {
    return loadPrivateProviderFile(config.providerConfigPath);
  }
  return validateProviderSelection({
    api: config.api,
    base_url: config.baseUrl,
    provider: config.provider,
    model: config.model,
    api_key: config.apiKey,
    api_key_source: config.apiKeySource,
    context_window: config.contextWindow,
    compression_threshold_percent: config.compressionThresholdPercent,
  });
}

export function loadPrivateProviderFile(path) {
  const metadata = lstatSync(path);
  if (!metadata.isFile()) throw new Error("provider config must be a regular file");
  if (metadata.size > PROVIDER_CONFIG_MAX_BYTES) {
    throw new Error("provider config exceeds 8 KiB");
  }
  if ((metadata.mode & 0o077) !== 0) {
    throw new Error("provider config must not be accessible by group or other users");
  }
  if (process.getuid && metadata.uid !== process.getuid()) {
    throw new Error("provider config must be owned by the Planner user");
  }
  const value = JSON.parse(readFileSync(path, "utf8"));
  requirePlainObject(value, "provider config");
  requireExactKeys(
    value,
    ["schema_version", "api", "base_url", "provider", "model", "api_key"],
    "provider config",
    ["context_window", "compression_threshold_percent", "initial_survey"],
  );
  if (value.schema_version !== PROVIDER_CONFIG_SCHEMA_VERSION) {
    throw new Error("unsupported provider config schema version");
  }
  if (value.initial_survey !== undefined) validateInitialSurvey(value.initial_survey);
  return validateProviderSelection({
    ...value,
    api_key_source: "private provider config",
  });
}

function validateInitialSurvey(value) {
  requirePlainObject(value, "initial_survey");
  requireExactKeys(
    value,
    ["mode", "start_hz", "stop_hz", "step_hz", "dwell_ms"],
    "initial_survey",
    ["gain_db"],
  );
  if (!["full_band", "custom_band", "disabled"].includes(value.mode)) {
    throw new Error("initial_survey mode is unsupported");
  }
  for (const key of ["start_hz", "stop_hz", "step_hz", "dwell_ms"]) {
    if (!Number.isSafeInteger(value[key]) || value[key] < 0) {
      throw new Error(`initial_survey ${key} must be a non-negative integer`);
    }
  }
  if (value.gain_db !== undefined && (!Number.isSafeInteger(value.gain_db) || value.gain_db < 0 || value.gain_db > 60)) {
    throw new Error("initial_survey gain_db must be an integer between 0 and 60");
  }
}

export function validateProviderSelection(value) {
  if (!SUPPORTED_PROVIDER_APIS.has(value.api)) {
    throw new Error("provider api must be openai-completions or openai-responses");
  }
  const baseUrl = validateBaseUrl(value.base_url);
  const provider = requireIdentifier(value.provider, "provider", 64);
  const model = requirePrintable(value.model, "model", 256);
  const apiKey = requirePrintable(value.api_key, "api_key", 4_096);
  const contextWindow = requireBoundedInteger(
    value.context_window ?? DEFAULT_CONTEXT_WINDOW,
    "context_window",
    8_192,
    1_000_000,
  );
  const compressionThresholdPercent = requireBoundedInteger(
    value.compression_threshold_percent ?? DEFAULT_COMPRESSION_THRESHOLD_PERCENT,
    "compression_threshold_percent",
    50,
    95,
  );
  return {
    api: value.api,
    baseUrl,
    provider,
    model,
    apiKey,
    apiKeySource: value.api_key_source || "configured API key",
    contextWindow,
    compressionThresholdPercent,
  };
}

export function validateBaseUrl(value) {
  const input = requirePrintable(value, "base_url", 2_048);
  let url;
  try {
    url = new URL(input);
  } catch {
    throw new Error("base_url must be an absolute HTTP(S) URL");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("base_url must not contain credentials, query, or fragment");
  }
  const hostname = url.hostname.toLowerCase();
  const loopback = hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
  if (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) {
    throw new Error("base_url must use HTTPS except for a loopback endpoint");
  }
  return url.toString().replace(/\/+$/u, "");
}

function requireIdentifier(value, label, maximumBytes) {
  const text = requirePrintable(value, label, maximumBytes);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(text)) {
    throw new Error(`${label} contains unsupported characters`);
  }
  return text;
}

function requirePrintable(value, label, maximumBytes) {
  if (
    typeof value !== "string" ||
    value.trim().length === 0 ||
    Buffer.byteLength(value, "utf8") > maximumBytes ||
    /[\u0000-\u001f\u007f]/u.test(value)
  ) {
    throw new Error(`${label} must contain 1 to ${maximumBytes} printable bytes`);
  }
  return value.trim();
}

function requireExactKeys(value, keys, label, optionalKeys = []) {
  const expected = new Set([...keys, ...optionalKeys]);
  for (const key of Object.keys(value)) {
    if (!expected.has(key)) throw new Error(`${label} contains unknown field ${key}`);
  }
  for (const key of keys) {
    if (!Object.hasOwn(value, key)) throw new Error(`${label} is missing field ${key}`);
  }
}

function requireBoundedInteger(value, label, minimum, maximum) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${label} must be an integer between ${minimum} and ${maximum}`);
  }
  return value;
}

function requirePlainObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
}
