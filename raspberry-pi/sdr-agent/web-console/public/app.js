const view = {
  state: null,
  active: null,
  provider: null,
  providerModels: [],
  settingsDirty: false,
  settingsOpen: false,
  reloadTimer: null,
  terminal: document.querySelector('#terminal'),
  sessions: document.querySelector('#sessions'),
  input: document.querySelector('#command-input'),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function loadState({ keepScroll = true } = {}) {
  const nearBottom = view.terminal.scrollHeight - view.terminal.scrollTop - view.terminal.clientHeight < 70;
  view.state = await api('/api/state');
  view.active = view.state.sessions.find((item) => item.id === view.state.active_session_id) || null;
  render();
  if (!keepScroll || nearBottom) scrollBottom();
}

function render() {
  renderSessions();
  renderTerminal();
  renderOverview();
  const enabled = Boolean(view.active);
  document.querySelectorAll('[data-command], #command-input, #command-form button, #auto-form input, #auto-form button').forEach((element) => { element.disabled = !enabled; });
}

async function loadProvider() {
  view.provider = await api('/api/provider');
  renderProvider();
}

function renderProvider() {
  if (!view.provider) return;
  const status = document.querySelector('#provider-status');
  if (view.provider.configured) {
    status.textContent = `${view.provider.provider} / ${view.provider.model} · ${formatTokens(view.provider.context_window)} · ${view.provider.compression_threshold_percent}% 压缩`;
    document.querySelector('#provider-api').value = view.provider.api;
    document.querySelector('#provider-base-url').value = view.provider.base_url;
    document.querySelector('#provider-id').value = view.provider.provider;
    document.querySelector('#provider-model').value = view.provider.model;
    document.querySelector('#provider-context-window').value = view.provider.context_window;
    document.querySelector('#provider-compression-threshold').value = view.provider.compression_threshold_percent;
  } else {
    status.textContent = '尚未配置第三方上游';
  }
  const survey = view.provider.initial_survey || defaultSurvey();
  const radio = document.querySelector(`input[name="survey-mode"][value="${survey.mode}"]`);
  if (radio) radio.checked = true;
  document.querySelector('#survey-start-mhz').value = hzToMhz(survey.start_hz);
  document.querySelector('#survey-stop-mhz').value = hzToMhz(survey.stop_hz);
  document.querySelector('#survey-step-mhz').value = hzToMhz(survey.step_hz);
  document.querySelector('#survey-dwell-ms').value = survey.dwell_ms;
  document.querySelector('#survey-gain-db').value = survey.gain_db ?? 20;
  document.querySelector('#provider-api-key').value = '';
  updateSurveyControls();
  markSettingsDirty(false);
}

function defaultSurvey() {
  return { mode: 'full_band', start_hz: 70000000, stop_hz: 6000000000, step_hz: 8000000, dwell_ms: 5, gain_db: 20 };
}

function surveyMode() {
  return document.querySelector('input[name="survey-mode"]:checked')?.value || 'full_band';
}

function surveyPayload() {
  return {
    mode: surveyMode(),
    start_hz: Math.round(Number(document.querySelector('#survey-start-mhz').value) * 1000000),
    stop_hz: Math.round(Number(document.querySelector('#survey-stop-mhz').value) * 1000000),
    step_hz: Math.round(Number(document.querySelector('#survey-step-mhz').value) * 1000000),
    dwell_ms: Number(document.querySelector('#survey-dwell-ms').value),
    gain_db: Number(document.querySelector('#survey-gain-db').value),
  };
}

function updateSurveyControls() {
  const mode = surveyMode();
  if (mode === 'full_band') {
    const survey = defaultSurvey();
    document.querySelector('#survey-start-mhz').value = hzToMhz(survey.start_hz);
    document.querySelector('#survey-stop-mhz').value = hzToMhz(survey.stop_hz);
    document.querySelector('#survey-step-mhz').value = hzToMhz(survey.step_hz);
    document.querySelector('#survey-dwell-ms').value = survey.dwell_ms;
  }
  document.querySelectorAll('#survey-fields input').forEach((input) => {
    input.disabled = mode === 'disabled' || (mode === 'full_band' && input.id !== 'survey-gain-db');
  });
  document.querySelector('#survey-fields').classList.toggle('fields-disabled', mode === 'disabled');
  updateSurveyBudget();
}

function updateSurveyBudget() {
  const budget = document.querySelector('#survey-budget');
  const summary = document.querySelector('#survey-budget-summary');
  const detail = document.querySelector('#survey-budget-detail');
  if (surveyMode() === 'disabled') {
    budget.dataset.state = 'disabled';
    summary.textContent = '首次扫描已关闭';
    detail.textContent = '新对话会直接进入控制台，不建立初始频谱。';
    return;
  }
  const survey = surveyPayload();
  const span = survey.stop_hz - survey.start_hz;
  const points = survey.step_hz > 0 && span >= 0 ? Math.ceil(span / survey.step_hz) + 1 : 0;
  const durationMs = points * (survey.dwell_ms + 250);
  const bytes = points * 4096 * 4;
  const valid = survey.start_hz >= 70000000 && survey.stop_hz <= 6000000000
    && survey.start_hz <= survey.stop_hz && survey.step_hz > 0 && survey.step_hz <= 8000000
    && survey.dwell_ms >= 0 && survey.dwell_ms <= 1000 && survey.gain_db >= 0 && survey.gain_db <= 60
    && points <= 768 && durationMs <= 300000;
  budget.dataset.state = valid ? 'ready' : 'error';
  summary.textContent = valid
    ? `${points} 点 · 约 ${Math.round(durationMs / 1000)} 秒 · 约 ${formatBytes(bytes)}`
    : '扫描预算超出安全边界';
  detail.textContent = valid
    ? `仅 RX，固定 ${survey.gain_db} dB 增益，10 MHz 采样率，4096 samples/点；可随时停止并恢复射频状态。`
    : '请限制在 70–6000 MHz、步进不超过 8 MHz、增益 0–60 dB、最多 768 点 / 300 秒。';
}

function hzToMhz(value) {
  return Number((Number(value) / 1000000).toFixed(6));
}

function formatBytes(value) {
  return value < 1048576 ? `${Math.round(value / 1024)} KiB` : `${(value / 1048576).toFixed(1)} MiB`;
}

function markSettingsDirty(dirty = true) {
  view.settingsDirty = dirty;
  document.querySelector('#settings-dirty-dot').hidden = !dirty;
  document.querySelector('#settings-save-state').textContent = dirty ? '有未保存修改' : '已载入当前设置';
  document.querySelector('#settings-view').classList.toggle('dirty', dirty);
}

function showSettings() {
  view.settingsOpen = true;
  document.querySelector('#console-view').hidden = true;
  document.querySelector('#settings-view').hidden = false;
  document.querySelector('#settings-entry').setAttribute('aria-expanded', 'true');
  document.querySelector('#settings-entry').classList.add('active');
  document.querySelector('#settings-title').focus?.();
}

function showConsole() {
  if (view.settingsDirty && !window.confirm('设置尚未保存，放弃修改并返回运行台？')) return;
  if (view.settingsDirty) renderProvider();
  view.settingsOpen = false;
  document.querySelector('#settings-view').hidden = true;
  document.querySelector('#console-view').hidden = false;
  document.querySelector('#settings-entry').setAttribute('aria-expanded', 'false');
  document.querySelector('#settings-entry').classList.remove('active');
}

function toggleSettings() {
  if (view.settingsOpen) showConsole(); else showSettings();
}

function discardSettings() {
  renderProvider();
  clearModelInventory();
  toast('未保存修改已放弃');
}

async function saveProvider(event) {
  event.preventDefault();
  const form = document.querySelector('#provider-form');
  if (!form.reportValidity()) return;
  const payload = {
    api: document.querySelector('#provider-api').value,
    base_url: document.querySelector('#provider-base-url').value.trim(),
    provider: document.querySelector('#provider-id').value.trim(),
    model: document.querySelector('#provider-model').value.trim(),
    api_key: document.querySelector('#provider-api-key').value,
    context_window: Number(document.querySelector('#provider-context-window').value),
    compression_threshold_percent: Number(document.querySelector('#provider-compression-threshold').value),
    initial_survey: surveyPayload(),
  };
  try {
    view.provider = await api('/api/provider', { method: 'PUT', body: JSON.stringify(payload) });
    document.querySelector('#provider-api-key').value = '';
    renderProvider();
    toast('设置已保存，将用于下一个新对话');
  } catch (error) { toast(error.message); }
}

async function queryProviderModels() {
  const baseUrl = document.querySelector('#provider-base-url');
  const apiKey = document.querySelector('#provider-api-key');
  if (!baseUrl.reportValidity()) return;
  const button = document.querySelector('#query-provider-models');
  clearModelInventory();
  const modelList = document.querySelector('#provider-model-list');
  modelList.replaceChildren(new Option('正在查询…', ''));
  modelList.disabled = true;
  button.disabled = true;
  button.textContent = '正在查询…';
  setModelInventoryStatus('正在连接上游 /models…', 'loading');
  try {
    const result = await api('/api/provider/models', {
      method: 'POST',
      body: JSON.stringify({ base_url: baseUrl.value.trim(), api_key: apiKey.value }),
    });
    renderModelInventory(result.models);
    toast(`上游返回 ${result.models.length} 个模型`);
  } catch (error) {
    modelList.replaceChildren(new Option('查询失败，请检查上方状态', ''));
    setModelInventoryStatus(error.message, 'error');
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = '查询上游模型';
  }
}

function renderModelInventory(models) {
  view.providerModels = models;
  const datalist = document.querySelector('#provider-model-options');
  const select = document.querySelector('#provider-model-list');
  datalist.replaceChildren();
  select.replaceChildren(new Option('选择一个上游模型…', ''));
  for (const model of models) {
    datalist.append(new Option('', model.id));
    select.append(new Option(model.context_window ? `${model.id} · ${formatTokens(model.context_window)}` : `${model.id} · 上游未提供上下文`, model.id));
  }
  select.disabled = false;
  const withContext = models.filter((model) => model.context_window).length;
  setModelInventoryStatus(`已发现 ${models.length} 个模型，其中 ${withContext} 个带上下文窗口`, 'ready');
  applySelectedModel(document.querySelector('#provider-model').value);
}

function applySelectedModel(modelId) {
  const selected = view.providerModels.find((model) => model.id === modelId);
  if (selected?.context_window) {
    document.querySelector('#provider-context-window').value = selected.context_window;
    markSettingsDirty();
    toast(`已采用上游返回的上下文窗口：${formatTokens(selected.context_window)}`);
  }
}

function setModelInventoryStatus(message, state) {
  const inventory = document.querySelector('#model-inventory');
  inventory.hidden = false;
  inventory.dataset.state = state;
  document.querySelector('#model-inventory-status').textContent = message;
}

function clearModelInventory() {
  view.providerModels = [];
  document.querySelector('#provider-model-options').replaceChildren();
  const select = document.querySelector('#provider-model-list');
  select.replaceChildren();
  select.disabled = true;
  document.querySelector('#model-inventory').hidden = true;
}

async function clearProvider() {
  if (!window.confirm('清除私密上游配置？新对话将回退到部署环境配置。')) return;
  try {
    view.provider = await api('/api/provider', { method: 'DELETE' });
    document.querySelector('#provider-form').reset();
    clearModelInventory();
    renderProvider();
    toast('上游配置已清除');
  } catch (error) { toast(error.message); }
}

function presetOpenCode() {
  document.querySelector('#provider-api').value = 'openai-completions';
  document.querySelector('#provider-base-url').value = 'https://opencode.ai/zen/go/v1';
  document.querySelector('#provider-id').value = 'opencode-go';
  document.querySelector('#provider-model').value = 'deepseek-v4-flash';
  document.querySelector('#provider-context-window').value = '196608';
  document.querySelector('#provider-compression-threshold').value = '90';
  clearModelInventory();
  markSettingsDirty();
  document.querySelector('#provider-api-key').focus();
}

function clearProviderFields() {
  document.querySelector('#provider-form').reset();
  clearModelInventory();
  updateSurveyControls();
  markSettingsDirty();
  document.querySelector('#provider-base-url').focus();
}

function apiLabel(apiName) {
  return apiName === 'openai-responses' ? 'Responses' : 'Chat Completions';
}

function renderSessions() {
  view.sessions.replaceChildren();
  for (const session of [...view.state.sessions].sort((a, b) => b.last_used_at_ms - a.last_used_at_ms)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `session${session.id === view.state.active_session_id ? ' active' : ''}`;
    const title = document.createElement('strong');
    title.textContent = session.title;
    const meta = document.createElement('span');
    meta.textContent = sessionMeta(session);
    button.append(title, meta);
    button.addEventListener('click', () => activate(session.id));
    view.sessions.append(button);
  }
}

function renderTerminal() {
  const activeTitle = document.querySelector('#active-title');
  const activeMeta = document.querySelector('#active-meta');
  view.terminal.replaceChildren();
  if (!view.active) {
    activeTitle.textContent = '未选择对话';
    activeMeta.textContent = '新建对话后将连接 sdr-agent';
    const empty = document.createElement('div');
    empty.className = 'terminal-empty';
    empty.textContent = '尚无终端输出';
    view.terminal.append(empty);
    return;
  }
  activeTitle.textContent = view.active.title;
  const compacted = view.active.compaction_count || 0;
  activeMeta.textContent = `${statusLabel(view.active.status)} · ${view.active.events.length} 条可见记录${compacted ? ` · 已压缩 ${compacted} 次` : ''}`;
  for (const event of view.active.events) {
    const row = document.createElement('div');
    row.className = `line ${safeKind(event.kind)}`;
    const time = document.createElement('time');
    time.textContent = new Date(event.timestamp_ms).toLocaleTimeString('zh-CN', { hour12: false });
    const kind = document.createElement('span');
    kind.className = 'kind';
    kind.textContent = kindLabel(event.kind);
    const text = document.createElement('span');
    text.className = 'text';
    text.textContent = event.text;
    row.append(time, kind, text);
    view.terminal.append(row);
  }
}

function renderOverview() {
  setText('#controller-status', view.active ? `${statusLabel(view.active.status)} · ${view.active.title}` : '等待活动对话');
  setText('#sweep-status', latestText('sweep') || initialSurveyLabel(view.active?.initial_survey_status));
  setText('#qwen-status', latestText('qwen') || '尚无模型输出');
  setText('#cruise-status', latestText('cruise') || '逐步批准模式');
}

function latestText(kind) {
  if (!view.active) return '';
  return [...view.active.events].reverse().find((event) => event.kind === kind)?.text || '';
}

async function createSession() {
  try {
    await api('/api/sessions', { method: 'POST', body: JSON.stringify({}) });
    await loadState({ keepScroll: false });
  } catch (error) { toast(error.message); }
}

async function activate(id) {
  if (id === view.state.active_session_id) return;
  try {
    await api(`/api/sessions/${encodeURIComponent(id)}/activate`, { method: 'POST', body: '{}' });
    await loadState({ keepScroll: false });
  } catch (error) { toast(error.message); }
}

async function send(command) {
  if (!view.active || !command.trim()) return;
  try {
    await api(`/api/sessions/${encodeURIComponent(view.active.id)}/command`, {
      method: 'POST', body: JSON.stringify({ command }),
    });
    view.input.value = '';
    await loadState({ keepScroll: false });
  } catch (error) { toast(error.message); }
}

async function startAuto(event) {
  event.preventDefault();
  const form = document.querySelector('#auto-form');
  const mission = document.querySelector('#auto-mission');
  if (!form.reportValidity()) return;
  const steps = Number(document.querySelector('#auto-steps').value);
  const seconds = Number(document.querySelector('#auto-seconds').value);
  await send(`/auto start --steps ${steps} --seconds ${seconds} ${mission.value.trim()}`);
}

function connectEvents() {
  const source = new EventSource('/api/events');
  source.onopen = () => {
    setConnection(true, '局域网实时连接');
    loadState().catch((error) => toast(error.message));
  };
  source.onerror = () => setConnection(false, '正在重新连接');
  source.onmessage = () => {
    clearTimeout(view.reloadTimer);
    view.reloadTimer = setTimeout(() => loadState().catch((error) => toast(error.message)), 80);
  };
}

function setConnection(online, text) {
  const node = document.querySelector('.connection');
  node.classList.toggle('online', online);
  setText('#connection-text', text);
}

function toast(message) {
  const node = document.querySelector('#toast');
  node.textContent = message;
  node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 3000);
}

