// S4b read-only planning load through the actual local Spark SDK adapter.
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { createModels, createProvider } from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';
import { resolveModelProfile } from '../src/model-profile.mjs';
import { createSparkJsonPlanningStream } from '../src/spark-stream.mjs';

const port = Number(process.argv[2]);
assert(Number.isInteger(port) && port >= 1024 && port <= 65535);
const key = readFileSync(process.argv[3], 'utf8').trim();
const observation = JSON.parse(readFileSync(process.argv[4], 'utf8'));
assert.equal(observation.status, 'unavailable');
const historyBytes = Number(process.argv[5]);
assert([0, 2048, 8192, 16384].includes(historyBytes));
const history = 'Previous synthetic observation was unavailable; hold without RF execution.\n'.repeat(240).slice(0, historyBytes);
const provider = { api: 'openai-completions', provider: 'spark-local', model: 'spark-x2.5-4b', baseUrl: `http://127.0.0.1:${port}/v1`, contextWindow: 32768 };
const model = resolveModelProfile(provider, 512);
const models = createModels();
models.setProvider(createProvider({ id: provider.provider, name: 'S4b isolated candidate', baseUrl: provider.baseUrl, auth: { apiKey: { name: 'candidate', resolve: async () => ({ auth: { apiKey: key }, source: 'private candidate' }) } }, models: [model], api: openAICompletionsApi() }));
const stream = createSparkJsonPlanningStream(models.streamSimple.bind(models));
const result = await stream(model, {
  systemPrompt: 'You are an RX-only planner. This is synthetic replay, recognition is not admitted. Return only the hold action through submit_plan.',
  messages: [{ role: 'user', content: `${history}\nCurrent compact recognition: ${JSON.stringify(observation)}\nSubmit hold.`, timestamp: Date.now() }],
  tools: [{ name: 'submit_plan', description: 'Return the safe action.', parameters: { type: 'object', additionalProperties: false, properties: { action: { type: 'string', const: 'hold' } }, required: ['action'] } }],
}, { signal: AbortSignal.timeout(60000), maxTokens: 512 }).result();
assert.equal(result.stopReason, 'toolUse', result.errorMessage);
assert.equal(result.content[0].name, 'submit_plan');
assert.deepEqual(result.content[0].arguments, { action: 'hold' });
console.log(JSON.stringify({ status: 'pass', action: 'hold', history_bytes: historyBytes, recognizer_available: false, usage: result.usage }));
