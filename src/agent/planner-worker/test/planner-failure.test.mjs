import assert from 'node:assert/strict';
import test from 'node:test';
import { describeMissingPlan, formatUpstreamError } from '../src/planner-failure.mjs';

test('provider errors are distinct from a successful response missing its tool', () => {
  const failed = {state:{messages:[{role:'assistant',stopReason:'error',errorMessage:'Connection error.'}]}};
  assert.match(describeMissingPlan(failed,[7]), /request=7.*连接失败/u);
  assert.doesNotMatch(describeMissingPlan(failed,[7]), /结束了本轮生成/u);
  assert.match(describeMissingPlan({state:{messages:[{role:'assistant',stopReason:'stop'}]}},[8]), /request=8.*没有提交下一步计划/u);
});

test('failure messages redact secrets and URLs before bounding their length', () => {
  const secret='private-test-key';
  const text=formatUpstreamError(`401 key=${secret}\nBearer token123 at https://user:pass@example.invalid/?key=${secret}`, [secret]);
  for (const value of [secret,'token123','user:pass','example.invalid','\n']) assert.equal(text.includes(value),false);
  assert.match(text,/401/u);
  assert.equal(formatUpstreamError('x'.repeat(900)).length,400);
});

test('length and abort cannot become accepted plans', () => {
  assert.match(describeMissingPlan({state:{messages:[{role:'assistant',stopReason:'length'}]}},[1]), /token 上限/u);
  assert.match(describeMissingPlan({state:{messages:[{role:'assistant',stopReason:'aborted'}]}},[1]), /已中止/u);
});