function scrollBottom() { view.terminal.scrollTop = view.terminal.scrollHeight; }
function setText(selector, text) { document.querySelector(selector).textContent = text; }
function safeKind(value) { return /^[a-z]+$/.test(value) ? value : 'system'; }
function kindLabel(kind) {
  return ({ system: '系统', prompt: '提示', operator: '操作员', qwen: '上游模型', plan: '已验证计划', execution: '执行', sweep: '扫频', cruise: '巡航', error: '错误' })[kind] || '系统';
}
function formatTokens(value) {
  return `${new Intl.NumberFormat('zh-CN').format(value)} tokens`;
}
function sessionMeta(session) {
  const compacted = session.compaction_count || 0;
  const survey = initialSurveyLabel(session.initial_survey_status, true);
  return `${statusLabel(session.status)}${survey ? ` · ${survey}` : ''}${compacted ? ` · 已压缩 ${compacted} 次` : ''}`;
}
function initialSurveyLabel(status, compact = false) {
  const labels = compact
    ? { pending: '待初扫', running: '初扫中', complete: '初扫完成', failed: '初扫失败', skipped: '' }
    : { pending: '首次扫频等待启动', running: '首次全频扫描中', complete: '首次频谱已建立', failed: '首次扫频失败', skipped: '首次扫描已关闭' };
  return labels[status] ?? (compact ? '' : '尚无扫频输出');
}
function statusLabel(status) {
  return ({ connected: '已连接', stored: '已保存', starting: '启动中', exited: '已退出', error: '错误' })[status] || status;
}

