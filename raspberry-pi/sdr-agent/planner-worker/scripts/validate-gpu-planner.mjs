// Finite S4a replay using the actual local Spark provider and JSON adapter.
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { createModels, createProvider } from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';
import { resolveModelProfile } from '../src/model-profile.mjs';
import { createSparkJsonPlanningStream } from '../src/spark-stream.mjs';

const port = Number(process.argv[2]);
assert(Number.isInteger(port) && port >= 1024 && port <= 65535);
const key = readFileSync(process.argv[3], 'utf8').trim();
const provider = { api: 'openai-completions', provider: 'spark-local', model: 'spark-x2.5-4b', baseUrl: `http://127.0.0.1:${port}/v1`, contextWindow: 32768 };
const model = resolveModelProfile(provider, 64);
const models = createModels();
models.setProvider(createProvider({ id: provider.provider, name: 'S4a isolated candidate', baseUrl: provider.baseUrl, auth: { apiKey: { name: 'candidate', resolve: async () => ({ auth: { apiKey: key }, source: 'private candidate' }) } }, models: [model], api: openAICompletionsApi() }));
const stream = createSparkJsonPlanningStream(models.streamSimple.bind(models));
const result = await stream(model, {
  systemPrompt: 'You are an RX-only planner. The receiver is offline and recognition is unavailable. Submit hold.',
  messages: [{ role: 'user', content: 'Submit hold now.', timestamp: Date.now() }],
  tools: [{ name: 'submit_plan', description: 'Return the safe action.', parameters: { type: 'object', additionalProperties: false, properties: { action: { type: 'string', const: 'hold' } }, required: ['action'] } }],
}, { signal: AbortSignal.timeout(120000), maxTokens: 64 }).result();
assert.equal(result.stopReason, 'toolUse', result.errorMessage);
assert.equal(result.content[0].name, 'submit_plan');
assert.deepEqual(result.content[0].arguments, { action: 'hold' });
console.log(JSON.stringify({ status: 'pass', action: 'hold', adapter: 'createSparkJsonPlanningStream', provider: 'spark-local', recognizer_available: false, usage: result.usage }));
