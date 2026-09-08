import { Type } from 'typebox';

export const surveyParametersSchema = Type.Object({
  step_hz: Type.Integer({ minimum: 1000, maximum: 8000000 }),
  dwell_ms: Type.Integer({ minimum: 0, maximum: 1000 }),
  gain_db: Type.Integer({ minimum: 0, maximum: 60 }),
}, { additionalProperties: false });

export function parseSurveyRequest(frame) {
  const request = JSON.parse(frame);
  const keys = ['protocol_version', 'operation', 'request_id', 'start_hz', 'stop_hz', 'step_hz', 'dwell_ms', 'gain_db'];
  if (!request || Object.keys(request).sort().join() !== keys.sort().join()
      || request.protocol_version !== 1 || request.operation !== 'survey_parameters'
      || !Number.isSafeInteger(request.request_id) || request.request_id < 1
      || !Number.isSafeInteger(request.start_hz) || !Number.isSafeInteger(request.stop_hz)
      || request.start_hz < 70000000 || request.stop_hz > 6000000000 || request.start_hz > request.stop_hz) {
    throw new Error('invalid survey parameter request');
  }
  for (const [key, min, max] of [['step_hz', 1000, 8000000], ['dwell_ms', 0, 1000], ['gain_db', 0, 60]]) {
    const value = request[key];
    if (value !== null && (!Number.isSafeInteger(value) || value < min || value > max)) throw new Error(`invalid ${key}`);
  }
  return request;
}

export function validateSurveyParameters(params, request) {
  if (!params || Object.keys(params).sort().join() !== 'dwell_ms,gain_db,step_hz') throw new Error('invalid survey parameters');
  parseSurveyRequest(JSON.stringify({ ...request, ...params }));
  for (const key of ['step_hz', 'dwell_ms', 'gain_db']) {
    if (params[key] === null || (request[key] !== null && params[key] !== request[key])) throw new Error(`model changed fixed ${key}`);
  }
  const points = Math.ceil((request.stop_hz - request.start_hz) / params.step_hz) + 1;
  if (points > 768 || points * (params.dwell_ms + 250) > 300000) throw new Error('model survey exceeds 768 points or 300 seconds');
  return params;
}

export const surveyParametersPrompt = `You suggest parameters for a receive-only first spectrum survey. Return exactly one submit_plan tool call with step_hz, dwell_ms and gain_db. This is a settings preview: you cannot execute hardware. The user supplies immutable start_hz and stop_hz. A null parameter means choose it; preserve every non-null parameter exactly. Use integer Hz/ms/dB. Fixed sample rate and bandwidth: 10000000 Hz; 4096 complex int16 samples per point. Step 1000..8000000 Hz, dwell 0..1000 ms, gain 0..60 dB. Points = ceil((stop_hz-start_hz)/step_hz)+1, at most 768; points*(dwell_ms+250) <= 300000 ms. Prefer a coarse initial survey with <=8 MHz spacing, short settling (5-20 ms), conservative fixed gain near 20 dB unless justified by the supplied band. Do not claim an optimal gain or measured RF quality: no RF measurement is available. Do not search the web or propose another action.`;