document.querySelector('#new-session').addEventListener('click', createSession);
document.querySelector('#provider-form').addEventListener('submit', saveProvider);
document.querySelector('#query-provider-models').addEventListener('click', queryProviderModels);
document.querySelector('#provider-model-list').addEventListener('change', (event) => {
  if (event.target.value) {
    document.querySelector('#provider-model').value = event.target.value;
    applySelectedModel(event.target.value);
  }
});
document.querySelector('#provider-base-url').addEventListener('input', () => {
  if (view.providerModels.length) clearModelInventory();
});
document.querySelector('#provider-api-key').addEventListener('input', () => {
  if (view.providerModels.length) clearModelInventory();
});
document.querySelector('#preset-opencode').addEventListener('click', presetOpenCode);
document.querySelector('#preset-custom').addEventListener('click', clearProviderFields);
document.querySelector('#settings-entry').addEventListener('click', toggleSettings);
document.querySelector('#settings-back').addEventListener('click', showConsole);
document.querySelector('#discard-settings').addEventListener('click', discardSettings);
document.querySelector('#provider-form').addEventListener('input', (event) => {
  if (event.target.closest('#survey-fields') || event.target.name === 'survey-mode') updateSurveyBudget();
  markSettingsDirty();
});
document.querySelectorAll('input[name="survey-mode"]').forEach((radio) => radio.addEventListener('change', () => {
  updateSurveyControls();
  markSettingsDirty();
}));
document.querySelector('#scroll-bottom').addEventListener('click', scrollBottom);
document.querySelector('#auto-form').addEventListener('submit', startAuto);
document.querySelectorAll('[data-command]').forEach((button) => button.addEventListener('click', () => send(button.dataset.command)));
document.querySelector('#command-form').addEventListener('submit', (event) => { event.preventDefault(); send(view.input.value); });
view.input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && event.ctrlKey) { event.preventDefault(); send(view.input.value); }
});
window.addEventListener('beforeunload', (event) => {
  if (!view.settingsDirty) return;
  event.preventDefault();
  event.returnValue = '';
});

Promise.all([loadState({ keepScroll: false }), loadProvider()])
  .then(connectEvents)
  .catch((error) => toast(error.message));
