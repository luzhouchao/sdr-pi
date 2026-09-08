import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSurveyRequest, validateSurveyParameters } from '../src/survey-parameters.mjs';
const request = {protocol_version:1,operation:'survey_parameters',request_id:91,start_hz:2400000000,stop_hz:2483500000,step_hz:null,dwell_ms:null,gain_db:null};
test('survey preview permits independently fixed values and enforces them', () => {
  const r = parseSurveyRequest(JSON.stringify({...request,step_hz:1000000}));
  assert.deepEqual(validateSurveyParameters({step_hz:1000000,dwell_ms:10,gain_db:20},r),{step_hz:1000000,dwell_ms:10,gain_db:20});
  assert.throws(()=>validateSurveyParameters({step_hz:8000000,dwell_ms:10,gain_db:20},r),/fixed/);
});
test('rejects malformed, extra, null and out-of-budget model suggestions', () => {
  for (const params of [{step_hz:8000000,dwell_ms:10,gain_db:null},{step_hz:1000,dwell_ms:10,gain_db:20},{step_hz:8000001,dwell_ms:10,gain_db:20},{step_hz:8000000,dwell_ms:10,gain_db:20,action:'hold'}]) assert.throws(()=>validateSurveyParameters(params,request));
  assert.throws(()=>parseSurveyRequest(JSON.stringify({...request,start_hz:1})));
  const wide = {...request,start_hz:70000000,stop_hz:6000000000};
  assert.throws(()=>validateSurveyParameters({step_hz:8000000,dwell_ms:1000,gain_db:20},wide),/300 seconds/);
  assert.doesNotThrow(()=>validateSurveyParameters({step_hz:8000000,dwell_ms:5,gain_db:20},wide));
});
