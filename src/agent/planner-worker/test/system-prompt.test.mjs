import assert from "node:assert/strict";
import test from "node:test";
import { PLANNER_SYSTEM_PROMPT } from "../src/system-prompt.mjs";

test("system prompt names live SDR observations and every hard planning boundary", () => {
  for (const required of [
    "observation.health",
    "observation.candidates",
    "observation.latest_sweep",
    "70,000,000–6,000,000,000 Hz",
    "2,100,000–30,720,000 Hz",
    "4 bytes per sample",
    "4,096-complex-sample inline-IQ window",
    "at most 768 points",
    "80 percent",
    "fixed_gain_db",
    "limits.min_freq_hz",
    "limits.max_freq_hz",
    "limits.max_span_hz",
    "limits.max_bandwidth_hz",
    "max_dwell_ms",
    "max_iq_samples",
    "max_iq_bytes",
    "auto_approve_iq_bytes",
    "max_observation_age_ms",
    "Never invent a signal",
    "Never transmit",
    "same language as the latest operator instruction",
    "For greetings, status questions and explanations",
    "submit hold",
    "natural non-empty reason",
    "Controller will show the exact parameters and any approval gate",
  ]) {
    assert.match(PLANNER_SYSTEM_PROMPT, new RegExp(required, "u"));
  }
});
