// Preserve the actual provider failure without exposing authentication material.
export function formatUpstreamError(error, secrets = []) {
  let text = error instanceof Error ? error.message : String(error || 'unknown upstream error');
  for (const secret of secrets) {
    if (secret) text = text.split(secret).join('[redacted]');
  }
  text = text
    .replace(/Bearer\s+[^\s"',;]+/giu, 'Bearer [redacted]')
    .replace(/https?:\/\/[^\s"']+/giu, '[upstream URL]')
    .replace(/[\r\n\u0000-\u001f\u007f]+/gu, ' ');
  if (/^Connection error\.?$/iu.test(text.trim())) {
    return '连接失败；请检查上游地址、网络和系统证书信任。';
  }
  return text.slice(0, 400);
}

export function describeMissingPlan(agent, requestIds = [], secrets = []) {
  const messages = agent?.state?.messages;
  const assistant = Array.isArray(messages)
    ? messages.findLast(message => message?.role === 'assistant')
    : undefined;
  const request = requestIds.length ? `request=${requestIds.join(',')}，` : '';
  const error = assistant?.errorMessage || agent?.state?.errorMessage;
  if (error) return `${request}上游请求失败：${formatUpstreamError(error, secrets)}`;
  if (assistant?.stopReason === 'length') return `${request}上游输出达到 token 上限，未提交下一步计划。`;
  if (assistant?.stopReason === 'aborted') return `${request}上游请求已中止，未提交下一步计划。`;
  return `上游模型结束了本轮生成，但 ${request}没有提交下一步计划`;
}
